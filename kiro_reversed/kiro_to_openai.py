# -*- coding: utf-8 -*-
"""
Kiro API 请求 → OpenAI API 请求 转换器。

将 Kiro 专有的 conversationState 格式转换为 OpenAI Chat Completions 格式。
"""

import base64
import json
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from kiro_reversed.config import map_model
from kiro_reversed.models import (
    KiroRequest,
    KiroTool,
    KiroToolResult,
    KiroToolUse,
    KiroUserInputMessage,
    KiroAssistantResponseMessage,
)


def _normalize_image_base64(raw_data: Any) -> str:
    """Normalize image payload to a clean base64 string.

    Kiro may send image bytes in ``images[].source.bytes`` while older code
    expected ``images[].data``. Some callers may also include a data URL prefix.
    This helper returns only the base64 payload and skips invalid/empty data.
    """
    if not isinstance(raw_data, str):
        return ""

    data = raw_data.strip()
    if not data:
        return ""

    if data.startswith("data:") and ";base64," in data:
        data = data.split(";base64,", 1)[1].strip()

    if not data:
        return ""

    try:
        base64.b64decode(data, validate=True)
    except (ValueError, base64.binascii.Error):
        logger.warning("跳过非法图片 base64 数据")
        return ""

    return data


def _extract_image_payload(image: Any) -> Tuple[str, str]:
    """Extract media type and base64 bytes from a Kiro image object/dict."""
    raw = image.model_dump() if hasattr(image, "model_dump") else image
    if not isinstance(raw, dict):
        return "image/jpeg", ""

    media_type = raw.get("mediaType") or raw.get("media_type") or "image/jpeg"
    data = raw.get("data") or ""

    source = raw.get("source") or {}
    if not data and isinstance(source, dict):
        data = source.get("bytes") or source.get("data") or ""

    normalized_data = _normalize_image_base64(data)
    return media_type, normalized_data


def _build_openai_user_content(text: str, images: Optional[List[Any]]) -> Any:
    """Build OpenAI user content, including valid Kiro images when present."""
    valid_images: List[Tuple[str, str]] = []
    for image in images or []:
        media_type, data = _extract_image_payload(image)
        if data:
            valid_images.append((media_type, data))

    if not valid_images:
        return text

    content_parts: List[Dict[str, Any]] = []
    if text:
        content_parts.append({"type": "text", "text": text})

    for media_type, data in valid_images:
        content_parts.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:{media_type};base64,{data}",
                "detail": "auto",
            },
        })

    return content_parts


# ===================================================================
# 工具提取
# ===================================================================

def _extract_tools_from_message(msg: KiroUserInputMessage) -> Optional[List[Dict[str, Any]]]:
    """从 Kiro 用户消息中提取工具定义，转换为 OpenAI tools 格式"""
    ctx = msg.userInputMessageContext
    if not ctx or not ctx.tools:
        return None

    tools = []
    for t in ctx.tools:
        raw = t.model_dump() if hasattr(t, 'model_dump') else {}
        
        # Kiro 实际格式: {"toolSpecification": {"name":..., "description":..., "inputSchema": {"json": {...}}}}
        spec = raw.get("toolSpecification", {})
        name = spec.get("name", "") or raw.get("name", "") or ""
        desc = spec.get("description", "") or raw.get("description", "") or ""
        input_schema_raw = spec.get("inputSchema", {}) or raw.get("inputSchema", {})
        
        # Kiro schema 格式: {"json": {"type":"object","properties":{...}}}
        # OpenAI 格式: {"type":"object","properties":{...}}
        parameters = input_schema_raw.get("json") or input_schema_raw
        if not parameters or not parameters.get("type"):
            parameters = {"type": "object", "properties": {}, "required": []}
        
        tools.append({
            "type": "function",
            "function": {
                "name": name,
                "description": desc,
                "parameters": parameters
            }
        })
    return tools if tools else None


# ===================================================================
# 消息转换
# ===================================================================

def _convert_history_entry_to_messages(
    entry: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    将 Kiro history 中的一条记录转换为 OpenAI message(s)。

    Kiro history 格式：
      {"userInputMessage": {"content": "...", "userInputMessageContext": {...}}}
      {"assistantResponseMessage": {"content": "...", "toolUses": [...]}}

    可能一个 entry 产生多条 OpenAI message（userInputMessage 含 toolResults 时拆分为 assistant+tool）。
    """
    messages: List[Dict[str, Any]] = []

    if "userInputMessage" in entry:
        uim = entry["userInputMessage"]
        content = uim.get("content", "") or ""
        images = uim.get("images") or []
        ctx = uim.get("userInputMessageContext") or {}

        # 工具结果 → 分别生成 tool 消息
        tool_results: List[Dict] = ctx.get("toolResults") or []
        for tr in tool_results:
            tc_id = tr.get("toolUseId", "")
            tc_content = tr.get("content", "") or ""
            # content 可能是数组 [{text: "..."}]，转成字符串
            if isinstance(tc_content, list):
                parts = []
                for item in tc_content:
                    if isinstance(item, dict):
                        parts.append(item.get("text", "") or json.dumps(item, ensure_ascii=False))
                    else:
                        parts.append(str(item))
                tc_content = "\n".join(parts)
            elif not isinstance(tc_content, str):
                tc_content = json.dumps(tc_content, ensure_ascii=False)
            messages.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": tc_content,
            })

        # 用户内容（如果纯 tool_result 没有文本也加一条）
        if content.strip() or images:
            messages.append({"role": "user", "content": _build_openai_user_content(content, images)})
        elif not tool_results:
            messages.append({"role": "user", "content": content})

    elif "assistantResponseMessage" in entry:
        arm = entry["assistantResponseMessage"]
        content = arm.get("content", "") or ""
        tool_uses: List[Dict] = arm.get("toolUses") or []

        msg: Dict[str, Any] = {"role": "assistant", "content": content}

        if tool_uses:
            tool_calls = []
            for i, tu in enumerate(tool_uses):
                args = tu.get("input", {}) or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"raw_input": args}
                tool_calls.append({
                    "id": tu.get("toolUseId", f"call_{i}"),
                    "type": "function",
                    "function": {
                        "name": tu.get("name", ""),
                        "arguments": json.dumps(args, ensure_ascii=False),
                    }
                })
            if tool_calls:
                msg["tool_calls"] = tool_calls

        messages.append(msg)

    return messages


def convert_kiro_to_openai(request: KiroRequest) -> Dict[str, Any]:
    """
    主转换函数：KiroRequest → OpenAI Chat Completions 请求体。

    Args:
        request: Kiro generateAssistantResponse 请求

    Returns:
        OpenAI Chat Completions 请求字典

    Raises:
        ValueError: 无法转换时抛出
    """
    cs = request.conversationState
    current = cs.currentMessage.userInputMessage

    # --- 模型映射 ---
    model = map_model(current.modelId)
    logger.info(f"Model mapping: {current.modelId} → {model}")

    # --- 提取工具 ---
    tools = _extract_tools_from_message(current)

    # --- 构建 messages 数组 ---
    messages: List[Dict[str, Any]] = []

    # 如果有 system prompt（Kiro 把它嵌在第一个 user message 里），这里直接透传
    # 不做 system prompt 拆分，保持原样

    # 处理 history
    if cs.history:
        for entry in cs.history:
            converted = _convert_history_entry_to_messages(entry)
            messages.extend(converted)

    # 处理 currentMessage
    # 先处理 current 中的 toolResults
    ctx = current.userInputMessageContext
    if ctx and ctx.toolResults:
        for tr in ctx.toolResults:
            tc_content = tr.content or ""
            if isinstance(tc_content, list):
                parts = []
                for item in tc_content:
                    if isinstance(item, dict):
                        parts.append(item.get("text", "") or json.dumps(item, ensure_ascii=False))
                    else:
                        parts.append(str(item))
                tc_content = "\n".join(parts)
            messages.append({
                "role": "tool",
                "tool_call_id": tr.toolUseId,
                "content": tc_content,
            })

    # 当前用户消息
    user_content = current.content or ""
    if user_content.strip() or current.images:
        messages.append({
            "role": "user",
            "content": _build_openai_user_content(user_content, current.images),
        })
    elif not (ctx and ctx.toolResults):
        messages.append({"role": "user", "content": user_content})

    # --- 压缩连续同角色消息 ---
    messages = _merge_consecutive_same_role(messages)

    # --- 确保以 user 开头 ---
    if messages and messages[0]["role"] != "user":
        messages.insert(0, {"role": "user", "content": "Hello"})

    # --- 确保 user/assistant 交替 ---
    messages = _ensure_alternating(messages)

    if not messages:
        raise ValueError("转换后没有有效消息")

    # --- 构建 OpenAI 请求 ---
    openai_request: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,  # 默认流式，Kiro 也是流式返回的
    }

    if tools:
        openai_request["tools"] = tools

    # 如果请求非流式，可以通过环境变量或特殊标记控制
    # 暂时默认流式

    return openai_request


def _merge_consecutive_same_role(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """合并连续相同角色的消息"""
    if not messages:
        return messages

    merged = []
    for msg in messages:
        if merged and merged[-1]["role"] == msg["role"]:
            # 同角色合并内容
            prev_content = merged[-1].get("content", "")
            curr_content = msg.get("content", "")
            if isinstance(prev_content, str) and isinstance(curr_content, str):
                merged[-1]["content"] = f"{prev_content}\n{curr_content}"
            elif isinstance(prev_content, list) and isinstance(curr_content, str):
                merged[-1]["content"].append({"type": "text", "text": curr_content})
            else:
                merged.append(msg)
        else:
            merged.append(msg)

    return merged


def _ensure_alternating(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """确保 user 和 assistant 交替出现"""
    if not messages:
        return messages

    result = [messages[0]]
    for msg in messages[1:]:
        last_role = result[-1]["role"]
        if msg["role"] == last_role:
            if msg["role"] == "user":
                # 两个连续 user，插入假 assistant
                result.append({"role": "assistant", "content": "I understand."})
            elif msg["role"] == "assistant":
                # 两个连续 assistant，插入假 user
                result.append({"role": "user", "content": "Continue."})
            elif msg["role"] == "tool":
                # tool 消息：前面应该有 assistant，如果没有就插入
                if last_role != "assistant":
                    result.append({"role": "assistant", "content": "Okay."})
        result.append(msg)

    return result
