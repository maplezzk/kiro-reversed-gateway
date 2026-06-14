#!/usr/bin/env python3
"""
独立脚本：用 kiro-gateway 发送请求到真实 Kiro API，保存原始响应。

前置条件:
  1. ~/.aws/sso/cache/kiro-auth-token.json 存在
  2. ~/.aws/sso/cache/{clientIdHash}.json 存在
  3. kiro-gateway 项目的依赖已安装 (cd kiro-gateway && pip install -r requirements.txt)

用法:
  cd /path/to/kiro-gateway
  /path/to/kiro-reversed-gateway/.venv/bin/python /path/to/kiro-reversed-gateway/capture_real_kiro.py
"""

import asyncio
import json
import sys
import os
from pathlib import Path

KIRO_GATEWAY_PATH = Path.home() / "CliProject" / "kiro-gateway"
sys.path.insert(0, str(KIRO_GATEWAY_PATH))


async def main():
    # 读取 profileArn（优先从环境变量取，其次从 ~/.aws/sso 文件中查找）
    profile_arn = os.environ.get("PROFILE_ARN", "")
    if not profile_arn:
        # 尝试从 kiro-gateway 的 credentials.json 找
        creds_json = KIRO_GATEWAY_PATH / "credentials.json"
        if creds_json.exists():
            with open(creds_json) as f:
                data = json.load(f)
            if isinstance(data, list) and data:
                profile_arn = data[0].get("profile_arn", "")

    print(f"profile_arn: {profile_arn or '(未提供)'}")

    from kiro.auth import KiroAuthManager
    from kiro.http_client import KiroHttpClient

    creds_file = Path.home() / ".aws" / "sso" / "cache" / "kiro-auth-token.json"
    auth = KiroAuthManager(creds_file=str(creds_file))

    # 刷新 token
    print("刷新 token...")
    token = await auth.get_access_token()
    print(f"Token: {token[:30]}...")

    # 构造一个简单的请求
    body = {
        "conversationState": {
            "conversationId": "capture-test-001",
            "chatTriggerType": "MANUAL",
            "currentMessage": {
                "userInputMessage": {
                    "content": "say hi in one word",
                    "modelId": "claude-haiku-4.5",
                    "origin": "AI_EDITOR",
                }
            },
        },
        "profileArn": profile_arn,
    }

    if not profile_arn:
        print("⚠️  没有 profileArn，可能返回 400。可以：")
        print("    export PROFILE_ARN=<your-profile-arn>")
        print("    或让 Kiro IDE 正常发一条消息，从代理日志中获取 profileArn")

    url = f"{auth.api_host}/generateAssistantResponse"
    print(f"URL: {url}")

    client = KiroHttpClient(auth, shared_client=None)
    try:
        resp = await client.request_with_retry("POST", url, body, stream=True)
        print(f"Status: {resp.status_code}")
        print(f"Content-Type: {resp.headers.get('content-type', '?')}")
        print(f"Headers:")
        for k, v in resp.headers.items():
            if not k.lower().startswith("x-amz"):
                continue
            print(f"  {k}: {v}")

        # 读前 10000 字节
        raw = b""
        async for chunk in resp.aiter_bytes():
            raw += chunk
            if len(raw) > 10000:
                break

        # 保存
        with open("/tmp/kiro_real_body.bin", "wb") as f:
            f.write(raw)

        print(f"\nSaved {len(raw)} bytes to /tmp/kiro_real_body.bin")

        # 打印 hex dump (前 1000 字节)
        print(f"\n=== hex dump (first 1000 bytes) ===")
        for i in range(0, min(len(raw), 1000), 16):
            hx = " ".join(f"{b:02x}" for b in raw[i:i+16])
            ac = "".join(chr(b) if 32 <= b < 127 else "." for b in raw[i:i+16])
            print(f"{i:04x}  {hx:<48s} |{ac}|")

        # 如果是文本格式，尝试解析
        if resp.headers.get("content-type", "").startswith("application/json"):
            try:
                text = raw.decode("utf-8")
                print(f"\n=== text content ===\n{text[:2000]}")
            except:
                pass
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
