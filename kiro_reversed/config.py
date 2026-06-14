# -*- coding: utf-8 -*-
"""
kiro-reversed-gateway 配置模块
"""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

# --- 服务器配置 ---
SERVER_HOST: str = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT: int = int(os.getenv("SERVER_PORT", "8443"))

# --- 后端 API 配置 ---
BACKEND_API_URL: str = os.getenv("BACKEND_API_URL", "").strip()
BACKEND_API_KEY: str = os.getenv("BACKEND_API_KEY", "")

# --- TLS 配置 ---
USE_TLS: bool = os.getenv("USE_TLS", "true").lower() in ("true", "1", "yes")
CERT_FILE: str = os.getenv("CERT_FILE", "certs/cert.pem")
KEY_FILE: str = os.getenv("KEY_FILE", "certs/key.pem")

# --- 超时 ---
REQUEST_TIMEOUT: float = float(os.getenv("REQUEST_TIMEOUT", "600"))
FIRST_TOKEN_TIMEOUT: float = float(os.getenv("FIRST_TOKEN_TIMEOUT", "60"))

# --- 运行模式 ---
# "openai": Kiro → OpenAI 转换模式 (默认, 走自定义后端)
# "forward": 纯转发模式 (直连 Kiro 真实 API, 不走转换)
# "hybrid": 混合模式 (官方模型走 Kiro, custom/* 模型走自定义后端)
MODE: str = os.getenv("MODE", "openai")

# --- 日志 ---
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# --- Kiro Profile 兜底 ---
PROFILE_ARN: str = os.getenv("PROFILE_ARN", "").strip()

# --- 模型 ---
SIMPLE_TASK_MODEL: str = os.getenv("SIMPLE_TASK_MODEL", "").strip()
CUSTOM_MODEL_PREFIX: str = os.getenv("CUSTOM_MODEL_PREFIX", "custom/").strip() or "custom/"


def strip_custom_model_prefix(model_id: str) -> str:
    """Strip the custom model prefix before sending requests to backend."""
    if model_id.startswith(CUSTOM_MODEL_PREFIX):
        return model_id[len(CUSTOM_MODEL_PREFIX):]
    return model_id


def map_model(kiro_model_id: str) -> str:
    """Map Kiro model IDs to backend model IDs."""
    backend_model_id = strip_custom_model_prefix(kiro_model_id)
    if backend_model_id == "simple-task" and SIMPLE_TASK_MODEL:
        return SIMPLE_TASK_MODEL
    return backend_model_id
