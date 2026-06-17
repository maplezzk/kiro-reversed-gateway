# -*- coding: utf-8 -*-
"""
OpenAI SSE 响应 → Kiro AWS Event Stream 转换器。

将 OpenAI Chat Completions 的流式响应（SSE）转换为 Kiro API 的 AWS Event Stream 格式。
"""

import json
import os
import struct
import uuid
import zlib
from typing import Any, AsyncGenerator, Dict, Optional

import httpx
from loguru import logger


# ===================================================================
# AWS Event Stream 二进制编码
# ===================================================================

# Header value types (AWS Event Stream spec)
_HVT_BOOL_TRUE = 0
_HVT_BOOL_FALSE = 1
_HVT_INT8 = 2
_HVT_INT16 = 3
_HVT_INT32 = 4
_HVT_INT64 = 6
_HVT_STRING = 7
_HVT_TIMESTAMP = 8


def _crc32(data: bytes) -> int:
    """AWS Event Stream 使用 CRC32 (zlib)"""
    return zlib.crc32(data) & 0xFFFFFFFF


def _encode_header(name: str, value_type: int, value: bytes) -> bytes:
    """编码一个 header entry"""
    name_bytes = name.encode("utf-8")
    return (
        struct.pack("!B", len(name_bytes))
        + name_bytes
        + struct.pack("!B", value_type)
        + value
    )


def _encode_string_header(name: str, value: str) -> bytes:
    val_bytes = value.encode("utf-8")
    return _encode_header(name, _HVT_STRING, struct.pack("!H", len(val_bytes)) + val_bytes)


def _encode_bool_header(name: str, value: bool) -> bytes:
    return _encode_header(name, _HVT_BOOL_TRUE if value else _HVT_BOOL_FALSE, b"")


def _encode_int_header(name: str, value: int) -> bytes:
    return _encode_header(name, _HVT_INT32, struct.pack("!i", value))


def _make_aws_event_frame(event_type: str, payload: dict) -> bytes:
    """
    构造一个 AWS Event Stream 二进制帧。

    Args:
        event_type: 事件类型，如 "assistantResponseEvent", "contextUsageEvent", "meteringEvent"
        payload: JSON payload

    Returns:
        完整的二进制帧
    """
    payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    # 构造 headers
    headers = (
        _encode_string_header(":event-type", event_type)
        + _encode_string_header(":content-type", "application/json")
        + _encode_string_header(":message-type", "event")
    )

    # prelude = 8 字节长度 + 4 字节 prelude CRC
    total_length = 12 + len(headers) + len(payload_bytes) + 4  # 4 = message CRC at end
    prelude = struct.pack("!II", total_length, len(headers))
    prelude_crc = _crc32(prelude)
    prelude_with_crc = prelude + struct.pack("!I", prelude_crc)

    # message CRC = CRC32 of prelude_with_crc + headers + payload
    message_crc = _crc32(prelude_with_crc + headers + payload_bytes)
    message_crc_bytes = struct.pack("!I", message_crc)

    return prelude_with_crc + headers + payload_bytes + message_crc_bytes


# ===================================================================
# Kiro Event Stream 构建工具
# ===================================================================

def make_content_event(text: str, model_id: str = "claude-haiku-4.5") -> bytes:
    """创建 Kiro 文本内容事件 (event-type=assistantResponseEvent)

    Kiro 真实 API 真实 content 事件都带 modelId 字段 (从 minimax 抓的响应看到)。
    Kiro IDE 解析时需要 modelId 字段才能正常处理。
    """
    return _make_aws_event_frame("assistantResponseEvent", {"content": text, "modelId": model_id})


def make_tool_start_event(tool_name: str, tool_call_id: str, arguments: Any = None) -> bytes:
    """
    创建 Kiro 工具调用开始事件。

    Kiro 真实格式 (event-type=toolUseEvent): {"name":"func","toolUseId":"call_1"} (无 input 字段)
    input 通过后续 input 事件传入。
    """
    return _make_aws_event_frame(
        "toolUseEvent",
        {"name": tool_name, "toolUseId": tool_call_id},
    )


def make_tool_input_event(input_text: str, tool_name: str = "", tool_call_id: str = "") -> bytes:
    """创建 Kiro 工具参数续传事件 (event-type=toolUseEvent)

    Args:
        input_text: 完整的 JSON 字符串 (例如 '{"path": "/tmp"}')
        tool_name, tool_call_id: 必填，Kiro IDE 期望每个 input 事件都带这些字段

    Kiro 真实 API 真实响应 input 字段是 string 格式 (累积 JSON 字符串)。
    """
    payload = {"input": input_text}
    if tool_name:
        payload["name"] = tool_name
    if tool_call_id:
        payload["toolUseId"] = tool_call_id
    return _make_aws_event_frame(
        "toolUseEvent", payload
    )


def make_tool_stop_event(tool_name: str = "", tool_call_id: str = "") -> bytes:
    """创建 Kiro 工具调用结束事件 (event-type=toolUseEvent, {"name","stop":true,"toolUseId"})"""
    payload = {"stop": True}
    if tool_name:
        payload["name"] = tool_name
    if tool_call_id:
        payload["toolUseId"] = tool_call_id
    return _make_aws_event_frame(
        "toolUseEvent", payload
    )


def make_usage_event(usage: float = 0, unit: str = "credit", unit_plural: str = "credits") -> bytes:
    """创建 Kiro 用量事件 (meteringEvent)"""
    return _make_aws_event_frame(
        "meteringEvent", {"unit": unit, "unitPlural": unit_plural, "usage": usage}
    )


def make_context_usage_event(percentage: float) -> bytes:
    """创建 Kiro 上下文使用率事件 (contextUsageEvent)"""
    return _make_aws_event_frame(
        "contextUsageEvent", {"contextUsagePercentage": percentage}
    )


def normalize_tool_arguments_for_kiro(tool_name: str, arguments_str: str) -> str:
    """Normalize tool arguments to match Kiro IDE tool expectations.

    Kiro IDE's list_directory tool accepts home-relative paths like ~/Desktop.
    Official Kiro API emits ~/Desktop for desktop listing requests, while some
    OpenAI-compatible models emit /Users/<name>/Desktop. Passing the absolute
    path can trigger Kiro IDE's workspace search error, so normalize only this
    known-compatible case before emitting toolUseEvent input.

    Args:
        tool_name: Name of the tool being called.
        arguments_str: JSON string containing tool arguments.

    Returns:
        Normalized JSON string when applicable; original string otherwise.
    """
    if tool_name != "list_directory" or not arguments_str.strip():
        return arguments_str

    try:
        arguments = json.loads(arguments_str)
    except json.JSONDecodeError:
        return arguments_str

    path = arguments.get("path")
    if not isinstance(path, str):
        return arguments_str

    home_dir = os.path.expanduser("~")
    if path == home_dir:
        arguments["path"] = "~"
    elif path.startswith(home_dir + os.sep):
        arguments["path"] = "~" + path[len(home_dir):]
    else:
        return arguments_str

    return json.dumps(arguments, ensure_ascii=False)


# ===================================================================
# OpenAI SSE 解析与转换
# ===================================================================

async def convert_openai_stream_to_kiro(
    response: httpx.Response,
    model_name: str,
    max_context_tokens: int = 200000,
) -> AsyncGenerator[bytes, None]:
    """
    将 OpenAI SSE 流式响应转换为 Kiro Event Stream。

    Args:
        response: httpx 流式响应
        model_name: 模型名称（用于日志）
        max_context_tokens: 模型最大上下文 token 数，用于计算 contextUsagePercentage

    Yields:
        编码后的 Kiro Event Stream 字节块
    """
    tool_call_buffer: Dict[str, Dict[str, Any]] = {}  # index → {id, name, arguments_str}
    content_buffer = ""
    last_event_type = None  # 'content', 'tool_calls' - 用于检测切换
    stopped = False  # 收到 finish_reason=tool_calls 后丢弃后续 content
    # 收集 usage 信息用于在流结束时发送 context_usage + metering 事件
    final_prompt_tokens = 0
    final_completion_tokens = 0
    final_total_tokens = 0

    try:
        async for line in response.aiter_lines():
            if not line or not line.startswith("data: "):
                continue

            data_str = line[6:]  # 去掉 "data: " 前缀

            if data_str == "[DONE]":
                # 流结束：flush 缓冲的工具调用 (仅当 finish_reason 时还没 flush 过)
                if not stopped:
                    for idx in sorted(tool_call_buffer.keys()):
                        tc = tool_call_buffer[idx]
                        yield make_tool_start_event(
                            tool_name=tc["name"],
                            tool_call_id=tc["id"],
                        )
                        if tc["arguments_str"].strip():
                            input_text = normalize_tool_arguments_for_kiro(tc["name"], tc["arguments_str"])
                            yield make_tool_input_event(
                                input_text,
                                tool_name=tc["name"],
                                tool_call_id=tc["id"],
                            )
                        yield make_tool_stop_event(tool_name=tc["name"], tool_call_id=tc["id"])
                    tool_call_buffer.clear()
                    # === 发送 trailer 事件 (Kiro 真实 API 在工具调用后必发) ===
                    yield make_content_event("", model_id=model_name)
                    if final_total_tokens > 0:
                        context_pct = final_prompt_tokens / max_context_tokens * 100.0
                        yield make_context_usage_event(context_pct)
                    if final_completion_tokens > 0:
                        yield make_usage_event(usage=1)

                # 流自然结束
                break

            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                logger.warning(f"无法解析 SSE 数据: {data_str[:100]}")
                continue

            choices = data.get("choices", [])
            if not choices:
                continue

            choice = choices[0]
            delta = choice.get("delta", {})
            finish_reason = choice.get("finish_reason", "")

            # --- 收集 usage 信息 (用于流结束时的 context_usage + metering 事件) ---
            usage = data.get("usage", {})
            if usage:
                final_prompt_tokens = usage.get("prompt_tokens", 0) or final_prompt_tokens
                final_completion_tokens = usage.get("completion_tokens", 0) or final_completion_tokens
                final_total_tokens = usage.get("total_tokens", 0) or final_total_tokens

            # --- 处理文本内容 ---
            # 只用真正的 delta.content, 不要 fallback 到 reasoning_content (那是内部推理, 不应暴露给 Kiro IDE)
            text_content = delta.get("content", "") or ""

            if text_content and not stopped:
                if last_event_type == "tool_calls":
                    # 从 tool_calls 切回 content：先 flush 之前缓存的 tool calls
                    for idx in sorted(tool_call_buffer.keys()):
                        tc = tool_call_buffer[idx]
                        yield make_tool_start_event(tool_name=tc["name"], tool_call_id=tc["id"])
                        if tc["arguments_str"].strip():
                            input_text = normalize_tool_arguments_for_kiro(tc["name"], tc["arguments_str"])
                            yield make_tool_input_event(
                                input_text,
                                tool_name=tc["name"],
                                tool_call_id=tc["id"],
                            )
                        yield make_tool_stop_event(tool_name=tc["name"], tool_call_id=tc["id"])
                    tool_call_buffer.clear()

                content_buffer += text_content
                yield make_content_event(text_content, model_id=model_name)
                last_event_type = "content"

            # --- 处理工具调用 ---
            tool_calls = delta.get("tool_calls") or []
            for tc in tool_calls:
                if last_event_type == "content" and content_buffer:
                    # 从 content 切到 tool_calls，content 已经处理过了
                    pass
                last_event_type = "tool_calls"
                # 立即停止后续 content 输出 (避免 step 等模型继续输出 "Got it let's see...")
                stopped = True
                logger.debug(f"检测到 tool_calls，停止后续 content 输出")

                index = tc.get("index", 0)
                tc_id = tc.get("id", "")

                if index not in tool_call_buffer:
                    # 用 Kiro 风格的 toolUseId (tooluse_xxx)，Kiro IDE 期望这种格式
                    if not tc_id or not tc_id.startswith("tooluse_"):
                        tc_id = f"tooluse_{uuid.uuid4().hex[:16]}"
                    tool_call_buffer[index] = {
                        "id": tc_id,
                        "name": "",
                        "arguments_str": "",
                    }

                entry = tool_call_buffer[index]
                # entry["id"] 已在 buffer 初始化时设置为 tooluse_ 格式，不要覆盖

                func = tc.get("function", {})
                if func.get("name"):
                    entry["name"] = func["name"]

                if func.get("arguments"):
                    entry["arguments_str"] += func["arguments"]

            # --- 处理 finish_reason ---
            if finish_reason:
                logger.debug(f"OpenAI stream finished: finish_reason={finish_reason}")
                if finish_reason == "tool_calls":
                    # 模型决定调用工具: 立即 flush tool_call_buffer，停止 stream
                    for idx in sorted(tool_call_buffer.keys()):
                        tc = tool_call_buffer[idx]
                        yield make_tool_start_event(tool_name=tc["name"], tool_call_id=tc["id"])
                        if tc["arguments_str"].strip():
                            input_text = normalize_tool_arguments_for_kiro(tc["name"], tc["arguments_str"])
                            yield make_tool_input_event(
                                input_text,
                                tool_name=tc["name"],
                                tool_call_id=tc["id"],
                            )
                        yield make_tool_stop_event(tool_name=tc["name"], tool_call_id=tc["id"])
                    tool_call_buffer.clear()
                    # 设置 stopped 标志，丢弃后续 content (step 等模型会继续输出)
                    stopped = True
                    content_buffer = ""
                    # === 发送 trailer 事件 (Kiro 真实 API 在 finish_reason 后也发) ===
                    yield make_content_event("", model_id=model_name)
                    if final_total_tokens > 0:
                        context_pct = final_prompt_tokens / max_context_tokens * 100.0
                        yield make_context_usage_event(context_pct)
                    if final_completion_tokens > 0:
                        yield make_usage_event(usage=1)
                    # 不 break: 让流自然结束 (continue reading [DONE])

    except GeneratorExit:
        logger.debug("流被中断 (GeneratorExit)")
        raise
    except Exception as e:
        logger.error(f"OpenAI 流转换出错: {type(e).__name__}: {e}")
        raise


# ===================================================================
# 非流式响应转换
# ===================================================================

async def convert_openai_non_stream_to_kiro(
    response: httpx.Response,
    model_name: str,
) -> bytes:
    """
    将 OpenAI 非流式响应转换为 Kiro Event Stream。

    Args:
        response: httpx 响应
        model_name: 模型名称

    Returns:
        编码后的 Kiro Event Stream 完整数据
    """
    data = response.json()
    choices = data.get("choices", [])
    result = bytearray()

    if not choices:
        return bytes(result)

    choice = choices[0]
    message = choice.get("message", {})

    # 文本内容
    content = message.get("content", "") or ""
    if content:
        result.extend(make_content_event(content, model_id=model_name))

    # 工具调用
    tool_calls = message.get("tool_calls") or []
    for tc in tool_calls:
        func = tc.get("function", {})
        func_name = func.get("name", "")
        func_args_str = func.get("arguments", "{}")

        try:
            func_args = json.loads(func_args_str)
        except json.JSONDecodeError:
            func_args = {"raw_input": func_args_str}

        tc_id = tc.get("id", "")
        if not tc_id or not tc_id.startswith("tooluse_"):
            tc_id = f"tooluse_{uuid.uuid4().hex[:16]}"
        result.extend(make_tool_start_event(
            tool_name=func_name,
            tool_call_id=tc_id,
            arguments=func_args,
        ))
        # 非流式：参数一次性发，input 事件
        normalized_args_str = normalize_tool_arguments_for_kiro(func_name, func_args_str)
        result.extend(make_tool_input_event(
            normalized_args_str,
            tool_name=func_name,
            tool_call_id=tc_id,
        ))
        result.extend(make_tool_stop_event(tool_name=func_name, tool_call_id=tc_id))

    # 用量
    usage = data.get("usage", {})
    total = usage.get("total_tokens", 0)
    if total > 0:
        result.extend(make_usage_event(1))

    # 停止标记
    # 流自然结束，不需要额外停止事件

    return bytes(result)
