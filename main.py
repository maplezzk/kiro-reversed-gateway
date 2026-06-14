# -*- coding: utf-8 -*-
"""
kiro-reversed-gateway - 主入口

Kiro API → 自定义大模型 API 反向代理。

将 Kiro IDE 发出的专有 API 请求转换为 OpenAI 标准格式，
转发给用户自己的大模型 API，并将响应转回 Kiro 格式。

使用方式:
    # 生成自签名证书（用于 HTTPS，覆盖 runtime + management）:
    mkdir -p certs
    openssl req -x509 -newkey rsa:4096 \\
      -keyout certs/key.pem -out certs/cert.pem \\
      -days 365 -nodes \\
      -subj "/CN=runtime.us-east-1.kiro.dev" \\
      -addext "subjectAltName=DNS:runtime.us-east-1.kiro.dev,DNS:management.us-east-1.kiro.dev,DNS:*.kiro.dev"

    # 启动:
    python main.py

流量劫持方案:
    1. hosts 劫持: 将 runtime.us-east-1.kiro.dev / management.us-east-1.kiro.dev 指向 127.0.0.1
        编辑 /etc/hosts:
        127.0.0.1 runtime.us-east-1.kiro.dev
        127.0.0.1 management.us-east-1.kiro.dev
    2. 启动代理（HTTPS 模式，端口 443）:
        sudo python main.py --port 443
    3. 信任自签名证书（Kiro IDE 信任 CA 证书）:
        sudo security add-trusted-cert -d -r trustRoot \\
          -k /Library/Keychains/System.keychain certs/cert.pem
"""

import sys
import argparse
import logging
import os
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from kiro_reversed.config import (
    SERVER_HOST,
    SERVER_PORT,
    USE_TLS,
    CERT_FILE,
    KEY_FILE,
    LOG_LEVEL,
    BACKEND_API_URL,
    MODE,
)


# --- Loguru 配置 ---
logger.remove()
logger.add(
    sys.stderr,
    level=LOG_LEVEL,
    colorize=True,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
)


# --- 拦截 uvicorn 日志 ---
class InterceptHandler(logging.Handler):
    def emit(self, record):
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def setup_logging():
    for name in ["uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"]:
        lg = logging.getLogger(name)
        lg.handlers = [InterceptHandler()]
        lg.propagate = False


setup_logging()

# --- FastAPI 应用 ---
app = FastAPI(
    title="kiro-reversed-gateway",
    description="反向代理 Kiro API → 自定义大模型 API",
    version="0.1.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 路由
from kiro_reversed.routes import router
app.include_router(router)


# --- 入口 ---
def parse_args():
    parser = argparse.ArgumentParser(
        description="kiro-reversed-gateway - Kiro API → 自定义大模型 API 反向代理",
    )
    parser.add_argument("-H", "--host", type=str, default=None, help=f"监听地址 (默认: {SERVER_HOST})")
    parser.add_argument("-p", "--port", type=int, default=None, help=f"监听端口 (默认: {SERVER_PORT})")
    parser.add_argument("--no-tls", action="store_true", help="禁用 TLS (仅用于 HTTP 模式调试)")
    return parser.parse_args()


def _contains_placeholder(value: str) -> bool:
    """Return True when a config value still contains documentation placeholders."""
    return "<" in value or ">" in value


def _validate_url(value: str, field_name: str) -> list[str]:
    """Validate an HTTP/HTTPS URL config value."""
    errors: list[str] = []
    if _contains_placeholder(value):
        errors.append(f"{field_name} 仍包含占位符，请替换成真实地址")
        return errors

    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        errors.append(f"{field_name} 必须是合法的 http/https URL，例如 http://host:port/v1")
    return errors


def _required_forward_ip_envs(forward_target: str) -> tuple[str, ...]:
    """Return required upstream IP environment variables for forward target."""
    required_by_target: dict[str, tuple[str, ...]] = {
        "auto": ("KIRO_RUNTIME_IP", "KIRO_MANAGEMENT_IP"),
        "runtime": ("KIRO_RUNTIME_IP",),
        "management": ("KIRO_MANAGEMENT_IP",),
        "q": ("KIRO_Q_IP",),
        "random": ("KIRO_RUNTIME_IP", "KIRO_MANAGEMENT_IP", "KIRO_Q_IP"),
    }
    return required_by_target[forward_target]


def validate_startup_config(host: str, port: int, use_tls: bool) -> None:
    """Validate core startup configuration and exit before serving on errors."""
    errors: list[str] = []
    warnings: list[str] = []

    if not host.strip():
        errors.append("SERVER_HOST 不能为空")

    if not 1 <= port <= 65535:
        errors.append(f"SERVER_PORT 必须在 1-65535 之间，当前值: {port}")

    mode = MODE.strip().lower()
    if mode not in {"openai", "forward"}:
        errors.append(f"MODE 只能是 openai 或 forward，当前值: {MODE!r}")

    forward_target = os.getenv("FORWARD_TARGET", "auto").strip().lower()
    allowed_forward_targets = {"auto", "runtime", "management", "q", "random"}
    if forward_target not in allowed_forward_targets:
        errors.append(
            "FORWARD_TARGET 只能是 auto/runtime/management/q/random，"
            f"当前值: {forward_target!r}"
        )

    if mode == "openai":
        if not BACKEND_API_URL:
            errors.append("MODE=openai 时必须配置 BACKEND_API_URL，推荐格式: http://host:port/v1")
        else:
            errors.extend(_validate_url(BACKEND_API_URL, "BACKEND_API_URL"))

    if use_tls:
        if not CERT_FILE:
            errors.append("USE_TLS=true 时必须配置 CERT_FILE")
        if not KEY_FILE:
            errors.append("USE_TLS=true 时必须配置 KEY_FILE")
        if CERT_FILE and not Path(CERT_FILE).is_file():
            errors.append(f"TLS 证书不存在: {Path(CERT_FILE).resolve()}")
        if KEY_FILE and not Path(KEY_FILE).is_file():
            errors.append(f"TLS 私钥不存在: {Path(KEY_FILE).resolve()}")

    if mode == "forward":
        missing_forward_ips = [
            name for name in _required_forward_ip_envs(forward_target)
            if not os.getenv(name, "").strip()
        ]
        if missing_forward_ips:
            errors.append(
                "MODE=forward 必须配置对应官方上游 IP；"
                f"当前 FORWARD_TARGET={forward_target!r}，缺少: {', '.join(missing_forward_ips)}"
            )

    if warnings:
        for warning in warnings:
            logger.warning(warning)

    if errors:
        print()
        print("  ❌ 配置校验失败，服务未启动：")
        for error in errors:
            print(f"   - {error}")
        print()
        sys.exit(1)


if __name__ == "__main__":
    import uvicorn

    args = parse_args()
    host = args.host or SERVER_HOST
    port = args.port or SERVER_PORT
    use_tls = USE_TLS and not args.no_tls

    validate_startup_config(host, port, use_tls)

    # 打印启动信息
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RESET = "\033[0m"
    BOLD = "\033[1m"

    print()
    print(f"  {BOLD}🔄 kiro-reversed-gateway v0.1.0{RESET}")
    print()
    print(f"  {GREEN}后端 API:{RESET} {BACKEND_API_URL}")

    if use_tls:
        print(f"  {CYAN}模式:{RESET}     HTTPS (TLS)")
        cert = os.path.abspath(CERT_FILE)
        key = os.path.abspath(KEY_FILE)
        print(f"  {CYAN}证书:{RESET}     {cert}")
        print(f"  {CYAN}密钥:{RESET}     {key}")
    else:
        print(f"  {CYAN}模式:{RESET}     HTTP (无 TLS)")

    protocol = "https" if use_tls else "http"
    print(f"  {CYAN}监听:{RESET}     {protocol}://{host}:{port}")
    print()

    uvicorn_config = {
        "host": host,
        "port": port,
        "log_config": {
            "version": 1,
            "disable_existing_loggers": False,
            "handlers": {
                "default": {"class": "main.InterceptHandler"},
            },
            "loggers": {
                "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
                "uvicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
                "uvicorn.access": {"handlers": ["default"], "level": "INFO", "propagate": False},
            },
        },
    }

    if use_tls:
        uvicorn_config["ssl_keyfile"] = KEY_FILE
        uvicorn_config["ssl_certfile"] = CERT_FILE

    uvicorn.run("main:app", **uvicorn_config)
