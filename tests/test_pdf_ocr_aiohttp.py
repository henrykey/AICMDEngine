#!/usr/bin/env python3
"""
PDF OCR测试 - 使用aiohttp WebSocket (备用方案)

如果websockets库有问题，使用这个脚本
"""

import asyncio
import aiohttp
import json
from pathlib import Path
import base64
import time
import argparse
from pdf2image import convert_from_path
import io

# 配置
MCP_ROUTER_HTTP_URL = "http://localhost:8000"
PDF_PATH = Path.home() / "Documents/GB/GB∕T 150.1~4-2024 压力容器 扫描版.pdf"
TOKEN_FILE = "/tmp/token.txt"


async def login_and_get_token(username="admin", password="admin123"):
    """登录MCP Router获取token"""
    try:
        if Path(TOKEN_FILE).exists():
            existing_token = open(TOKEN_FILE).read().strip()
            if existing_token:
                print("→ 使用已保存的JWT token")
                return existing_token
    except Exception:
        pass

    print(f"→ 登录MCP Router...")
    login_url = f"{MCP_ROUTER_HTTP_URL}/v1/auth/login"

    async with aiohttp.ClientSession() as session:
        async with session.post(
            login_url,
            json={"username": username, "password": password}
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                token = data['access_token']
                with open(TOKEN_FILE, 'w') as f:
                    f.write(token)
                print("✓ 登录成功")
                return token
            else:
                print(f"✗ 登录失败: {resp.status}")
                return None


async def ocr_with_aiohttp(jwt_token, page_num):
    """使用aiohttp WebSocket进行OCR"""

    # 提取页面
    print(f"→ 提取第{page_num}页...")
    images = convert_from_path(PDF_PATH, first_page=page_num, last_page=page_num)
    image = images[0]

    # 转换为base64
    img_buffer = io.BytesIO()
    image.save(img_buffer, format='PNG')
    img_bytes = img_buffer.getvalue()
    img_base64 = base64.b64encode(img_bytes).decode('utf-8')

    print(f"  图像大小: {len(img_bytes) / 1024:.2f} KB")

    # 使用aiohttp WebSocket
    ws_url = f"ws://localhost:8000/mcp/v1?token={jwt_token}"

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(ws_url) as ws:
            print("  ✓ WebSocket连接成功")

            # 初始化
            init_msg = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "pdf-ocr", "version": "1.0"}
                }
            }
            await ws.send_str(json.dumps(init_msg))
            init_resp = await ws.receive_str()
            print(f"  ✓ 初始化完成")

            # 调用OCR
            ocr_request = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "paddleocr.ocr",
                    "arguments": {
                        "input_data": img_base64,
                        "output_mode": "simple"
                    }
                }
            }

            print("  → 调用OCR...")
            start_time = time.time()
            await ws.send_str(json.dumps(ocr_request))

            # 接收响应
            response_str = await ws.receive_str()
            elapsed_time = time.time() - start_time

            response = json.loads(response_str)

            if 'result' in response:
                content = response['result'].get('content', [])
                full_text = ""
                for item in content:
                    if item.get('type') == 'text':
                        full_text += item.get('text', '') + "\n"

                print(f"  ✓ OCR成功! 耗时: {elapsed_time:.2f}秒")
                print(f"  文本统计: {len(full_text)}字符")

                # 统计中文
                chinese_chars = sum(1 for c in full_text if '\u4e00' <= c <= '\u9fff')
                print(f"  中文字符: {chinese_chars}")

                return full_text
            else:
                error = response.get('error', {})
                print(f"  ✗ OCR失败: {error.get('message', 'Unknown error')}")
                return None


async def main():
    parser = argparse.ArgumentParser(description='PDF OCR测试 (aiohttp版本)')
    parser.add_argument('--pages', type=str, help='指定页码')
    parser.add_argument('--username', type=str, default='admin')
    parser.add_argument('--password', type=str, default='admin123')
    args = parser.parse_args()

    # 登录
    token = await login_and_get_token(args.username, args.password)
    if not token:
        print("✗ 无法获取token")
        return

    # 解析页码
    if args.pages:
        if '-' in args.pages:
            start, end = map(int, args.pages.split('-'))
            pages = list(range(start, end + 1))
        else:
            pages = [int(args.pages)]
    else:
        pages = [25]  # 默认第25页

    print()
    print("=" * 80)

    for page_num in pages:
        print(f"处理第 {page_num} 页")
        print("-" * 80)

        try:
            text = await ocr_with_aiohttp(token, page_num)

            if text:
                print()
                print("提取的文本:")
                print("=" * 80)
                print(text[:500])
                if len(text) > 500:
                    print("...")
                print("=" * 80)
        except Exception as e:
            print(f"✗ 处理失败: {e}")
            import traceback
            traceback.print_exc()

        print()


if __name__ == "__main__":
    asyncio.run(main())
