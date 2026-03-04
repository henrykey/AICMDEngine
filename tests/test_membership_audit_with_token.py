#!/usr/bin/env python3
"""
测试membership_mcp的audit事件提交 - 在arguments中显式传递auth_token

⚠️  注意：这是一个测试脚本，用于验证显式传递auth_token的行为
   生产环境不建议这样做，应该让MCP Router自动传递token

参考文档：
- /Users/kehongwei/workspace/AICMDEngine/docs/MCP_CONFIGURATION_GUIDE.md
"""

import asyncio
import websockets
import json

JWT_TOKEN = open("/tmp/token.txt").read().strip()
MCP_ROUTER_URL = "ws://localhost:8000/mcp/v1"


async def test_membership_audit_with_explicit_token():
    """
    测试在arguments中显式传递auth_token

    注意：这可能会导致"got multiple values for keyword argument"错误，
    因为protocol_handler.py会自动从context传递auth_token
    """

    print("=" * 80)
    print("Membership Audit Event测试 - 显式传递auth_token")
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
                        "name": "audit-test",
                        "version": "1.0"
                    }
                }
            }
            await websocket.send(json.dumps(init_request))
            response = json.loads(await websocket.recv())
            print("✓ 初始化完成")
            print()

            # 调用membership.submit_audit_event工具
            # 在arguments中显式传递auth_token和tenant_id
            audit_request = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "membership.submit_audit_event",
                    "arguments": {
                        "category": "ACCESS",
                        "action": "test_action",
                        "tenant_id": 1,
                        "auth_token": JWT_TOKEN,  # 显式传递auth_token
                        "actor": {
                            "type": "system",
                            "id": "test_system"
                        },
                        "resource_type": "test",
                        "resource_id": "test_123"
                    }
                }
            }

            print("→ 调用membership.submit_audit_event工具...")
            print("  在arguments中显式传递auth_token和tenant_id")
            print()

            await websocket.send(json.dumps(audit_request))

            print("← 等待响应...")
            print()

            # 接收响应
            response = json.loads(await websocket.recv())

            # 处理结果
            if 'result' in response:
                result = response['result']
                content = result.get('content', [])

                print("-" * 80)
                print("✓ Audit event提交成功!")
                print("-" * 80)
                print()

                for item in content:
                    if item.get('type') == 'text':
                        text = item.get('text', '')
                        print(f"返回: {text}")
                        print()

                if "401" not in text:
                    print("=" * 80)
                    print("✓ 显式传递auth_token方案验证成功!")
                    print("✓ 没有出现401 Unauthorized错误!")
                    print("=" * 80)

            elif 'error' in response:
                error = response['error']
                print("-" * 80)
                print("✗ Audit event提交失败!")
                print("-" * 80)
                print(f"错误代码: {error.get('code')}")
                print(f"错误信息: {error.get('message')}")
                print(f"错误详情: {error.get('data', {})}")
                print()

                # 检查是否是重复参数错误
                if 'multiple values for keyword argument' in str(error.get('message', '')):
                    print("⚠️  检测到重复参数错误!")
                    print("   这说明同时从context和arguments传递了相同的参数")
                    print()

    except Exception as e:
        print(f"✗ 错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_membership_audit_with_explicit_token())
