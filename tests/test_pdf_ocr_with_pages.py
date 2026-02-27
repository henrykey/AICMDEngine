#!/usr/bin/env python3
"""
PDF OCR测试 - 支持指定页面参数

用法:
  # OCR第1页 (使用默认用户名密码: admin/admin123)
  python test_pdf_ocr_with_pages.py --pages 1

  # OCR第5,10,15页
  python test_pdf_ocr_with_pages.py --pages 5,10,15

  # OCR第1-10页
  python test_pdf_ocr_with_pages.py --pages 1-10

  # OCR随机3页
  python test_pdf_ocr_with_pages.py --random 3

  # OCR前5页
  python test_pdf_ocr_with_pages.py --first 5

  # 指定用户名密码
  python test_pdf_ocr_with_pages.py --username admin --password admin123 --pages 1

  # 强制重新登录
  python test_pdf_ocr_with_pages.py --force-login --pages 1

依赖安装:
  pip install websockets pdf2image Pillow aiohttp

参考文档：
- /Users/kehongwei/workspace/AICMDEngine/docs/PADDELEOCR_MCP_INTEGRATION.md
- /Users/kehongwei/workspace/AICMDEngine/docs/PADDELEOCR_QUICKSTART.md
"""

import asyncio
import websockets
import websockets.exceptions
import json
from pathlib import Path
import random
import base64
import argparse
import time
from pdf2image import convert_from_path
import io
import aiohttp

# 配置
MCP_ROUTER_URL = "ws://localhost:8000/mcp/v1"
MCP_ROUTER_HTTP_URL = "http://localhost:8000"  # MCP Router的HTTP接口 (用于登录)
PDF_PATH = Path.home() / "Documents/GB/GB∕T 150.1~4-2024 压力容器 扫描版.pdf"
TOKEN_FILE = "/tmp/token.txt"


async def login_and_get_token(username="admin", password="admin123", force_login=False):
    """登录MCP Router并获取JWT token (MCP Router认证托管给membership)"""

    # 如果不是强制登录，先检查token文件是否存在
    if not force_login:
        try:
            if Path(TOKEN_FILE).exists():
                existing_token = open(TOKEN_FILE).read().strip()
                if existing_token:
                    # 验证token是否有效（尝试连接MCP Router）
                    print("→ 验证已保存的JWT token...")
                    if await test_mcp_connection(existing_token):
                        print("✓ 已保存的token有效，直接使用")
                        return existing_token
                    else:
                        print("⚠️  已保存的token无效或已过期")
        except Exception as e:
            print(f"⚠️  Token验证失败: {e}")

    # Token文件不存在、无效或强制登录，需要登录
    print(f"→ 登录MCP Router获取JWT token...")
    print(f"  用户: {username}")
    print(f"  MCP Router: {MCP_ROUTER_HTTP_URL}")

    # MCP Router提供登录接口，内部认证托管给membership
    login_url = f"{MCP_ROUTER_HTTP_URL}/v1/auth/login"
    payload = {
        "username": username,
        "password": password
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                login_url,
                json=payload,
                headers={"Content-Type": "application/json"}
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    token = data.get('access_token')

                    if token:
                        # 保存token到文件
                        with open(TOKEN_FILE, 'w') as f:
                            f.write(token)

                        print("✓ 登录成功，JWT token已保存")
                        return token
                else:
                    error_text = await response.text()
                    print(f"✗ 登录失败: {response.status}")
                    print(f"  错误详情: {error_text}")
                    return None
    except Exception as e:
        print(f"✗ 登录请求失败: {e}")
        import traceback
        traceback.print_exc()
        return None


async def test_mcp_connection(jwt_token):
    """测试MCP Router连接"""
    # 使用 query 参数传递 token（兼容性更好）
    ws_url = f"{MCP_ROUTER_URL}?token={jwt_token}"

    try:
        print("→ 测试MCP Router连接...")
        async with websockets.connect(ws_url) as websocket:
            print("✓ MCP Router连接正常")
            await websocket.close()
            return True
    except Exception as e:
        print(f"✗ MCP Router连接失败: {e}")
        return False


def parse_pages_arg(pages_str):
    """解析页码参数"""
    pages = []

    for part in pages_str.split(','):
        part = part.strip()
        if '-' in part:
            # 处理范围: "1-10"
            start, end = part.split('-')
            pages.extend(range(int(start), int(end) + 1))
        else:
            # 单个页码
            pages.append(int(part))

    return [p - 1 for p in pages]  # 转换为0-based索引


class StdIoTransport:
    def __init__(self, proc):
        self.proc = proc

    async def send(self, text: str):
        if self.proc.stdin is None:
            raise RuntimeError('stdio stdin is closed')
        self.proc.stdin.write((text + "\n").encode())
        await self.proc.stdin.drain()
        print(f"  [调试] stdin已写入 {len(text)} 字符，drain()完成", flush=True)

    async def recv(self, timeout_seconds=300) -> str:
        """读取完整的 MCP RPC 响应（可能跨越多行，跳过中间的日志消息）
        
        MCP 响应必须包含 result 或 error 字段。
        中间可能会收到日志消息，我们跳过它们。
        长时间运行的任务（如OCR）可能需要数分钟，使用大的默认超时。
        
        参数:
            timeout_seconds: 等待响应的最大秒数（默认5分钟用于长时间OCR任务）
        """
        if self.proc.stdout is None:
            raise RuntimeError('stdio stdout is closed')
        
        buffer = ""
        decoder = json.JSONDecoder()
        max_wait_objects = 1000  # 最多读取 1000 个 JSON 对象后放弃（防止无限循环）
        objects_read = 0
        start_time = time.time()
        
        async def _read_with_timeout():
            nonlocal buffer, objects_read
            
            while objects_read < max_wait_objects:
                # 计算剩余超时时间
                elapsed = time.time() - start_time
                remaining = timeout_seconds - elapsed
                
                if remaining <= 0:
                    raise TimeoutError(f'Timeout waiting for RPC response after {timeout_seconds}s (read {objects_read} objects)')
                
                # 使用较短的readline超时（30秒），防止单个readline阻塞整个操作
                # 这样即使长任务正在处理，我们也能定期检查连接
                line_timeout = min(30, remaining)
                
                try:
                    line = await asyncio.wait_for(self.proc.stdout.readline(), timeout=line_timeout)
                except asyncio.TimeoutError:
                    # 如果readline超时，但总体超时还未到，继续等待（可能是长任务）
                    if remaining > 0:
                        print(f"  [调试] readline超时（{line_timeout}s），继续等待... ({objects_read} objects已读，{remaining:.0f}s剩余)")
                        continue
                    else:
                        raise TimeoutError(f'Timeout waiting for RPC response after {timeout_seconds}s')
                
                if not line:
                    # 检查进程是否仍在运行
                    if self.proc.returncode is not None:
                        stderr_data = ""
                        try:
                            if self.proc.stderr:
                                stderr_chunk = await asyncio.wait_for(self.proc.stderr.read(1000), timeout=0.1)
                                if stderr_chunk:
                                    stderr_data = stderr_chunk.decode(errors='ignore')
                        except:
                            pass
                        raise EOFError(f'stdio EOF (process exited with code {self.proc.returncode})\nstderr: {stderr_data[:200]}')
                    else:
                        raise EOFError('stdio EOF')
                
                buffer += line.decode()
                
                # 尝试解析为 JSON 对象
                try:
                    stripped = buffer.strip()
                    if not stripped:
                        continue
                    
                    obj, idx = decoder.raw_decode(stripped)
                    objects_read += 1
                    buffer = stripped[idx:].strip()  # 丢弃已解析的部分
                    
                    # 检查这是否是 RPC 响应（有 result 或 error 字段）
                    if isinstance(obj, dict) and ('result' in obj or 'error' in obj):
                        # 这是我们要找的响应
                        return json.dumps(obj)
                    # 否则这是一个日志或其他消息，继续读取
                    
                except json.JSONDecodeError:
                    # 还没有完整的 JSON，继续读下一行
                    continue
            
            raise RuntimeError(f'Too many objects received ({objects_read}) while waiting for RPC response')
        
        try:
            return await _read_with_timeout()
        except TimeoutError as e:
            raise TimeoutError(str(e))
        except EOFError as e:
            raise e


class WebSocketTransport:
    def __init__(self, websocket):
        self.websocket = websocket

    async def send(self, text: str):
        await self.websocket.send(text)

    async def recv(self) -> str:
        return await self.websocket.recv()


async def call_tool_with_retry(transport, tool_request, max_retries=2):
    """调用工具并实现重试机制。
    transport: 对象须实现 async send(text) 和 async recv() -> str
    """
    for attempt in range(max_retries + 1):
        try:
            await transport.send(json.dumps(tool_request))
            print(f"  [调试] 已发送请求，等待响应...")
            raw = await transport.recv()
            print(f"  [调试] 收到响应: {raw[:200] if len(raw) > 200 else raw}...")
            response = json.loads(raw)

            if 'error' in response:
                error = response['error']
                if 'timeout' in str(error.get('message', '')).lower():
                    if attempt < max_retries:
                        print(f"  ⚠️  超时，重试 {attempt + 1}/{max_retries}...")
                        await asyncio.sleep(2)
                        continue
            return response

        except asyncio.TimeoutError:
            if attempt < max_retries:
                print(f"  ⚠️  asyncio 超时，重试 {attempt + 1}/{max_retries}...")
                await asyncio.sleep(2)
                continue
            else:
                return {
                    'error': {
                        'code': -1,
                        'message': f'Timeout after {max_retries} retries'
                    }
                }
        except Exception as e:
            print(f"  [调试] 异常: {type(e).__name__}: {e}")
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


async def _do_ocr_with_transport(transport, pages, num_random, first_n, use_router=False):
    """使用已建立的 transport 进行 OCR 处理的内部函数
    
    参数:
        transport: 已连接的 transport 对象
        pages, num_random, first_n: 页面选择参数
        use_router: 是否通过 Router 调用（True 时使用 paddleocr.ocr，False 时使用 ocr）
    """
    # 代理来选择工具名
    tool_name = "paddleocr.ocr" if use_router else "ocr"
    # 确定要处理的页面
    if pages is not None:
        # 使用指定页码
        page_indices = pages
        print(f"→ 处理指定页面: {[p+1 for p in pages]}")
    elif num_random is not None:
        # 先提取所有页，然后随机选择
        print(f"→ 随机选择 {num_random} 页")
        # 先提取总页数
        all_images = convert_from_path(PDF_PATH)
        total_pages = len(all_images)
        print(f"  PDF总页数: {total_pages}")
        del all_images  # 释放内存
        page_indices = random.sample(range(total_pages), min(num_random, total_pages))
        print(f"  随机选择: {[p+1 for p in page_indices]}")
    elif first_n is not None:
        # 处理前N页
        page_indices = list(range(first_n))
        print(f"→ 处理前 {first_n} 页")
    else:
        # 默认：随机3-5页
        print(f"→ 随机选择 3-5 页")
        all_images = convert_from_path(PDF_PATH)
        total_pages = len(all_images)
        del all_images
        num_pages = random.randint(3, 5)
        page_indices = random.sample(range(total_pages), min(num_pages, total_pages))

    print()

    # 从PDF提取指定页面
    print("→ 从PDF提取页面图像...")
    print()

    # 计算需要提取的页面范围
    min_page = min(page_indices)
    max_page = max(page_indices)

    # 提取所需页面（多提取一些避免索引问题）
    images = convert_from_path(
        PDF_PATH,
        first_page=min_page + 1,  # pdf2image使用1-based
        last_page=max_page + 1
    )

    # 创建索引映射
    image_dict = {i + min_page: img for i, img in enumerate(images)}

    print(f"✓ 成功提取 {len(images)} 页图像")
    print(f"  页面范围: 第{min_page+1}页 到 第{max_page+1}页")
    print()

    # 统计信息
    total_chars = 0
    total_chinese = 0
    successful_pages = 0
    total_time = 0

    # 对每页进行OCR
    for idx, page_num in enumerate(page_indices, 1):
        print("=" * 80)
        print(f"处理第 {page_num + 1} 页 ({idx}/{len(page_indices)})")
        print("=" * 80)

        if page_num not in image_dict:
            print(f"✗ 页面 {page_num + 1} 不在提取范围内")
            continue

        image = image_dict[page_num]

        # 将图像转换为base64
        img_buffer = io.BytesIO()
        image.save(img_buffer, format='PNG')
        img_bytes = img_buffer.getvalue()
        img_base64 = base64.b64encode(img_bytes).decode('utf-8')
        img_size_kb = len(img_bytes) / 1024

        print(f"图像大小: {img_size_kb:.2f} KB")
        print()

        # 调用OCR工具
        tool_call_request = {
            "jsonrpc": "2.0",
            "id": 2 + idx,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": {
                    "input_data": img_base64,
                    "output_mode": "simple"
                }
            }
        }

        print(f"→ 调用{tool_name}工具...")
        print()

        start_time = time.time()
        response = await call_tool_with_retry(transport, tool_call_request)
        elapsed_time = time.time() - start_time
        total_time += elapsed_time

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
                print("提取的文本内容:")
                print("-" * 80)
                print(full_text)
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
    print(f"总处理时间: {total_time:.2f} 秒")
    print(f"平均每页: {total_time/successful_pages if successful_pages > 0 else 0:.2f} 秒")
    print()

    if successful_pages == len(page_indices):
        print("✓ 所有页面处理成功!")
    else:
        print(f"⚠️  {len(page_indices) - successful_pages} 页处理失败")

    print("=" * 80)


async def test_pdf_ocr_with_pages(jwt_token, pages=None, num_random=None, first_n=None, stdio_cmd=None):
    """
    测试PDF OCR

    参数:
        jwt_token: JWT认证token
        pages: 指定页码列表 (0-based索引)
        num_random: 随机选择N页
        first_n: 处理前N页
    """

    print("=" * 80)
    print("PDF OCR 测试 - 支持页面参数")
    print("=" * 80)
    print(f"PDF文件: {PDF_PATH}")
    print(f"文件大小: {PDF_PATH.stat().st_size / 1024 / 1024:.2f} MB")
    print()

    if not PDF_PATH.exists():
        print(f"✗ PDF文件不存在: {PDF_PATH}")
        return

    # 连接 MCP：支持两种模式
    #  - Router/WS 模式（默认）：通过 Router 做 JWT 认证并路由到指定 MCP
    #  - stdio 模式（当 stdio_cmd 提供时）：通过 subprocess 启动 MCP 并直接用 stdin/stdout 通信（跳过 Router）

    transport = None
    proc = None
    try:
        if stdio_cmd:
            # 启动本地 MCP 进程（通过命令行）并使用 stdio 与其通信
            print(f"→ 启动 stdio MCP: {stdio_cmd}")
            proc = await asyncio.create_subprocess_shell(
                stdio_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # 后台打印 stderr 便于调试
            async def _drain_stderr(p):
                if p.stderr is None:
                    return
                while True:
                    line = await p.stderr.readline()
                    if not line:
                        break
                    print(f"[mcp-stderr] {line.decode().rstrip()}")

            asyncio.create_task(_drain_stderr(proc))

            transport = StdIoTransport(proc)
            print("✓ 已通过 stdio 启动 MCP，跳过 Router/WS 认证")
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
                        "name": "pdf-ocr-with-pages",
                        "version": "1.0.0"
                    }
                }
            }
            await transport.send(json.dumps(init_request))
            response = json.loads(await transport.recv())
            print("✓ 初始化完成 (stdio)")
            print()
            
            # 执行 OCR 处理（stdio 模式时工具名为 "ocr"）
            await _do_ocr_with_transport(transport, pages, num_random, first_n, use_router=False)
            
        else:
            # 使用 query 参数传递 token（兼容性更好）
            ws_url = f"{MCP_ROUTER_URL}?token={jwt_token}"
            async with websockets.connect(ws_url, max_size=2**24) as websocket:
                transport = WebSocketTransport(websocket)
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
                            "name": "pdf-ocr-with-pages",
                            "version": "1.0.0"
                        }
                    }
                }
                await transport.send(json.dumps(init_request))
                response = json.loads(await transport.recv())
                print("✓ 初始化完成")
                print()

                # 执行 OCR 处理（Router 模式时工具名为 "paddleocr.ocr"）
                await _do_ocr_with_transport(transport, pages, num_random, first_n, use_router=True)

    except websockets.exceptions.InvalidStatusCode as e:
        print(f"✗ WebSocket连接失败 - HTTP状态码: {e.status_code}")
        print(f"  错误详情: {e}")
        print()
        print("可能的原因:")
        print("  1. MCP Router服务未启动")
        print("  2. JWT token无效或过期")
        print("  3. MCP Router地址配置错误")
        print()
        print("检查命令:")
        print("  lsof -i :8000  # 检查服务是否运行")
        print("  cat /tmp/token.txt  # 检查token是否存在")
        print()

    except websockets.exceptions.WebSocketException as e:
        print(f"✗ WebSocket错误: {e}")
        print(f"  错误类型: {type(e).__name__}")
        print()

    except OSError as e:
        print(f"✗ 网络连接错误: {e}")
        print(f"  请检查MCP Router是否在 {MCP_ROUTER_URL} 运行")
        print()

    except Exception as e:
        print(f"✗ 未预期的错误: {e}")
        print(f"  错误类型: {type(e).__name__}")
        import traceback
        traceback.print_exc()


def main():
    # 声明全局变量（必须在函数开头）
    global MCP_ROUTER_HTTP_URL, MCP_ROUTER_URL

    parser = argparse.ArgumentParser(
        description='PDF OCR测试工具 - 支持指定页面',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  %(prog)s --pages 1                    # OCR第1页
  %(prog)s --pages 5,10,15              # OCR第5,10,15页
  %(prog)s --pages 1-10                 # OCR第1-10页
  %(prog)s --random 3                   # 随机OCR 3页
  %(prog)s --first 5                    # OCR前5页
  %(prog)s --username admin --password admin123 --pages 1  # 指定用户名密码
        '''
    )

    parser.add_argument(
        '--pages',
        type=str,
        help='指定页码 (例: 1 或 5,10,15 或 1-10)'
    )

    parser.add_argument(
        '--random',
        type=int,
        metavar='N',
        help='随机选择N页进行OCR'
    )

    parser.add_argument(
        '--first',
        type=int,
        metavar='N',
        help='处理前N页'
    )

    parser.add_argument(
        '--username',
        type=str,
        default='admin',
        help='Membership API用户名 (默认: admin)'
    )

    parser.add_argument(
        '--password',
        type=str,
        default='admin123',
        help='Membership API密码 (默认: admin123)'
    )

    parser.add_argument(
        '--api-url',
        type=str,
        default=MCP_ROUTER_HTTP_URL,
        help=f'MCP Router地址 (默认: {MCP_ROUTER_HTTP_URL})'
    )

    parser.add_argument(
        '--ws-url',
        type=str,
        default=MCP_ROUTER_URL,
        help=f'MCP Router WebSocket URL (默认: {MCP_ROUTER_URL})'
    )

    parser.add_argument(
        '--stdio-cmd',
        type=str,
        default=None,
        help='通过 stdio 启动并直接连接 MCP 的命令；启用后跳过 Router/WS 认证。例如: "python -m paddleocr_mcp --verbose"'
    )

    parser.add_argument(
        '--force-login',
        action='store_true',
        help='强制重新登录，忽略已保存的token'
    )

    args = parser.parse_args()

    # 修改MCP Router URL（如果通过命令行指定）
    MCP_ROUTER_HTTP_URL = args.api_url
    # WebSocket URL 可选覆盖
    MCP_ROUTER_URL = args.ws_url

    # 确定要处理的页面
    pages = None
    num_random = None
    first_n = None

    if args.pages:
        pages = parse_pages_arg(args.pages)
    elif args.random:
        num_random = args.random
    elif args.first:
        first_n = args.first
    else:
        # 默认：随机3-5页
        num_random = random.randint(3, 5)

    # 运行测试
    async def run_with_connection_check():
        # 如果用户指定了 stdio 命令，则直接走 stdio 模式，不通过 Router 登录/验证
        if args.stdio_cmd:
            print("→ 使用 stdio 模式，跳过 Router 登录/验证")
            await test_pdf_ocr_with_pages(None, pages, num_random, first_n, stdio_cmd=args.stdio_cmd)
            return

        # 1. 先登录获取token（自动验证旧token，无效则重新登录）
        jwt_token = await login_and_get_token(args.username, args.password, args.force_login)

        if not jwt_token:
            print()
            print("=" * 80)
            print("无法获取JWT token，请检查:")
            print("  1. MCP Router服务是否启动")
            print(f"     检查: lsof -i :8000")
            print("  2. 用户名密码是否正确")
            print(f"     当前: {args.username} / {args.password}")
            print(f"  3. MCP Router地址是否正确")
            print(f"     当前: {MCP_ROUTER_HTTP_URL}")
            print()
            print("提示: 可以使用 --username 和 --password 指定用户名密码")
            print("=" * 80)
            return

        print()

        # 2. 测试MCP Router连接
        if not await test_mcp_connection(jwt_token):
            print()
            print("=" * 80)
            print("无法连接到MCP Router，请检查:")
            print("  1. MCP Router服务是否启动")
            print(f"     检查: lsof -i :8000")
            print("  2. JWT token是否有效")
            print(f"     Token已从 {MCP_ROUTER_HTTP_URL} 获取")
            print("  3. MCP Router地址是否正确")
            print(f"     当前: {MCP_ROUTER_URL}")
            print("=" * 80)
            return

        print()
        # 3. 连接成功，运行OCR测试
        await test_pdf_ocr_with_pages(jwt_token, pages, num_random, first_n)

    asyncio.run(run_with_connection_check())


if __name__ == "__main__":
    main()
