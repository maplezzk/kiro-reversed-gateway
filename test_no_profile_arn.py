#!/usr/bin/env python3
"""
独立脚本：测试不传 profileArn 时 Kiro API 的行为。
"""
import asyncio
import json
import sys
import os
from pathlib import Path

KIRO_GATEWAY_PATH = Path.home() / "CliProject" / "kiro-gateway"
sys.path.insert(0, str(KIRO_GATEWAY_PATH))


async def main():
    from kiro.auth import KiroAuthManager
    from kiro.http_client import KiroHttpClient

    creds_file = Path.home() / ".aws" / "sso" / "cache" / "kiro-auth-token.json"
    auth = KiroAuthManager(creds_file=str(creds_file))

    print("刷新 token...")
    token = await auth.get_access_token()

    # 试 1: 不带 profileArn
    body = {
        "conversationState": {
            "conversationId": "test-1",
            "chatTriggerType": "MANUAL",
            "currentMessage": {
                "userInputMessage": {
                    "content": "say hi in one word",
                    "modelId": "claude-haiku-4.5",
                    "origin": "AI_EDITOR",
                }
            },
        }
    }

    url = f"{auth.api_host}/generateAssistantResponse"
    print(f"URL: {url}")
    print(f"Test 1: 不带 profileArn")

    client = KiroHttpClient(auth, shared_client=None)
    try:
        resp = await client.request_with_retry("POST", url, body, stream=True)
        print(f"Status: {resp.status_code}")
        print(f"Content-Type: {resp.headers.get('content-type', '?')}")

        raw = b""
        async for chunk in resp.aiter_bytes():
            raw += chunk
            if len(raw) > 10000:
                break

        with open("/tmp/kiro_test1.bin", "wb") as f:
            f.write(raw)
        print(f"Saved {len(raw)} bytes")

        # hex dump 前 600 字节
        print(f"\n=== hex (first 600) ===")
        for i in range(0, min(len(raw), 600), 16):
            hx = " ".join(f"{b:02x}" for b in raw[i:i+16])
            ac = "".join(chr(b) if 32 <= b < 127 else "." for b in raw[i:i+16])
            print(f"{i:04x}  {hx:<48s} |{ac}|")

        # text
        try:
            print(f"\n=== text ===\n{raw.decode('utf-8', errors='replace')[:500]}")
        except:
            pass
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
