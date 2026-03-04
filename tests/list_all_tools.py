#!/usr/bin/env python3
"""
列出MCP Router中所有可用的工具及其参数
"""

import asyncio
import websockets
import json

JWT_TOKEN = open("/tmp/token.txt").read().strip()
MCP_ROUTER_URL = "ws://localhost:8000/mcp/v1"


async def list_tools():
    """列出所有工具"""

    print("=" * 80)
    print("MCP Router 工具列表")
    print("=" * 80)
    print()

    ws_url = f"{MCP_ROUTER_URL}?token={JWT_TOKEN}"

    try:
        async with websockets.connect(ws_url) as websocket:
            print("✓ WebSocket连接成功")
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
                        "name": "list-tools",
                        "version": "1.0"
                    }
                }
            }
            await websocket.send(json.dumps(init_request))
            response = json.loads(await websocket.recv())
            print("✓ 初始化完成")
            print()

            # 获取工具列表
            tools_request = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list"
            }
            await websocket.send(json.dumps(tools_request))
            response = json.loads(await websocket.recv())

            if 'result' in response:
                tools = response['result'].get('tools', [])

                print(f"找到 {len(tools)} 个工具:")
                print("=" * 80)

                for i, tool in enumerate(tools, 1):
                    name = tool.get('name', '')
                    desc = tool.get('description', '')
                    schema = tool.get('inputSchema', {})
                    properties = schema.get('properties', {})
                    required = schema.get('required', [])

                    print(f"\n{i}. {name}")
                    print(f"   描述: {desc}")
                    print(f"   必需参数: {required}")

                    if properties:
                        print(f"   所有参数:")
                        for prop_name, prop_info in properties.items():
                            prop_type = prop_info.get('type', 'unknown')
                            prop_desc = prop_info.get('description', '')
                            print(f"     - {prop_name} ({prop_type}): {prop_desc}")

                print("\n" + "=" * 80)

                # 特别关注OCR/Word/PDF相关工具
                print("\n文档处理相关工具:")
                print("-" * 80)

                doc_tools = []
                for tool in tools:
                    name = tool.get('name', '').lower()
                    desc = tool.get('description', '').lower()
                    if ('ocr' in name or 'pdf' in name or 'word' in name or
                        'extract' in name or 'parse' in name or 'document' in desc):
                        doc_tools.append(tool)

                if doc_tools:
                    for tool in doc_tools:
                        name = tool.get('name')
                        desc = tool.get('description')
                        schema = tool.get('inputSchema', {})
                        properties = schema.get('properties', {})
                        required = schema.get('required', [])

                        print(f"\n工具: {name}")
                        print(f"描述: {desc}")
                        print(f"必需参数: {required}")
                        print(f"所有参数:")
                        for prop_name, prop_info in properties.items():
                            prop_type = prop_info.get('type', 'unknown')
                            prop_desc = prop_info.get('description', '')
                            print(f"  - {prop_name} ({prop_type}): {prop_desc}")
                else:
                    print("未找到文档处理工具")

                print("\n" + "=" * 80)

    except Exception as e:
        print(f"✗ 错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(list_tools())
