#!/usr/bin/env python3
import asyncio
import websockets
import aiohttp
import json

# 直接复制配置
MCP_ROUTER_URL = "ws://localhost:8000/mcp/v1"
MCP_ROUTER_HTTP_URL = "http://localhost:8000"
TOKEN_FILE = "/tmp/token.txt"

async def test_step_by_step():
    print("=" * 80)
    print("逐步调试WebSocket连接")
    print("=" * 80)
    print()

    # 步骤1：获取token
    print("步骤1：获取token")
    login_url = f"{MCP_ROUTER_HTTP_URL}/v1/auth/login"
    print(f"  URL: {login_url}")

    async with aiohttp.ClientSession() as session:
        async with session.post(
            login_url,
            json={"username": "admin", "password": "admin123"}
        ) as resp:
            print(f"  状态码: {resp.status}")
            if resp.status == 200:
                data = await resp.json()
                token = data['access_token']
                print(f"  ✓ Token获取成功")
                print(f"  Token长度: {len(token)}")
                print(f"  Token前50字符: {token[:50]}")
            else:
                print(f"  ✗ 登录失败")
                text = await resp.text()
                print(f"  响应: {text[:200]}")
                return

    print()

    # 步骤2：构造WebSocket URL
    print("步骤2：构造WebSocket URL")
    ws_url = f"{MCP_ROUTER_URL}?token={token}"
    print(f"  URL长度: {len(ws_url)}")
    print(f"  URL前100字符: {ws_url[:100]}")
    print()

    # 步骤3：尝试连接
    print("步骤3：连接WebSocket")
    print(f"  使用websockets版本: {websockets.__version__}")

    try:
        print("  → 正在连接...")
        ws = await websockets.connect(ws_url)
        print("  ✓ 连接对象创建成功")

        # 发送初始化
        init_msg = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "debug", "version": "1.0"}
            }
        }
        print(f"  → 发送初始化消息...")
        await ws.send(json.dumps(init_msg))
        print("  ✓ 消息发送成功")

        print(f"  → 等待响应...")
        response = await ws.recv()
        print(f"  ✓ 收到响应: {response[:100]}")

        await ws.close()
        print("  ✓ 连接关闭成功")

        print()
        print("=" * 80)
        print("✓ 全部步骤成功！")
        print("=" * 80)

    except Exception as e:
        print(f"  ✗ 失败: {type(e).__name__}: {e}")
        print()
        import traceback
        traceback.print_exc()

        print()
        print("=" * 80)
        print("✗ 连接失败")
        print("=" * 80)

if __name__ == "__main__":
    asyncio.run(test_step_by_step())
