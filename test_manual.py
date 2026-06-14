import asyncio
import json
import httpx
import sys

"""
手动测试脚本 —— 模拟 Kiro 请求发送到代理。

用法:
    # 先在另一个终端启动代理:
    python main.py --no-tls --port 8443

    # 然后运行测试:
    python test_manual.py
"""

PROXY_URL = "http://localhost:8443/generateAssistantResponse"


async def test_basic():
    """测试基本对话"""
    kiro_request = {
        "conversationState": {
            "chatTriggerType": "MANUAL",
            "conversationId": "test-conv-001",
            "currentMessage": {
                "userInputMessage": {
                    "content": "你好，请用中文介绍一下你自己",
                    "modelId": "claude-sonnet-4.5",
                    "origin": "AI_EDITOR",
                }
            },
        },
        "profileArn": "",
    }

    print("=" * 60)
    print("测试1: 基本对话")
    print(f"发送请求到: {PROXY_URL}")
    print(f"模型: claude-sonnet-4.5")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("POST", PROXY_URL, json=kiro_request) as response:
            print(f"状态码: {response.status_code}")
            print("响应:")
            async for chunk in response.aiter_bytes():
                try:
                    text = chunk.decode("utf-8", errors="replace").strip()
                    if text:
                        print(f"  {text}")
                except Exception:
                    pass


async def test_with_history():
    """测试带历史记录的对话"""
    kiro_request = {
        "conversationState": {
            "chatTriggerType": "MANUAL",
            "conversationId": "test-conv-002",
            "currentMessage": {
                "userInputMessage": {
                    "content": "那把 Python 改成 JavaScript 呢？",
                    "modelId": "claude-sonnet-4.5",
                    "origin": "AI_EDITOR",
                }
            },
            "history": [
                {
                    "userInputMessage": {
                        "content": "用 Python 写一个快速排序",
                    }
                },
                {
                    "assistantResponseMessage": {
                        "content": '```python\ndef quicksort(arr):\n    if len(arr) <= 1:\n        return arr\n    pivot = arr[len(arr) // 2]\n    left = [x for x in arr if x < pivot]\n    middle = [x for x in arr if x == pivot]\n    right = [x for x in arr if x > pivot]\n    return quicksort(left) + middle + quicksort(right)\n```',
                    }
                },
            ],
        },
        "profileArn": "",
    }

    print("=" * 60)
    print("测试2: 带历史记录的对话")
    print(f"发送请求到: {PROXY_URL}")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("POST", PROXY_URL, json=kiro_request) as response:
            print(f"状态码: {response.status_code}")
            print("响应:")
            async for chunk in response.aiter_bytes():
                try:
                    text = chunk.decode("utf-8", errors="replace").strip()
                    if text:
                        print(f"  {text}")
                except Exception:
                    pass


async def main():
    print("\n🔧 kiro-reversed-gateway 手动测试\n")

    await test_basic()
    print()
    await test_with_history()

    print("\n✅ 测试完成")


if __name__ == "__main__":
    asyncio.run(main())
