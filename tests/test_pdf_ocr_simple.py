#!/usr/bin/env python3
"""
简单的PDF OCR测试 - 使用文件路径而不是base64
"""

import asyncio
import websockets
import json
from pathlib import Path

# 配置
MCP_ROUTER_URL = "ws://localhost:8000/mcp/v1"
PDF_PATH = Path.home() / "Documents/GB/GB∕T 150.1~4-2024 压力容器 扫描版.pdf"
JWT_TOKEN = open("/tmp/token.txt").read().strip()


async def test_pdf_ocr():
    """使用paddleocr.ocr工具测试PDF提取"""

    print("=" * 80)
    print("PDF OCR 测试 (使用文件路径)")
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
        async with websockets.connect(ws_url, max_size=2**24) as websocket:  # 16MB max
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

            # 调用paddleocr.ocr工具
            tool_call_request = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "paddleocr.ocr",
                    "arguments": {
                        "file_path": str(PDF_PATH)
                    }
                }
            }

            print("→ 调用 paddleocr.ocr 工具...")
            print(f"  文件路径: {PDF_PATH}")
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

                # 显示前1000字符
                if len(full_text) > 0:
                    print("提取的文本预览 (前1000字符):")
                    print("=" * 80)
                    print(full_text[:1000])
                    if len(full_text) > 1000:
                        print("...")
                    print("=" * 80)
                    print()

                    # 检查是否包含中文
                    chinese_chars = sum(1 for c in full_text if '\u4e00' <= c <= '\u9fff')
                    print(f"中文字符数: {chinese_chars}")
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

    except Exception as e:
        print(f"✗ 未预期的错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_pdf_ocr())
