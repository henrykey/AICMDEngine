#!/usr/bin/env python3
"""
简单的WebSocket连接测试
只测试连接，不做其他工作
"""

import asyncio
import websockets
import aiohttp
import json


async def main():
    print("=" * 80)
    print("WebSocket连接测试")
    print("=" * 80)
    print()

    # 步骤1: 获取token
    print("步骤1: 获取JWT token")
    print("-" * 80)

    login_url = "http://localhost:8000/v1/auth/login"
    print(f"登录URL: {login_url}")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                login_url,
                json={"username": "admin", "password": "admin123"}
            ) as resp:
                if resp.status != 200:
                    print(f"✗ 登录失败: HTTP {resp.status}")
                    text = await resp.text()
                    print(f"响应: {text[:200]}")
                    return

                data = await resp.json()
                token = data['access_token']

                print(f"✓ 登录成功")
                print(f"  Token长度: {len(token)} 字符")
                print(f"  Token前50字符: {token[:50]}...")
    except Exception as e:
        print(f"✗ 登录异常: {type(e).__name__}: {e}")
        return

    print()

    # 步骤2: 连接WebSocket
    print("步骤2: 连接WebSocket")
    print("-" * 80)

    ws_url = f"ws://localhost:8000/mcp/v1?token={token}"
    print(f"WebSocket URL: {ws_url[:80]}...")
    print()

    try:
        print("→ 正在连接...")
        async with websockets.connect(ws_url) as ws:
            print("✓ 连接成功!")
            print()

            # 发送初始化消息
            init_msg = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test-simple", "version": "1.0"}
                }
            }

            print("→ 发送initialize消息...")
            await ws.send(json.dumps(init_msg))
            print("✓ 消息已发送")
            print()

            print("→ 等待响应...")
            response = await ws.recv()
            print(f"✓ 收到响应: {response[:100]}...")
            print()

            await ws.close()
            print("✓ 连接已关闭")

    except Exception as e:
        print(f"✗ 连接失败: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return

    print()
    print("=" * 80)
    print("✓ 测试成功!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
