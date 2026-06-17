# -*- coding: utf-8 -*-
"""
FastAPI 路由 —— 暴露 Kiro API 兼容端点。

支持两种模式 (通过环境变量 MODE 控制):
  MODE=openai   : Kiro → OpenAI 转换模式 (默认)
  MODE=forward  : 纯转发模式, 直连 Kiro 真实 API
"""

import json
import re
import struct
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse, Response
from loguru import logger

from kiro_reversed.config import MODE, PROFILE_ARN, CUSTOM_MODEL_PREFIX
from kiro_reversed.forward import KIRO_FORWARD_HOSTS, KIRO_FORWARD_TARGETS
from kiro_reversed.models import KiroRequest
from kiro_reversed.kiro_to_openai import convert_kiro_to_openai
from kiro_reversed.openai_to_kiro import (
    convert_openai_stream_to_kiro,
    convert_openai_non_stream_to_kiro,
)
from kiro_reversed.http_client import send_to_backend, fetch_backend_models

router = APIRouter()

# JSONL 日志目录
LOG_DIR = Path(__file__).parent.parent / "debug_logs"
LOG_DIR.mkdir(exist_ok=True)


def _save_log(conv_id: str, stage: str, data) -> None:
    """保存请求/响应到 JSONL 文件"""
    try:
        safe_id = conv_id.replace("/", "_").replace(":", "_") or "unknown"
        path = LOG_DIR / f"{safe_id}.jsonl"
        record = {"ts": time.time(), "stage": stage}
        if isinstance(data, (bytes, bytearray)):
            record["raw_bytes"] = data.hex()
        else:
            record["data"] = data
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"保存日志失败: {e}")


async def _save_raw_response_bytes(conv_id: str, stage: str, chunks: list) -> None:
    """保存流式响应的原始字节 (长度前缀 + 原始字节)"""
    try:
        safe_id = conv_id.replace("/", "_").replace(":", "_") or "unknown"
        suffix = f"_{int(time.time()*1000)%100000}"
        path = LOG_DIR / f"{safe_id}{suffix}.binlog"
        with open(path, "ab") as f:
            for chunk in chunks:
                f.write(struct.pack("!I", len(chunk)))
                f.write(chunk)
    except Exception as e:
        logger.warning(f"保存原始响应失败: {e}")


@router.get("/")
async def root():
    """健康检查"""
    return {
        "status": "ok",
        "service": "kiro-reversed-gateway",
        "mode": MODE,
        "description": "反向代理 Kiro API → 自定义大模型 API",
    }


def _build_models_response(models: list[dict], log_stage: str = "list_available_models") -> Response:
    """Build a Kiro-compatible model list response."""
    _save_log("models", log_stage, {"count": len(models), "models": models})
    return Response(
        content=json.dumps({"models": models}, ensure_ascii=False),
        media_type="application/json",
        headers={
            "cache-control": "no-store, no-cache, must-revalidate",
            "pragma": "no-cache",
            "expires": "0",
        },
    )


def _parse_context_length_from_model_id(model_id: str) -> int | None:
    """Parse context length suffix from a model id.

    Supported suffix examples:
    - ``model-name[256k]`` -> 256000
    - ``model-name[1m]`` -> 1000000
    """
    match = re.search(r"\[\s*(\d+(?:\.\d+)?)\s*([kKmM])\s*\]\s*$", model_id)
    if not match:
        return None

    value = float(match.group(1))
    unit = match.group(2).lower()
    multiplier = 1_000 if unit == "k" else 1_000_000
    return int(value * multiplier)


def _get_backend_model_context_length(item: dict, raw_model_id: str) -> int:
    """Return max input tokens from backend metadata, model suffix, or default."""
    explicit_value = item.get("maxInputTokens") or item.get("context_length")
    if explicit_value:
        return int(explicit_value)

    suffix_value = _parse_context_length_from_model_id(raw_model_id)
    if suffix_value:
        return suffix_value

    return 200000


async def _build_backend_model_items(prefix_custom: bool = False) -> list[dict]:
    """Build Kiro-compatible model items from backend OpenAI /models."""
    backend_models = await fetch_backend_models()
    models = []
    for item in backend_models:
        raw_model_id = item.get("id") or item.get("model") or item.get("modelId")
        if not raw_model_id:
            continue
        model_id = raw_model_id
        if prefix_custom and not raw_model_id.startswith(CUSTOM_MODEL_PREFIX):
            model_id = f"{CUSTOM_MODEL_PREFIX}{raw_model_id}"
        models.append({
            "modelId": model_id,
            "modelName": model_id if prefix_custom else item.get("modelName") or item.get("name") or model_id,
            "description": item.get("description") or f"Custom backend model: {raw_model_id}",
            "modelProvider": item.get("modelProvider") or ("CUSTOM" if prefix_custom else "DEFAULT"),
            "rateMultiplier": item.get("rateMultiplier") or 1,
            "rateUnit": item.get("rateUnit") or "request",
            "supportedInputTypes": item.get("supportedInputTypes") or ["TEXT", "IMAGE"],
            "promptCaching": item.get("promptCaching") or {"supportsPromptCaching": False},
            "tokenLimits": {
                "maxInputTokens": _get_backend_model_context_length(item, raw_model_id),
                "maxOutputTokens": item.get("maxOutputTokens") or 8192,
            },
        })
    return models


async def _build_backend_models_response() -> Response:
    """Build Kiro-compatible models response from backend OpenAI /models."""
    models = await _build_backend_model_items(prefix_custom=False)
    return _build_models_response(models)


def _get_stable_next_month_reset_timestamp() -> int:
    """Return a stable monthly reset timestamp for synthetic usage data.

    Kiro shows a reset notification when the reset date moves forward. Returning
    ``now + 30 days`` would drift on every request, so use the first day of the
    next UTC month to keep the value stable within the current month.
    """
    now = datetime.now(timezone.utc)
    if now.month == 12:
        reset_date = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        reset_date = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
    return int(reset_date.timestamp())


async def _build_usage_limits_response(request: Request) -> Response:
    """Build a displayable local Kiro usage limits response.

    The values are synthetic and represent custom backend usage, not official Kiro billing.
    """
    reset_at = _get_stable_next_month_reset_timestamp()
    current_usage = 12
    usage_limit = 100000
    usage_breakdown = {
        "resourceType": "CUSTOM_BACKEND_REQUEST",
        "displayName": "Custom Backend Request",
        "displayNamePlural": "Custom Backend Requests",
        "unit": "requests",
        "currentUsage": current_usage,
        "currentUsageWithPrecision": current_usage,
        "usageLimit": usage_limit,
        "usageLimitWithPrecision": usage_limit,
        "percentUsed": current_usage / usage_limit * 100,
        "nextDateReset": reset_at,
        "currency": "USD",
        "currentOverages": 0,
        "currentOveragesWithPrecision": 0,
        "overageCap": 0,
        "overageCapWithPrecision": 0,
        "overageCharges": 0,
        "overageRate": 0,
    }
    data = {
        "daysUntilReset": 30,
        "nextDateReset": reset_at,
        "limits": [
            {
                "type": "CUSTOM_BACKEND_REQUEST",
                "currentUsage": current_usage,
                "totalUsageLimit": usage_limit,
                "percentUsed": current_usage / usage_limit * 100,
            }
        ],
        "totalUsage": {
            "currentUsage": current_usage,
            "usageLimit": usage_limit,
            "percentUsed": current_usage / usage_limit * 100,
        },
        "usageBreakdown": usage_breakdown,
        "usageBreakdownList": [usage_breakdown],
        "subscriptionInfo": {
            "type": "CUSTOM",
            "subscriptionTitle": "Custom Backend Plan",
            "subscriptionManagementTarget": "CUSTOM",
            "overageCapability": "NOT_OVERAGE_CAPABLE",
            "upgradeCapability": "NOT_UPGRADE_CAPABLE",
        },
        "overageConfiguration": {
            "overageStatus": "DISABLED",
        },
        "userInfo": {
            "userId": "custom-backend-user",
            "email": "custom-backend@local",
        },
    }
    _save_log(
        "usage_limits",
        "local_usage_limits",
        {
            "path": request.url.path,
            "query": request.url.query,
            "response": data,
        },
    )
    return Response(
        content=json.dumps(data, ensure_ascii=False),
        media_type="application/json",
        headers={
            "cache-control": "no-store, no-cache, must-revalidate",
            "pragma": "no-cache",
            "expires": "0",
        },
    )


def _get_profile_arn_from_request(request: Request) -> str:
    """Get the profile ARN from query/header with a configured fallback."""
    return (
        request.query_params.get("profileArn")
        or request.headers.get("x-amzn-kiro-profile-arn")
        or PROFILE_ARN
    )


async def _build_profile_response(request: Request) -> Response:
    """Build minimal valid profile responses for Kiro management UI."""
    profile_arn = _get_profile_arn_from_request(request)
    profile = {
        "arn": profile_arn,
        "profileArn": profile_arn,
        "profileName": "Custom Backend",
        "name": "Custom Backend",
    }
    path = request.url.path.lower()
    data = {"profiles": [profile]} if "list" in path else {"profile": profile}
    _save_log(
        "profiles",
        "local_profile_response",
        {
            "path": request.url.path,
            "query": request.url.query,
            "response": data,
        },
    )
    return Response(
        content=json.dumps(data, ensure_ascii=False),
        media_type="application/json",
        headers={
            "cache-control": "no-store, no-cache, must-revalidate",
            "pragma": "no-cache",
            "expires": "0",
        },
    )


@router.api_route("/ListAvailableModels", methods=["GET", "POST"])
@router.api_route("/listAvailableModels", methods=["GET", "POST"])
@router.api_route("/list_available_models", methods=["GET", "POST"])
@router.api_route("/models", methods=["GET", "POST"])
@router.api_route("/v1/models", methods=["GET", "POST"])
async def list_available_models(request: Request):
    """Kiro/OpenAI models endpoint.

    MODE=forward: 纯转发官方 /ListAvailableModels。
    MODE=hybrid : 合并官方 Kiro models + custom/* 后端 models。
    MODE=openai : 读取后端 OpenAI /models，并转换成 Kiro 的 models 格式。
    """
    if MODE == "forward":
        return await _handle_forward_mode(request)
    if MODE == "hybrid":
        try:
            return await _build_hybrid_models_response(request)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"获取混合 models 失败: {e}")
            raise HTTPException(status_code=502, detail=f"获取混合 models 失败: {e}")

    try:
        return await _build_backend_models_response()
    except Exception as e:
        logger.error(f"获取后端 models 失败: {e}")
        raise HTTPException(status_code=502, detail=f"获取后端 models 失败: {e}")


@router.api_route("/getUsageLimits", methods=["GET", "POST"])
@router.api_route("/GetUsageLimits", methods=["GET", "POST"])
@router.api_route("/Get-Usage-Limits", methods=["GET", "POST"])
async def get_usage_limits(request: Request):
    """Return usage limits response or forward it in official-capable modes."""
    if MODE in ("forward", "hybrid"):
        return await _handle_forward_mode(request)
    return await _build_usage_limits_response(request)


@router.api_route("/ListAvailableProfiles", methods=["GET", "POST"])
@router.api_route("/listAvailableProfiles", methods=["GET", "POST"])
@router.api_route("/List-Available-Profiles", methods=["GET", "POST"])
@router.api_route("/GetProfile", methods=["GET", "POST"])
@router.api_route("/Get-Profile", methods=["GET", "POST"])
async def profile_endpoints(request: Request):
    """Return profile responses or forward them in official-capable modes."""
    if MODE in ("forward", "hybrid"):
        return await _handle_forward_mode(request)
    return await _build_profile_response(request)


# ============ 纯转发模式 ============

import random as _random


def _normalize_host_header(host_value: str | None) -> str:
    """Normalize incoming Host header to a bare lowercase hostname."""
    if not host_value:
        return ""
    return host_value.split(":", 1)[0].strip().lower()


def _get_request_host(request: Request) -> str:
    """Return the normalized incoming host name for routing decisions."""
    return _normalize_host_header(request.headers.get("host") or request.url.hostname)


def _resolve_forward_target_name(request: Request | None = None) -> str:
    """Resolve the upstream target name for a request."""
    import os

    target_name = os.getenv("FORWARD_TARGET", "auto").strip().lower()
    if MODE == "hybrid" and request is not None:
        target_name = "auto"
    if target_name in ("", "auto") and request is not None:
        request_host = _get_request_host(request)
        if request_host in KIRO_FORWARD_HOSTS:
            return KIRO_FORWARD_HOSTS[request_host]
        if request_host.startswith("management.") and request_host.endswith(".kiro.dev"):
            return "management"
        if request_host.startswith("runtime.") and request_host.endswith(".kiro.dev"):
            return "runtime"
        return "runtime"
    if target_name == "random":
        return "random"
    return target_name if target_name in KIRO_FORWARD_TARGETS else "runtime"


def _pick_forward_target(request: Request | None = None) -> dict:
    """根据请求 Host 或 FORWARD_TARGET 选择转发目标。

    支持:
      auto      : 根据请求 Host 自动选择 runtime/management/q
      runtime   : runtime Kiro host
      management: management Kiro host
      q         : Amazon Q host
      random    : 随机选择
    """
    target_name = _resolve_forward_target_name(request)
    if target_name == "random":
        return _random.choice(list(KIRO_FORWARD_TARGETS.values()))
    return KIRO_FORWARD_TARGETS[target_name]


def _prepare_forward_upstream(request: Request, raw_body: bytes) -> tuple[str, dict, str, str]:
    """Prepare upstream URL and headers for official Kiro forwarding."""
    target = _pick_forward_target(request)
    ip = target.get("ip", "")
    host_header = target["host"]
    if not ip:
        message = f"MODE=forward 必须为 {host_header} 配置官方上游 IP"
        logger.error(f"[FWD] {message}")
        raise HTTPException(status_code=502, detail=message)

    fwd_headers = {}
    for k, v in request.headers.items():
        if k.lower() in ("host", "content-length", "connection"):
            continue
        fwd_headers[k] = v
    fwd_headers["host"] = host_header

    target_url = f"https://{ip}{request.url.path}"
    if request.url.query:
        target_url += f"?{request.url.query}"

    logger.info(
        f"[FWD] -> {host_header}({ip}){request.url.path} "
        f"({len(raw_body)} bytes, upstream_host={ip})"
    )
    return target_url, fwd_headers, host_header, ip


async def _fetch_forward_body(request: Request, raw_body: bytes | None = None) -> tuple[int, dict, bytes]:
    """Fetch a full official Kiro upstream response body."""
    body = await request.body() if raw_body is None else raw_body
    target_url, fwd_headers, host_header, ip = _prepare_forward_upstream(request, body)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0),
        verify=False if ip else True,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        response = await client.send(
            client.build_request(
                method=request.method,
                url=target_url,
                headers=fwd_headers,
                content=body,
            ),
            stream=False,
        )
        logger.info(f"[FWD] Kiro 真实 API 响应: status={response.status_code}")
        out_headers = {
            k: v for k, v in response.headers.items()
            if k.lower() not in ("content-length", "transfer-encoding", "connection")
        }
        return response.status_code, out_headers, response.content


async def _build_official_model_items(request: Request) -> list[dict]:
    """Fetch official Kiro model items from upstream."""
    status_code, _, body = await _fetch_forward_body(request)
    if status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"获取官方 Kiro models 失败: upstream status={status_code}",
        )
    try:
        data = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"官方 Kiro models 响应不是 JSON: {exc}") from exc

    if isinstance(data, dict) and isinstance(data.get("models"), list):
        return [item for item in data["models"] if isinstance(item, dict)]
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return [item for item in data["data"] if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


async def _build_hybrid_models_response(request: Request) -> Response:
    """Build merged official + custom model list for hybrid mode."""
    official_models = await _build_official_model_items(request)
    custom_models = await _build_backend_model_items(prefix_custom=True)
    official_ids = {item.get("modelId") or item.get("id") for item in official_models}
    merged = list(official_models)
    for item in custom_models:
        if item.get("modelId") in official_ids:
            logger.warning(f"跳过与官方模型重名的自定义模型: {item.get('modelId')}")
            continue
        merged.append(item)
    return _build_models_response(merged)


async def _handle_forward_mode(request: Request) -> StreamingResponse:
    """
    纯转发模式: Kiro IDE 的请求直连 Kiro 真实 API 真实 IP.
    不改 headers、不改 body、不转换格式。只把 host 从 127.0.0.1 改到 AWS 真实 host.
    请求和响应的完整 raw bytes 都保存到 debug_logs/.
    """
    raw_body = await request.body()
    ts = int(time.time() * 1000) % 100000
    conv_id = f"fwd_{ts}"

    target_url, fwd_headers, host_header, ip = _prepare_forward_upstream(request, raw_body)

    # 保存请求
    try:
        req_log = {
            "method": request.method,
            "path": request.url.path,
            "query": request.url.query,
            "forward_host": host_header,
            "forward_ip": ip,
            "headers": {k: v for k, v in request.headers.items() if k.lower() != "authorization"},
            "body_len": len(raw_body),
            "body_preview": raw_body.decode("utf-8", errors="replace")[:500],
        }
        _save_log(conv_id, "forward_req", req_log)
    except Exception as e:
        logger.warning(f"保存 forward request 失败: {e}")

    client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0),
        verify=False if ip else True,
        follow_redirects=False,
        trust_env=False,
    )

    upstream_resp = await client.send(
        client.build_request(
            method=request.method,
            url=target_url,
            headers=fwd_headers,
            content=raw_body,
        ),
        stream=True,
    )
    logger.info(f"[FWD] Kiro 真实 API 响应: status={upstream_resp.status_code}")

    # 透传响应 headers
    out_headers = {}
    for k, v in upstream_resp.headers.items():
        if k.lower() in ("content-length", "transfer-encoding", "connection"):
            continue
        out_headers[k] = v

    out_chunks = []

    async def body_iter():
        try:
            async for chunk in upstream_resp.aiter_bytes():
                out_chunks.append(chunk)
                yield chunk
        finally:
            await _save_raw_response_bytes(conv_id, "forward_resp", out_chunks)
            logger.info(f"[FWD] 响应保存: {len(out_chunks)} chunks, {sum(len(c) for c in out_chunks)} bytes")
            try:
                await upstream_resp.aclose()
            except Exception:
                pass
            try:
                await client.aclose()
            except Exception:
                pass

    return StreamingResponse(
        body_iter(),
        status_code=upstream_resp.status_code,
        headers=out_headers,
        media_type=upstream_resp.headers.get("content-type"),
    )


@router.api_route("/mcp", methods=["GET", "POST"])
async def mcp_proxy(request: Request):
    """Kiro MCP endpoint.

    MODE=forward: 透传官方 MCP。
    MODE=hybrid : 透传官方 MCP，保证官方模型能力完整。
    MODE=openai : 直接返回空 MCP tools 列表，避免 Kiro IDE 加载官方 MCP 工具。
    """
    if MODE in ("forward", "hybrid"):
        return await _handle_forward_mode(request)

    request_id = "tools_list"
    method = ""
    try:
        body = await request.json()
        if isinstance(body, dict):
            request_id = body.get("id", request_id)
            method = body.get("method", "")
    except Exception:
        body = None

    _save_log("mcp", "empty_mcp_response", {"method": method, "id": request_id, "body": body})
    return Response(
        content=json.dumps(
            {
                "error": None,
                "id": request_id,
                "jsonrpc": "2.0",
                "result": {"tools": []},
            },
            ensure_ascii=False,
        ),
        media_type="application/json",
        headers={
            "cache-control": "no-store, no-cache, must-revalidate",
            "pragma": "no-cache",
            "expires": "0",
        },
    )


# ============ OpenAI 转换模式 ============

async def _handle_openai_mode(request: Request, request_data: KiroRequest) -> StreamingResponse:
    """OpenAI 转换模式: Kiro → OpenAI → 后端 API → Kiro"""

    # 保存原始 HTTP body
    try:
        raw_body = await request.body()
        cs = request_data.conversationState
        conv_id = cs.conversationId
        _save_log(conv_id, "kiro_raw", {"body": raw_body.decode("utf-8", errors="replace")})
    except Exception as e:
        logger.warning(f"保存 raw body 失败: {e}")

    cs = request_data.conversationState
    model_id = cs.currentMessage.userInputMessage.modelId
    conv_id = cs.conversationId

    logger.info(f"收到 Kiro 请求: model={model_id}, conv_id={conv_id}")
    _save_log(conv_id, "kiro_in", request_data.model_dump())

    try:
        openai_payload = convert_kiro_to_openai(request_data)
        logger.debug(f"转换后的 OpenAI 请求模型: {openai_payload.get('model')}")
        _save_log(conv_id, "openai_out", openai_payload)
    except ValueError as e:
        logger.warning(f"请求转换失败: {e}")
        raise HTTPException(status_code=400, detail=f"请求转换失败: {e}")
    except Exception as e:
        logger.error(f"请求转换异常: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"内部转换错误: {e}")

    try:
        backend_response = await send_to_backend(openai_payload, stream=True)

        _dbg_lines = []
        _dbg_path = LOG_DIR / f"{conv_id}_backend_sse_{int(time.time()*1000)%100000}.jsonl"
        _orig_aiter = backend_response.aiter_lines

        async def _dbg_aiter():
            async for line in _orig_aiter():
                _dbg_lines.append(line)
                yield line
        backend_response.aiter_lines = _dbg_aiter

        _orig_aclose = backend_response.aclose

        async def _dbg_aclose():
            try:
                with open(_dbg_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(_dbg_lines))
            except Exception as e:
                logger.warning(f"保存后端 SSE 失败: {e}")
            await _orig_aclose()
        backend_response.aclose = _dbg_aclose

    except httpx.HTTPStatusError as e:
        logger.error(f"后端 API 错误: {e}")
        raise HTTPException(status_code=502, detail=f"后端 API 错误: {e}")
    except httpx.TimeoutException as e:
        logger.error(f"后端 API 超时: {e}")
        raise HTTPException(status_code=504, detail=f"后端 API 超时: {e}")
    except Exception as e:
        logger.error(f"后端 API 请求失败: {traceback.format_exc()}")
        raise HTTPException(status_code=502, detail=f"后端 API 请求失败: {e}")

    async def stream_kiro_response():
        out_chunks = []
        try:
            async for chunk in convert_openai_stream_to_kiro(
                backend_response,
                model_name=model_id,
                max_context_tokens=_parse_context_length_from_model_id(model_id) or 200000,
            ):
                out_chunks.append(chunk)
                yield chunk
        except GeneratorExit:
            logger.debug("客户端断开连接")
        except Exception as e:
            logger.error(f"流式转换出错: {traceback.format_exc()}")
            error_bytes = json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8") + b"\n"
            out_chunks.append(error_bytes)
            yield error_bytes
        finally:
            await _save_raw_response_bytes(conv_id, "kiro_out", out_chunks)
            logger.info(f"已记录响应: {len(out_chunks)} 个 chunk, 共 {sum(len(c) for c in out_chunks)} 字节")
            await backend_response.aclose()

    return StreamingResponse(
        stream_kiro_response(),
        media_type="application/json",
        headers={"x-amzn-requestid": conv_id},
    )


# ============ 主端点 ============

@router.post("/generateAssistantResponse")
async def generate_assistant_response(request: Request):
    """
    Kiro API 兼容端点 —— generateAssistantResponse。

    根据 MODE 环境变量选择:
      MODE=forward → 纯转发到 Kiro 真实 API，不解析 body
      MODE=hybrid  → custom/* 模型走自定义后端，其它模型走官方 Kiro
      MODE=openai  → 解析 Kiro 请求并转换到自定义后端
    """
    if MODE == "forward":
        return await _handle_forward_mode(request)

    if MODE == "hybrid":
        try:
            request_json = await request.json()
            request_data = KiroRequest.model_validate(request_json)
        except Exception as e:
            logger.warning(f"Kiro 请求解析失败: {e}")
            raise HTTPException(status_code=400, detail=f"Kiro 请求解析失败: {e}")
        model_id = request_data.conversationState.currentMessage.userInputMessage.modelId
        if model_id.startswith(CUSTOM_MODEL_PREFIX):
            logger.info(f"[HYBRID] custom model -> OpenAI backend: {model_id}")
            return await _handle_openai_mode(request, request_data)
        logger.info(f"[HYBRID] official model -> Kiro forward: {model_id}")
        return await _handle_forward_mode(request)

    try:
        request_data = KiroRequest.model_validate(await request.json())
    except Exception as e:
        logger.warning(f"Kiro 请求解析失败: {e}")
        raise HTTPException(status_code=400, detail=f"Kiro 请求解析失败: {e}")

    return await _handle_openai_mode(request, request_data)


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def catch_all(request: Request, path: str):
    """Log and handle unknown Kiro endpoints.

    MODE=forward 时所有请求纯转发官方。
    MODE=openai 时 runtime 走 OpenAI 转换，management 已知接口走本地兜底。
    """
    raw_body = await request.body()
    request_path = request.url.path
    request_host = _get_request_host(request)
    target_name = _resolve_forward_target_name(request)
    _save_log(
        "unknown_requests",
        "request",
        {
            "method": request.method,
            "path": request_path,
            "query": request.url.query,
            "host": request_host,
            "target_name": target_name,
            "x_amz_target": request.headers.get("x-amz-target", ""),
            "headers": {k: v for k, v in request.headers.items() if k.lower() != "authorization"},
            "body_len": len(raw_body),
            "body_preview": raw_body.decode("utf-8", errors="replace")[:500],
        },
    )

    amz_target = request.headers.get("x-amz-target", "")
    if MODE == "forward":
        return await _handle_forward_mode(request)

    if "ListAvailableModels" in amz_target:
        try:
            if MODE == "hybrid":
                return await _build_hybrid_models_response(request)
            return await _build_backend_models_response()
        except Exception as e:
            logger.error(f"x-amz-target 获取 models 失败: {e}")
            raise HTTPException(status_code=502, detail=f"获取 models 失败: {e}")
    if "GetUsageLimits" in amz_target:
        if MODE in ("forward", "hybrid"):
            return await _handle_forward_mode(request)
        return await _build_usage_limits_response(request)
    if "ListAvailableProfiles" in amz_target or "GetProfile" in amz_target:
        if MODE in ("forward", "hybrid"):
            return await _handle_forward_mode(request)
        return await _build_profile_response(request)

    if "model" in request_path.lower():
        try:
            if MODE == "hybrid":
                return await _build_hybrid_models_response(request)
            return await _build_backend_models_response()
        except Exception as e:
            logger.error(f"catch-all 获取 models 失败: {e}")
            raise HTTPException(status_code=502, detail=f"获取 models 失败: {e}")

    if "usage" in request_path.lower():
        if MODE in ("forward", "hybrid"):
            return await _handle_forward_mode(request)
        return await _build_usage_limits_response(request)

    if "profile" in request_path.lower():
        if MODE in ("forward", "hybrid"):
            return await _handle_forward_mode(request)
        return await _build_profile_response(request)

    if request_path in ("", "/") and target_name == "management":
        return Response(
            content=json.dumps({}, ensure_ascii=False),
            media_type="application/json",
            headers={"cache-control": "no-store"},
        )

    if target_name == "management":
        return await _handle_forward_mode(request)

    raise HTTPException(status_code=404, detail=f"Unknown endpoint: {request_path}")
