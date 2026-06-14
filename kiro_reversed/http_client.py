# -*- coding: utf-8 -*-
"""
HTTP 客户端 —— 向后端 API 发送请求并返回响应。
"""

import httpx
from loguru import logger

from kiro_reversed.config import (
    BACKEND_API_URL,
    BACKEND_API_KEY,
    REQUEST_TIMEOUT,
)


def _build_backend_chat_url() -> str:
    """Build the backend chat completions URL from configured API base/url."""
    if not BACKEND_API_URL:
        raise ValueError("BACKEND_API_URL is not configured")

    normalized_url = BACKEND_API_URL.rstrip("/")
    if normalized_url.endswith("/chat/completions"):
        return normalized_url
    return f"{normalized_url}/chat/completions"


def _build_backend_models_url() -> str:
    """Build the backend models URL from configured API base/url."""
    if not BACKEND_API_URL:
        raise ValueError("BACKEND_API_URL is not configured")

    normalized_url = BACKEND_API_URL.rstrip("/")
    if normalized_url.endswith("/chat/completions"):
        return normalized_url[: -len("/chat/completions")] + "/models"
    return f"{normalized_url}/models"


async def fetch_backend_models() -> list[dict]:
    """Fetch OpenAI-compatible models from backend /models endpoint.

    Returns:
        Raw model objects from OpenAI-compatible response data.
    """
    models_url = _build_backend_models_url()
    headers = {}
    if BACKEND_API_KEY:
        headers["Authorization"] = f"Bearer {BACKEND_API_KEY}"

    timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(models_url, headers=headers)
        response.raise_for_status()
        data = response.json()

    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return [item for item in data["data"] if isinstance(item, dict)]
    if isinstance(data, dict) and isinstance(data.get("models"), list):
        return [item for item in data["models"] if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


async def send_to_backend(
    openai_payload: dict,
    stream: bool = True,
) -> httpx.Response:
    """
    发送 OpenAI 格式请求到后端 API。

    Args:
        openai_payload: OpenAI Chat Completions 请求体
        stream: 是否流式请求

    Returns:
        httpx 响应对象（需要调用方关闭）

    Raises:
        httpx.HTTPError: 请求失败时
    """
    if not BACKEND_API_URL:
        raise ValueError("BACKEND_API_URL is not configured")

    headers = {
        "Content-Type": "application/json",
    }
    if BACKEND_API_KEY:
        headers["Authorization"] = f"Bearer {BACKEND_API_KEY}"

    timeout = httpx.Timeout(
        connect=30.0,
        read=REQUEST_TIMEOUT,
        write=30.0,
        pool=30.0,
    )

    chat_url = _build_backend_chat_url()
    logger.debug(f"发送请求到后端: {chat_url}")
    logger.debug(f"模型: {openai_payload.get('model')}")
    logger.debug(f"消息数: {len(openai_payload.get('messages', []))}")
    logger.debug(f"流式: {stream}")

    # 使用流式请求以支持 SSE 解析
    client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)
    response = await client.send(
        client.build_request(
            "POST",
            chat_url,
            headers=headers,
            json=openai_payload,
        ),
        stream=stream,
    )

    if response.status_code != 200:
        error_body = ""
        try:
            error_body = await response.aread()
            error_body = error_body.decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        logger.error(f"后端返回错误 {response.status_code}: {error_body}")
        await client.aclose()
        raise httpx.HTTPStatusError(
            f"Backend returned {response.status_code}: {error_body}",
            request=response.request,
            response=response,
        )

    return response
