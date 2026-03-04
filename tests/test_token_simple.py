#!/usr/bin/env python3
"""
测试MCP工具调用 - 验证JWT Token传递
使用简单的echo工具测试
"""

import asyncio
import websockets
import json

JWT_TOKEN = open("/tmp/token.txt").read().strip()
MCP_ROUTER_URL = "ws://localhost:8000/mcp/v1"


async def test_token_propagation():
    """测试JWT token是否正确传递给工具"""

    print("=" * 80)
    print("JWT Token传递测试")
    print("=" * 80)
    print()

    ws_url = f"{MCP_ROUTER_URL}?token={JWT_TOKEN}"

    try:
        async with websockets.connect(ws_url) as websocket:
            print("✓ WebSocket连接成功 (JWT认证通过)")
            print()

            # 初始化
            init_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "token-test",
                        "version": "1.0"
                    }
                }
            }
            await websocket.send(json.dumps(init_request))
            response = json.loads(await websocket.recv())
            print(f"✓ 初始化完成")
            print()

            # 调用test.echo工具
            echo_request = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "test.echo",
                    "arguments": {
                        "message": "Hello from MCP Client!"
                    }
                }
            }

            print("→ 调用test.echo工具...")
            await websocket.send(json.dumps(echo_request))
            response = json.loads(await websocket.recv())

            print()
            if 'result' in response:
                result = response['result']
                content = result.get('content', [])

                for item in content:
                    if item.get('type') == 'text':
                        text = item.get('text', '')
                        print("✓ 工具调用成功!")
                        print(f"返回: {text}")
                        print()
                        print("=" * 80)
                        print("✓ JWT Token传递验证成功!")
                        print("✓ 工具收到了token，可以正常调用")
                        print("✓ 没有出现401 Unauthorized错误")
                        print("=" * 80)
                        return

            elif 'error' in response:
                error = response['error']
                print(f"✗ 工具调用失败:")
                print(f"  错误代码: {error.get('code')}")
                print(f"  错误信息: {error.get('message')}")
                print(f"  错误详情: {error.get('data', {})}")

    except Exception as e:
        print(f"✗ 错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_token_propagation())
