#!/usr/bin/env python3
"""
完整的PDF OCR提取测试
测试扫描版PDF的文本提取功能
"""

import asyncio
import websockets
import json
import sys
import random
import base64
from pathlib import Path

# 配置
MCP_ROUTER_URL = "ws://localhost:8000/mcp/v1"
PDF_PATH = Path.home() / "Documents/GB/GB∕T 150.1~4-2024 压力容器 扫描版.pdf"

# JWT token
JWT_TOKEN = open("/tmp/token.txt").read().strip()


async def test_pdf_ocr():
    """完整测试PDF OCR提取"""

    print("=" * 80)
    print("PDF OCR 完整测试")
    print("=" * 80)
    print(f"PDF: {PDF_PATH}")
    print(f"MCP Router: {MCP_ROUTER_URL}")
    print()

    # 检查PDF文件
    if not PDF_PATH.exists():
        print(f"✗ PDF文件不存在: {PDF_PATH}")
        return

    # 读取PDF文件
    print(f"→ 读取PDF文件...")
    with open(PDF_PATH, 'rb') as f:
        pdf_data = f.read()
        pdf_base64 = base64.b64encode(pdf_data).decode('utf-8')
        pdf_size = len(pdf_data)

    print(f"  文件大小: {pdf_size} bytes ({pdf_size / 1024 / 1024:.2f} MB)")
    print(f"  Base64编码: {len(pdf_base64)} characters")
    print()

    # 连接MCP Router
    ws_url = f"{MCP_ROUTER_URL}?token={JWT_TOKEN}"

    try:
        async with websockets.connect(ws_url) as websocket:
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
            print(f"✓ 初始化完成: {response.get('result', {}).get('serverInfo', {}).get('name', 'Unknown')}")
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

            print(f"✓ 发现 {len(tools)} 个工具")
            print()

            # 显示所有工具
            print("所有工具列表:")
            print("-" * 80)
            for i, tool in enumerate(tools, 1):
                name = tool.get('name', '')
                desc = tool.get('description', '')[:80]
                properties = tool.get('inputSchema', {}).get('properties', {})
                has_file = 'file' in properties or 'filename' in properties or 'document' in properties
                flag = " [FILE]" if has_file else ""
                print(f"{i:3}. {name}{flag}")
                print(f"     {desc}")
            print("-" * 80)
            print()

            # 查找PDF处理工具
            pdf_tools = []
            for tool in tools:
                name = tool.get('name', '').lower()
                desc = tool.get('description', '').lower()
                properties = tool.get('inputSchema', {}).get('properties', {})

                # 查找接受file参数或与PDF相关的工具
                if ('file' in properties or 'filename' in properties or 'document' in properties or
                    'pdf' in name or 'ocr' in name or 'word' in name or 'extract' in name):
                    pdf_tools.append(tool)

            print(f"找到 {len(pdf_tools)} 个可能的PDF/OCR工具:")
            for tool in pdf_tools:
                print(f"  - {tool.get('name')}: {tool.get('description', '')[:80]}")
            print()

            if not pdf_tools:
                print("✗ 未找到PDF处理工具")
                return

            # 选择第一个工具
            tool = pdf_tools[0]
            tool_name = tool.get('name')

            print(f"→ 使用工具: {tool_name}")
            print("-" * 80)
            print()

            # 调用工具
            tool_call_request = {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": {
                        "file": {
                            "name": PDF_PATH.name,
                            "content": pdf_base64,
                            "type": "application/pdf"
                        },
                        "auth_token": JWT_TOKEN
                    }
                }
            }

            print("→ 发送PDF到MCP Router...")
            print(f"  工具: {tool_name}")
            print(f"  文件: {PDF_PATH.name}")
            print(f"  Token: {JWT_TOKEN[:50]}...")
            print()

            await websocket.send(json.dumps(tool_call_request))

            print("← 等待OCR处理...")
            print()

            # 接收响应
            response = json.loads(await websocket.recv())

            # 处理结果
            if 'result' in response:
                result = response['result']
                content = result.get('content', [])

                print("-" * 80)
                print("✓ OCR提取成功!")
                print("-" * 80)
                print()

                # 提取文本内容
                full_text = ""
                for item in content:
                    if item.get('type') == 'text':
                        text = item.get('text', '')
                        full_text += text + "\n"

                # 统计信息
                lines = full_text.split('\n')
                non_empty_lines = [l for l in lines if l.strip()]

                print(f"文本统计:")
                print(f"  总字符数: {len(full_text)}")
                print(f"  总行数: {len(lines)}")
                print(f"  非空行数: {len(non_empty_lines)}")
                print()

                # 显示前500字符
                print("提取的文本预览 (前500字符):")
                print("=" * 80)
                print(full_text[:500])
                if len(full_text) > 500:
                    print("...")
                print("=" * 80)
                print()

                # 显示最后500字符
                if len(full_text) > 1000:
                    print("提取的文本预览 (最后500字符):")
                    print("=" * 80)
                    print("...")
                    print(full_text[-500:])
                    print("=" * 80)
                    print()

                print("✓ 测试完成!")
                return

            elif 'error' in response:
                error = response['error']
                print("-" * 80)
                print("✗ OCR提取失败!")
                print("-" * 80)
                print(f"错误代码: {error.get('code')}")
                print(f"错误信息: {error.get('message')}")
                print(f"错误详情: {error.get('data', {})}")
                print()

    except websockets.exceptions.WebSocketException as e:
        print(f"✗ WebSocket错误: {e}")
        print()
        print("故障排查:")
        print("  1. 检查MCP Router是否运行: curl http://localhost:8000/health")
        print("  2. 检查MCP Router日志")
        print()

    except Exception as e:
        print(f"✗ 未预期的错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_pdf_ocr())
