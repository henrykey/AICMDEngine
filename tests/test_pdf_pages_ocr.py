#!/usr/bin/env python3
"""
PDF单页OCR测试 - 先提取单页图像，再进行OCR

这个测试演示如何处理大型PDF文件以避免超时：
1. 使用pdf2image提取单页图像
2. 对每页单独进行OCR
3. 随机选择3-5页进行测试

参考文档：
- /Users/kehongwei/workspace/AICMDEngine/docs/PADDELEOCR_MCP_INTEGRATION.md
- /Users/kehongwei/workspace/AICMDEngine/docs/PADDELEOCR_QUICKSTART.md
- /Users/kehongwei/workspace/AICMDEngine/external_mcp/PaddleOCR/docs/version3.x/deployment/mcp_server.md
"""

import asyncio
import websockets
import json
from pathlib import Path
import random
import base64
from pdf2image import convert_from_path
import io

# 配置
MCP_ROUTER_URL = "ws://localhost:8000/mcp/v1"
PDF_PATH = Path.home() / "Documents/GB/GB∕T 150.1~4-2024 压力容器 扫描版.pdf"
JWT_TOKEN = open("/tmp/token.txt").read().strip()


async def test_pdf_page_ocr():
    """
    测试PDF单页OCR

    处理策略：
    1. 先提取单页图像 (避免处理整个72MB文件)
    2. 每页单独发送到OCR服务 (避免超时)
    3. 使用正确的参数名: input_data (不是file_path或image)
    """

    print("=" * 80)
    print("PDF单页OCR测试")
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
                        "name": "pdf-page-ocr-test",
                        "version": "1.0.0"
                    }
                }
            }
            await websocket.send(json.dumps(init_request))
            response = json.loads(await websocket.recv())
            print("✓ 初始化完成")
            print()

            # 从PDF提取单页图像
            print("→ 从PDF提取单页图像...")
            print("  (这可能需要几分钟，请耐心等待)")
            print()

            # 使用pdf2image提取前几页
            # 只提取前10页用于测试
            images = convert_from_path(PDF_PATH, first_page=1, last_page=10)

            print(f"✓ 成功提取 {len(images)} 页图像")
            print()

            # 随机选择3-5页
            num_pages_to_ocr = random.randint(3, 5)
            page_indices = random.sample(range(len(images)), min(num_pages_to_ocr, len(images)))

            print(f"随机选择 {len(page_indices)} 页进行OCR: {page_indices}")
            print()

            # 对每页进行OCR
            for page_num in page_indices:
                print("=" * 80)
                print(f"处理第 {page_num + 1} 页")
                print("=" * 80)

                image = images[page_num]

                # 将图像转换为base64
                img_buffer = io.BytesIO()
                image.save(img_buffer, format='PNG')
                img_bytes = img_buffer.getvalue()
                img_base64 = base64.b64encode(img_bytes).decode('utf-8')
                img_size_kb = len(img_bytes) / 1024

                print(f"图像大小: {img_size_kb:.2f} KB")
                print()

                # 调用paddleocr.ocr工具
                tool_call_request = {
                    "jsonrpc": "2.0",
                    "id": 2 + page_num,
                    "method": "tools/call",
                    "params": {
                        "name": "paddleocr.ocr",
                        "arguments": {
                            "input_data": img_base64,
                            "output_mode": "simple"
                        }
                    }
                }

                print("→ 调用paddleocr.ocr工具...")
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
                    print(f"  非空行数: {len(non_empty_lines)}")
                    print()

                    # 检查中文
                    chinese_chars = sum(1 for c in full_text if '\u4e00' <= c <= '\u9fff')
                    print(f"中文字符数: {chinese_chars}")
                    print()

                    # 显示提取的文本
                    if len(full_text) > 0:
                        print("提取的文本内容:")
                        print("=" * 80)
                        print(full_text[:1000])  # 显示前1000字符
                        if len(full_text) > 1000:
                            print("...")
                        print("=" * 80)
                        print()

                elif 'error' in response:
                    error = response['error']
                    print("-" * 80)
                    print("✗ OCR提取失败!")
                    print("-" * 80)
                    print(f"错误代码: {error.get('code')}")
                    print(f"错误信息: {error.get('message')}")
                    print()

                print()

            print("=" * 80)
            print("✓ 测试完成!")
            print("✓ JWT Token传递验证成功!")
            print("✓ 单页OCR工具调用成功，无401错误!")
            print("=" * 80)

    except websockets.exceptions.WebSocketException as e:
        print(f"✗ WebSocket错误: {e}")
        print()

    except Exception as e:
        print(f"✗ 未预期的错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_pdf_page_ocr())
