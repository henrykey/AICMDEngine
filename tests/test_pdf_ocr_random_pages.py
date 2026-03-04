#!/usr/bin/env python3
"""
PDF OCR测试 - 提取扫描版PDF的文本内容

这个测试演示对整个PDF进行OCR并随机展示部分页面内容。
适用于较小的PDF文件或需要完整文本提取的场景。

参考文档：
- /Users/kehongwei/workspace/AICMDEngine/docs/PADDELEOCR_MCP_INTEGRATION.md
- /Users/kehongwei/workspace/AICMDEngine/docs/PADDELEOCR_QUICKSTART.md

⚠️  注意：对于大文件(>50MB)，建议使用test_pdf_pages_ocr.py进行单页处理
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
    """
    测试PDF OCR文本提取

    工具参数：
    - input_data: PDF文件路径 (支持文件路径、URL、Base64)
    - output_mode: "simple" (简单文本) 或 "detailed" (详细信息)

    对于大型PDF文件，建议：
    1. 使用test_pdf_pages_ocr.py进行单页处理
    2. 或将PDF拆分为多个小文件分别处理
    """

    print("=" * 80)
    print("PDF OCR 文本提取测试")
    print("=" * 80)
    print(f"PDF文件: {PDF_PATH}")
    print(f"文件大小: {PDF_PATH.stat().st_size / 1024 / 1024:.2f} MB")
    print()

    if not PDF_PATH.exists():
        print(f"✗ PDF文件不存在: {PDF_PATH}")
        return

    # 连接MCP Router
    ws_url = f"{MCP_ROUTER_URL}?token={JWT_TOKEN}"

    try:
        async with websockets.connect(ws_url, max_size=2**24) as websocket:
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
                        "name": "pdf-ocr-test",
                        "version": "1.0.0"
                    }
                }
            }
            await websocket.send(json.dumps(init_request))
            response = json.loads(await websocket.recv())
            print("✓ 初始化完成")
            print()

            # 调用paddleocr.ocr工具 - 使用正确的参数名
            tool_call_request = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "paddleocr.ocr",
                    "arguments": {
                        "input_data": str(PDF_PATH),
                        "output_mode": "simple"
                    }
                }
            }

            print("→ 调用paddleocr.ocr工具...")
            print(f"  参数: input_data={PDF_PATH}")
            print(f"  参数: output_mode=simple")
            print()
            print("← 等待OCR处理 (可能需要几分钟)...")
            print()

            await websocket.send(json.dumps(tool_call_request))
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

                # 检查是否包含中文
                chinese_chars = sum(1 for c in full_text if '\u4e00' <= c <= '\u9fff')
                print(f"中文字符数: {chinese_chars}")
                print()

                # 如果提取到了文本，模拟显示3-5页的内容
                # 由于OCR返回的是完整文本，我们按行数来模拟"页"
                if len(non_empty_lines) > 0:
                    # 随机选择3-5个起始行位置来模拟"随机页"
                    num_pages = random.randint(3, 5)
                    lines_per_page = max(50, len(non_empty_lines) // 10)  # 假设每页约50行

                    print(f"随机选择 {num_pages} 页的内容展示:")
                    print("=" * 80)
                    print()

                    # 生成随机页码
                    page_starts = random.sample(
                        range(0, max(1, len(non_empty_lines) - lines_per_page)),
                        min(num_pages, max(1, len(non_empty_lines) - lines_per_page))
                    )

                    for i, start_line in enumerate(page_starts, 1):
                        end_line = min(start_line + lines_per_page, len(non_empty_lines))
                        page_lines = non_empty_lines[start_line:end_line]
                        page_text = '\n'.join(page_lines)

                        print(f"【第 {i} 页】(行 {start_line+1}-{end_line})")
                        print("-" * 80)
                        print(page_text[:500])  # 每页显示前500字符
                        if len(page_text) > 500:
                            print("...")
                        print("-" * 80)
                        print()

                print("=" * 80)
                print("✓ JWT Token传递验证成功!")
                print("✓ OCR工具调用成功，无401错误!")
                print("=" * 80)
                return

            elif 'error' in response:
                error = response['error']
                print("-" * 80)
                print("✗ OCR提取失败!")
                print("-" * 80)
                print(f"错误代码: {error.get('code')}")
                print(f"错误信息: {error.get('message')}")
                if error.get('data'):
                    print(f"错误详情: {error.get('data')}")
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
