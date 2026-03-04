#!/usr/bin/env python3
"""
PDF OCR测试 - 尝试不同的参数格式
"""

import asyncio
import websockets
import json
from pathlib import Path
import random

# 配置
MCP_ROUTER_URL = "ws://localhost:8000/mcp/v1"
PDF_PATH = Path.home() / "Documents/GB/GB∕T 150.1~4-2024 压力容器 扫描版.pdf"
JWT_TOKEN = open("/tmp/token.txt").read().strip()


async def test_pdf_ocr():
    """测试PDF OCR提取"""

    print("=" * 80)
    print("PDF OCR 测试")
    print("=" * 80)
    print(f"PDF: {PDF_PATH}")
    print(f"大小: {PDF_PATH.stat().st_size / 1024 / 1024:.2f} MB")
    print()

    if not PDF_PATH.exists():
        print(f"✗ PDF文件不存在: {PDF_PATH}")
        return

    # 连接MCP Router
    ws_url = f"{MCP_ROUTER_URL}?token={JWT_TOKEN}"

    try:
        async with websockets.connect(ws_url, max_size=2**24) as websocket:
            print("✓ 已连接到MCP Router")
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
                        "name": "pdf-ocr-test",
                        "version": "1.0.0"
                    }
                }
            }
            await websocket.send(json.dumps(init_request))
            response = json.loads(await websocket.recv())
            print(f"✓ 初始化完成")
            print()

            # 获取工具列表，查看paddleocr.ocr的参数
            tools_request = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list"
            }
            await websocket.send(json.dumps(tools_request))
            response = json.loads(await websocket.recv())
            tools = response.get('result', {}).get('tools', [])

            # 查找paddleocr.ocr工具
            paddleocr_tool = None
            for tool in tools:
                if tool.get('name') == 'paddleocr.ocr':
                    paddleocr_tool = tool
                    break

            if paddleocr_tool:
                print("paddleocr.ocr 工具参数:")
                print("-" * 80)
                schema = paddleocr_tool.get('inputSchema', {})
                properties = schema.get('properties', {})
                required = schema.get('required', [])

                print(f"Required parameters: {required}")
                for prop_name, prop_info in properties.items():
                    prop_type = prop_info.get('type', 'unknown')
                    desc = prop_info.get('description', '')
                    print(f"  - {prop_name} ({prop_type}): {desc}")
                print("-" * 80)
                print()

            # 尝试调用 - 使用不同的参数组合
            test_cases = [
                {
                    "name": "paddleocr.ocr",
                    "arguments": {
                        "image": str(PDF_PATH)
                    }
                },
                {
                    "name": "paddleocr.ocr",
                    "arguments": {
                        "img_path": str(PDF_PATH)
                    }
                },
                {
                    "name": "paddleocr.ocr",
                    "arguments": {
                        "file_path": str(PDF_PATH)
                    }
                }
            ]

            for i, test_case in enumerate(test_cases, 1):
                print(f"尝试 {i}: {test_case['arguments']}")
                print("-" * 40)

                tool_call_request = {
                    "jsonrpc": "2.0",
                    "id": 2 + i,
                    "method": "tools/call",
                    "params": test_case
                }

                try:
                    await websocket.send(json.dumps(tool_call_request))
                    response = json.loads(await websocket.recv())

                    if 'result' in response:
                        result = response['result']
                        content = result.get('content', [])

                        print("✓ 调用成功!")

                        # 提取文本
                        for item in content:
                            if item.get('type') == 'text':
                                text = item.get('text', '')
                                print(f"文本长度: {len(text)} 字符")
                                if len(text) > 0:
                                    print(f"预览: {text[:200]}")
                                    print()
                                    print("=" * 80)
                                    print("✓ PDF OCR测试成功!")
                                    return

                    elif 'error' in response:
                        error = response['error']
                        print(f"✗ 错误: {error.get('message')}")

                except Exception as e:
                    print(f"✗ 异常: {e}")

                print()

                # 如果成功了就退出
                if 'result' in response:
                    break

    except Exception as e:
        print(f"✗ 连接错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_pdf_ocr())
