#!/usr/bin/env python3
"""
诊断WebSocket连接问题
"""

import asyncio
import sys
import websockets
import websockets.exceptions
import traceback

print("=" * 80)
print("WebSocket连接诊断")
print("=" * 80)
print()
print(f"Python版本: {sys.version}")
print(f"websockets版本: {websockets.__version__}")
print()

# 获取token
print("1. 获取JWT token...")
try:
    import aiohttp
    import json

    async def get_token():
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "http://localhost:8000/v1/auth/login",
                json={"username": "admin", "password": "admin123"}
            ) as resp:
                data = await resp.json()
                return data['access_token']

    token = asyncio.run(get_token())
    print(f"✓ Token获取成功: {token[:50]}...")
    print()
except Exception as e:
    print(f"✗ 获取token失败: {e}")
    traceback.print_exc()
    sys.exit(1)

# 测试不同的连接方式
ws_url = f"ws://localhost:8000/mcp/v1?token={token}"

print("2. 测试WebSocket连接...")
print(f"URL: {ws_url}")
print()

async def test_connection():
    print("尝试方式1: 简单连接")
    try:
        async with websockets.connect(ws_url) as ws:
            print("✓ 连接成功！")
            await ws.close()
            return True
    except Exception as e:
        print(f"✗ 失败: {type(e).__name__}: {e}")
        print()

    print("尝试方式2: 带max_size")
    try:
        async with websockets.connect(ws_url, max_size=2**24) as ws:
            print("✓ 连接成功！")
            await ws.close()
            return True
    except Exception as e:
        print(f"✗ 失败: {type(e).__name__}: {e}")
        print()

    print("尝试方式3: 带ping参数")
    try:
        async with websockets.connect(
            ws_url,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=10
        ) as ws:
            print("✓ 连接成功！")
            await ws.close()
            return True
    except Exception as e:
        print(f"✗ 失败: {type(e).__name__}: {e}")
        print()

    print("尝试方式4: 不使用query参数，用header")
    try:
        headers = {"Authorization": f"Bearer {token}"}
        async with websockets.connect(
            "ws://localhost:8000/mcp/v1",
            extra_headers=headers
        ) as ws:
            print("✓ 连接成功！")
            await ws.close()
            return True
    except Exception as e:
        print(f"✗ 失败: {type(e).__name__}: {e}")
        traceback.print_exc()

    return False

result = asyncio.run(test_connection())

print()
print("=" * 80)
if result:
    print("✓ 至少有一种方式可以连接")
else:
    print("✗ 所有连接方式都失败了")
print("=" * 80)
