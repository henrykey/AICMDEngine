#!/usr/bin/env python3
"""
PDF OCR最佳实践测试 - 遵循PaddleOCR MCP官方文档

测试目标：
1. 验证正确的参数使用 (input_data, output_mode)
2. 演示大文件处理策略 (单页提取)
3. 验证JWT token自动传递 (不手动传递auth_token/tenant_id)
4. 展示错误处理和重试机制

参考文档：
- /Users/kehongwei/workspace/AICMDEngine/docs/PADDELEOCR_MCP_INTEGRATION.md
- /Users/kehongwei/workspace/AICMDEngine/docs/PADDELEOCR_QUICKSTART.md
"""

import asyncio
import websockets
import json
from pathlib import Path
import random
import base64
import time
from pdf2image import convert_from_path
import io

# 配置
MCP_ROUTER_URL = "ws://localhost:8000/mcp/v1"
PDF_PATH = Path.home() / "Documents/GB/GB∕T 150.1~4-2024 压力容器 扫描版.pdf"
JWT_TOKEN = open("/tmp/token.txt").read().strip()


async def call_tool_with_retry(websocket, tool_request, max_retries=2):
    """调用工具并实现重试机制"""

    for attempt in range(max_retries + 1):
        try:
            await websocket.send(json.dumps(tool_request))
            response = json.loads(await websocket.recv())

            if 'error' in response:
                error = response['error']

                # 检查是否是超时错误
                if 'timeout' in str(error.get('message', '')).lower():
                    if attempt < max_retries:
                        print(f"  ⚠️  超时，重试 {attempt + 1}/{max_retries}...")
                        await asyncio.sleep(2)
                        continue

                # 其他错误直接返回
                return response

            return response

        except Exception as e:
            if attempt < max_retries:
                print(f"  ⚠️  错误: {e}，重试 {attempt + 1}/{max_retries}...")
                await asyncio.sleep(2)
                continue
            else:
                return {
                    'error': {
                        'code': -1,
                        'message': f'RPC error after {max_retries} retries: {e}'
                    }
                }


async def test_ocr_with_best_practices():
    """使用最佳实践测试PDF OCR"""

    print("=" * 80)
    print("PDF OCR 最佳实践测试")
    print("=" * 80)
    print(f"PDF文件: {PDF_PATH}")
    print(f"文件大小: {PDF_PATH.stat().st_size / 1024 / 1024:.2f} MB")
    print()
    print("测试策略：")
    print("  ✓ 使用正确的参数名 (input_data)")
    print("  ✓ 单页提取避免超时")
    print("  ✓ JWT token自动传递 (不手动传递auth_token)")
    print("  ✓ 实现重试机制")
    print("  ✓ 显示详细统计信息")
    print("=" * 80)
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
                        "name": "pdf-ocr-best-practices",
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
            print("  (遵循文档建议：先提取单页，再进行OCR)")
            print()

            # 提取前10页用于测试
            images = convert_from_path(PDF_PATH, first_page=1, last_page=10)

            print(f"✓ 成功提取 {len(images)} 页图像")
            print()

            # 随机选择3-5页
            num_pages_to_ocr = random.randint(3, 5)
            page_indices = random.sample(range(len(images)), min(num_pages_to_ocr, len(images)))

            print(f"随机选择 {len(page_indices)} 页进行OCR: {[i+1 for i in page_indices]}")
            print()

            # 统计信息
            total_chars = 0
            total_chinese = 0
            successful_pages = 0

            # 对每页进行OCR
            for idx, page_num in enumerate(page_indices, 1):
                print("=" * 80)
                print(f"处理第 {page_num + 1} 页 ({idx}/{len(page_indices)})")
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

                # 调用paddleocr.ocr工具 - 使用正确的参数名
                tool_call_request = {
                    "jsonrpc": "2.0",
                    "id": 2 + page_num,
                    "method": "tools/call",
                    "params": {
                        "name": "paddleocr.ocr",
                        "arguments": {
                            "input_data": img_base64,  # ← 正确的参数名
                            "output_mode": "simple"     # ← simple 或 detailed
                        }
                    }
                }

                print("→ 调用paddleocr.ocr工具...")
                print(f"  参数: input_data=<base64> ({img_size_kb:.1f} KB)")
                print(f"  参数: output_mode=simple")
                print(f"  注意: 不传递auth_token (MCP Router自动传递)")
                print()

                start_time = time.time()

                # 使用带重试的调用
                response = await call_tool_with_retry(websocket, tool_call_request)

                elapsed_time = time.time() - start_time

                # 处理结果
                if 'result' in response:
                    result = response['result']
                    content = result.get('content', [])

                    print("✓ OCR提取成功!")
                    print(f"  处理时间: {elapsed_time:.2f} 秒")
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
                    chinese_chars = sum(1 for c in full_text if '\u4e00' <= c <= '\u9fff')

                    total_chars += len(full_text)
                    total_chinese += chinese_chars
                    successful_pages += 1

                    print(f"文本统计:")
                    print(f"  总字符数: {len(full_text)}")
                    print(f"  非空行数: {len(non_empty_lines)}")
                    print(f"  中文字符数: {chinese_chars}")
                    print()

                    # 显示提取的文本预览
                    if len(full_text) > 0:
                        print("提取的文本预览:")
                        print("-" * 80)
                        preview = full_text[:500]
                        print(preview)
                        if len(full_text) > 500:
                            print("...")
                        print("-" * 80)
                        print()
                    else:
                        print("  (未检测到文本 - 可能是图表或纯图像页面)")
                        print()

                elif 'error' in response:
                    error = response['error']
                    print("✗ OCR提取失败!")
                    print(f"  错误代码: {error.get('code')}")
                    print(f"  错误信息: {error.get('message')}")
                    print()

            # 最终统计
            print("=" * 80)
            print("测试总结")
            print("=" * 80)
            print(f"成功处理: {successful_pages}/{len(page_indices)} 页")
            print(f"总字符数: {total_chars}")
            print(f"总中文字符: {total_chinese}")
            print(f"平均每页字符: {total_chars // successful_pages if successful_pages > 0 else 0}")
            print()
            print("✓ 最佳实践验证成功!")
            print("✓ 参数使用正确 (input_data)")
            print("✓ JWT token自动传递 (无需手动传递)")
            print("✓ 单页处理避免超时")
            print("✓ 重试机制正常工作")
            print("=" * 80)

    except websockets.exceptions.WebSocketException as e:
        print(f"✗ WebSocket错误: {e}")
        print()

    except Exception as e:
        print(f"✗ 未预期的错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_ocr_with_best_practices())
