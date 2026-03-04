#!/usr/bin/env python3
"""
测试Word文档提取 - 验证JWT token传递
"""

import asyncio
import websockets
import json
from pathlib import Path
import random

# 配置
MCP_ROUTER_URL = "ws://localhost:8000/mcp/v1"
JWT_TOKEN = open("/tmp/token.txt").read().strip()


async def test_word_extraction():
    """测试Word文档文本提取"""

    print("=" * 80)
    print("Word文档提取测试 - 验证JWT Token传递")
    print("=" * 80)
    print()

    # 连接MCP Router
    ws_url = f"{MCP_ROUTER_URL}?token={JWT_TOKEN}"

    try:
        async with websockets.connect(ws_url, max_size=2**24) as websocket:
            print("✓ 已连接到MCP Router (JWT认证成功)")
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
                        "name": "test-client",
                        "version": "1.0.0"
                    }
                }
            }
            await websocket.send(json.dumps(init_request))
            response = json.loads(await websocket.recv())
            print(f"✓ 初始化完成")
            print()

            # 获取工具列表
            tools_request = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list"
            }
            await websocket.send(json.dumps(tools_request))
            response = json.loads(await websocket.recv())
            tools = response.get('result', {}).get('tools', [])

            # 查找word.get_document_text工具
            word_tool = None
            for tool in tools:
                if tool.get('name') == 'word.get_document_text':
                    word_tool = tool
                    break

            if not word_tool:
                print("✗ 未找到word.get_document_text工具")
                return

            # 显示工具参数
            print("word.get_document_text 工具参数:")
            print("-" * 80)
            schema = word_tool.get('inputSchema', {})
            properties = schema.get('properties', {})
            required = schema.get('required', [])

            print(f"必需参数: {required}")
            for prop_name, prop_info in properties.items():
                prop_type = prop_info.get('type', 'unknown')
                desc = prop_info.get('description', '')
                print(f"  - {prop_name} ({prop_type}): {desc[:100]}")
            print("-" * 80)
            print()

            # 列出可用的Word文档
            list_request = {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "word.list_available_documents",
                    "arguments": {
                        "directory": "/Users/kehongwei/workspace/AICMDEngine/docs"
                    }
                }
            }

            print("→ 列出可用文档...")
            await websocket.send(json.dumps(list_request))
            response = json.loads(await websocket.recv())

            if 'result' in response:
                result = response['result']
                content = result.get('content', [])

                for item in content:
                    if item.get('type') == 'text':
                        text = item.get('text', '')
                        print(f"\n可用文档:\n{text}")
            print()

            # 如果找到了.docx文件，测试提取文本
            docx_files = list(Path("/Users/kehongwei/workspace/AICMDEngine/docs").glob("*.docx"))

            if docx_files:
                test_file = docx_files[0]
                print(f"→ 测试文件: {test_file.name}")
                print("-" * 80)

                extract_request = {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {
                        "name": "word.get_document_text",
                        "arguments": {
                            "file_path": str(test_file)
                        }
                    }
                }

                await websocket.send(json.dumps(extract_request))
                response = json.loads(await websocket.recv())

                if 'result' in response:
                    result = response['result']
                    content = result.get('content', [])

                    print("✓ 提取成功!")
                    print()

                    for item in content:
                        if item.get('type') == 'text':
                            text = item.get('text', '')
                            print(f"文本长度: {len(text)} 字符")
                            print(f"行数: {len(text.split(chr(10)))} 行")
                            print()

                            # 显示前500字符
                            print("文本预览 (前500字符):")
                            print("=" * 80)
                            print(text[:500])
                            if len(text) > 500:
                                print("...")
                            print("=" * 80)
                            print()

                            # 检查中文
                            chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
                            if chinese_chars > 0:
                                print(f"✓ 包含 {chinese_chars} 个中文字符")
                            print()

                            print("✓ JWT Token传递验证成功!")
                            print("✓ 工具调用成功，无401错误!")
                            break
            else:
                print("未找到.docx文件进行测试")

    except Exception as e:
        print(f"✗ 错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_word_extraction())
