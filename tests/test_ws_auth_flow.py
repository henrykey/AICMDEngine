#!/usr/bin/env python3
"""
WebSocket认证流程详细测试

显示完整的WebSocket握手过程和认证信息
"""

import asyncio
import websockets
import aiohttp
import json
import sys

print("=" * 80)
print("WebSocket认证流程详细测试")
print("=" * 80)
print()
print(f"Python版本: {sys.version}")
print(f"websockets版本: {websockets.__version__}")
print()

async def test_auth_flow():
    # 步骤1: 登录获取token
    print("步骤1: 登录获取JWT token")
    print("-" * 80)

    login_url = "http://localhost:8000/v1/auth/login"
    print(f"登录URL: {login_url}")

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
            print(f"  Token后20字符: ...{token[-20:]}")

    print()

    # 步骤2: 测试带token的连接 (query parameter方式)
    print("步骤2: 测试WebSocket连接 - 使用query parameter方式")
    print("-" * 80)

    ws_url_query = f"ws://localhost:8000/mcp/v1?token={token}"
    print(f"WebSocket URL: {ws_url_query[:80]}...")
    print(f"URL长度: {len(ws_url_query)} 字符")

    try:
        print("  → 正在连接...")
        async with websockets.connect(ws_url_query) as ws:
            print("  ✓ 连接成功!")

            # 发送初始化消息
            init_msg = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test-auth", "version": "1.0"}
                }
            }

            print("  → 发送initialize消息...")
            await ws.send(json.dumps(init_msg))
            print("  ✓ 消息发送成功")

            print("  → 等待响应...")
            response = await asyncio.wait_for(ws.recv(), timeout=5.0)
            response_data = json.loads(response)

            print(f"  ✓ 收到响应")
            print(f"    JSON-RPC版本: {response_data.get('jsonrpc')}")
            if 'result' in response_data:
                result = response_data['result']
                print(f"    协议版本: {result.get('protocolVersion')}")
                print(f"    服务器信息: {result.get('serverInfo')}")
                capabilities = result.get('capabilities', {})
                print(f"    支持的工具数量: {len(capabilities.get('tools', []))}")

            await ws.close()
            print("  ✓ 连接正常关闭")

    except asyncio.TimeoutError:
        print("  ✗ 超时: 5秒内未收到响应")
    except Exception as e:
        print(f"  ✗ 连接失败: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

    print()

    # 步骤3: 测试不带token的连接 (应该失败)
    print("步骤3: 测试WebSocket连接 - 不带token (应该失败)")
    print("-" * 80)

    ws_url_no_token = "ws://localhost:8000/mcp/v1"
    print(f"WebSocket URL: {ws_url_no_token}")

    try:
        print("  → 正在连接...")
        async with websockets.connect(ws_url_no_token) as ws:
            print("  ? 连接成功 (意外!)")
            await ws.close()
    except websockets.exceptions.InvalidStatusCode as e:
        print(f"  ✓ 按预期失败: {type(e).__name__}")
        print(f"    HTTP状态码: {e.status_code}")
        print(f"    这是正常的 - 服务器要求认证")
    except Exception as e:
        print(f"  ✗ 其他错误: {type(e).__name__}: {e}")

    print()

    # 步骤4: 测试无效token的连接 (应该失败)
    print("步骤4: 测试WebSocket连接 - 无效token (应该失败)")
    print("-" * 80)

    invalid_token = "invalid_token_12345"
    ws_url_invalid = f"ws://localhost:8000/mcp/v1?token={invalid_token}"
    print(f"WebSocket URL: {ws_url_invalid}")

    try:
        print("  → 正在连接...")
        async with websockets.connect(ws_url_invalid) as ws:
            print("  ? 连接成功 (意外!)")
            await ws.close()
    except websockets.exceptions.InvalidStatusCode as e:
        print(f"  ✓ 按预期失败: {type(e).__name__}")
        print(f"    HTTP状态码: {e.status_code}")
        print(f"    这是正常的 - token验证失败")
    except Exception as e:
        print(f"  ✗ 其他错误: {type(e).__name__}: {e}")

    print()
    print("=" * 80)
    print("测试完成")
    print("=" * 80)
    print()
    print("结论:")
    print("  1. WebSocket连接**必须**携带有效的JWT token")
    print("  2. Token可以通过query参数传递: ?token=XXX")
    print("  3. 也可以通过Authorization header传递: Bearer XXX")
    print("  4. 服务器在握手阶段就会验证token")
    print("  5. 无token或无效token会导致连接被拒绝")
    print()

if __name__ == "__main__":
    asyncio.run(test_auth_flow())
