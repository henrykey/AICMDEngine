#!/usr/bin/env python3
import asyncio
import websockets
import aiohttp
import json

async def main():
    # 1. 获取新token
    print("1. 获取新token...")
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "http://localhost:8000/v1/auth/login",
            json={"username": "admin", "password": "admin123"}
        ) as resp:
            data = await resp.json()
            token = data['access_token']
            print(f"   Token: {token[:50]}...")

    # 2. 立即测试连接
    print("\n2. 测试WebSocket连接...")
    ws_url = f"ws://localhost:8000/mcp/v1?token={token}"
    print(f"   URL: {ws_url[:80]}...")

    try:
        async with websockets.connect(ws_url) as ws:
            print("   ✓ 连接成功！")

            # 发送初始化
            init_msg = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"}
                }
            }
            await ws.send(json.dumps(init_msg))
            response = await ws.recv()
            print(f"   ✓ 收到响应: {response[:100]}...")

    except Exception as e:
        print(f"   ✗ 失败: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
