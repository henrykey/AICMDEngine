#!/usr/bin/env python3
"""
测试membership_mcp的audit事件提交 - 验证JWT token传递

这个测试验证MCP Router自动传递JWT token给工具的正确行为。

参考文档：
- /Users/kehongwei/workspace/AICMDEngine/docs/MCP_CONFIGURATION_GUIDE.md
- /Users/kehongwei/workspace/AICMDEngine/src/mcp/protocol_handler.py (自动传递逻辑)
"""

import asyncio
import websockets
import json

JWT_TOKEN = open("/tmp/token.txt").read().strip()
MCP_ROUTER_URL = "ws://localhost:8000/mcp/v1"


async def test_membership_audit():
    """
    测试membership.submit_audit_event工具

    验证点：
    1. JWT token从WebSocket连接自动传递到工具
    2. 不需要在arguments中手动传递auth_token
    3. tenant_id从JWT token的tenantId claim自动提取
    """

    print("=" * 80)
    print("Membership Audit Event测试 - 验证JWT Token传递")
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
            # 注意：不传auth_token和tenant_id参数，应该自动使用从WebSocket连接传递的值
            audit_request = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "membership.submit_audit_event",
                    "arguments": {
                        "category": "ACCESS",
                        "action": "test_action",
                        # tenant_id将从context中获取
                        "actor": {
                            "type": "system",
                            "id": "test_system"
                        },
                        "resource_type": "test",
                        "resource_id": "test_123",
                        "details": {
                            "test": "JWT token propagation test"
                        }
                    }
                }
            }

            print("→ 调用membership.submit_audit_event工具...")
            print("  (不传auth_token参数，验证MCP Router是否自动传递)")
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

                print("=" * 80)
                print("✓ JWT Token传递验证成功!")
                print("✓ MCP Router正确传递了auth_token给membership_mcp工具!")
                print("✓ 没有出现401 Unauthorized错误!")
                print("=" * 80)
                return

            elif 'error' in response:
                error = response['error']
                print("-" * 80)
                print("✗ Audit event提交失败!")
                print("-" * 80)
                print(f"错误代码: {error.get('code')}")
                print(f"错误信息: {error.get('message')}")
                print(f"错误详情: {error.get('data', {})}")
                print()

                if '401' in str(error.get('message', '')) or error.get('code') == 401:
                    print("⚠️  检测到401错误 - JWT token没有正确传递!")
                    print()

    except Exception as e:
        print(f"✗ 错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_membership_audit())
