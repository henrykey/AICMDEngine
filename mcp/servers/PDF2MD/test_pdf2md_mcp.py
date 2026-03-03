#!/usr/bin/env python3
"""
PDF2MD MCP服务测试工具

用法:
  # 测试单页处理 (使用默认用户名密码: admin/admin123)
  python test_pdf2md_mcp.py --page 1

  # 测试多页处理
  python test_pdf2md_mcp.py --pages 1,2,3

  # 测试文档级处理
  python test_pdf2md_mcp.py --document

  # 测试指定页码范围
  python test_pdf2md_mcp.py --pages 1-5

  # 指定用户名密码
  python test_pdf2md_mcp.py --username admin --password admin123 --page 1

  # 强制重新登录
  python test_pdf2md_mcp.py --force-login --page 1

  # 通过stdio直接连接（跳过Router）
  python test_pdf2md_mcp.py --stdio-cmd "python -m PDF2MD" --page 1

依赖安装:
  pip install websockets aiohttp

参考文档：
- /Users/kehongwei/workspace/AICMDEngine/docs/MCP_CONFIGURATION_GUIDE.md
"""

import asyncio
import websockets
import websockets.exceptions
import json
from pathlib import Path
import argparse
import time
import aiohttp
import base64

# 配置
MCP_ROUTER_URL = "ws://localhost:8000/mcp/v1"
MCP_ROUTER_HTTP_URL = "http://localhost:8000"  # MCP Router的HTTP接口 (用于登录)
PDF_PATH = Path.home() / "Documents/GB/GBT16749-2018.pdf"
TOKEN_FILE = "/tmp/pdf2md_token.txt"


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

    return pages  # 返回1-based页码


class WebSocketTransport:
    def __init__(self, websocket):
        self.websocket = websocket

    async def send(self, text: str):
        await self.websocket.send(text)

    async def recv(self) -> str:
        return await self.websocket.recv()


async def call_tool_with_retry(transport, tool_request, max_retries=2):
    """调用工具并实现重试机制"""
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


async def test_process_page(transport, page_num, pdf_path=None, pdf_base64=None):
    """测试process_pdf_page工具 - 通过MCP Router调用远程服务"""
    print("=" * 80)
    print(f"测试 process_pdf_page - 第{page_num}页")
    print("=" * 80)

    tool_name = "pdf2md.process_pdf_page"

    # 准备参数
    if pdf_base64:
        # 使用base64编码的PDF
        args = {
            "file_data": pdf_base64,
            "page_num": page_num
        }
        print(f"PDF数据: base64编码 ({len(pdf_base64)//1024} KB)")
    elif pdf_path:
        # 传递文件路径（MCP服务端读取）
        args = {
            "file_path": pdf_path,
            "page_num": page_num
        }
        print(f"PDF文件: {Path(pdf_path).name}")
    else:
        print("✗ 错误：必须提供pdf_path或pdf_base64参数")
        return

    print()

    # 构建工具调用请求
    tool_call_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": args
        }
    }

    print(f"→ 调用远程工具: {tool_name}")
    start_time = time.time()
    response = await call_tool_with_retry(transport, tool_call_request)
    elapsed_time = time.time() - start_time

    # 处理结果
    if 'result' in response:
        result = response['result']
        content = result.get('content', [])

        print("✓ 远程调用成功!")
        print(f"  处理时间: {elapsed_time:.2f} 秒")
        print()

        # 提取文本内容
        for item in content:
            if item.get('type') == 'text':
                text = item.get('text', '')
                try:
                    data = json.loads(text)
                    print("返回的数据结构:")
                    print(f"  - page_type: {data.get('page_type')}")
                    print(f"  - page_num: {data.get('page_num')}")
                    print(f"  - success: {data.get('success', True)}")
                    print(f"  - has_render: {'render' in data}")
                    print(f"  - has_rag: {'rag' in data}")
                    print(f"  - has_elements: {'elements' in data}")
                    print()

                    # 显示render预览
                    if 'render' in data:
                        render = data['render']
                        if isinstance(render, dict) and 'markdown' in render:
                            render_text = render['markdown']
                        elif isinstance(render, str):
                            render_text = render
                        else:
                            render_text = str(render)

                        print("【Render预览】（前500字符）")
                        print("-" * 80)
                        print(render_text[:500])
                        print("-" * 80)
                        print()

                    # 显示RAG预览
                    if 'rag' in data:
                        rag = data['rag']
                        if isinstance(rag, dict) and 'content' in rag:
                            rag_text = rag['content']
                        elif isinstance(rag, str):
                            rag_text = rag
                        else:
                            rag_text = str(rag)

                        print("【RAG预览】（前300字符）")
                        print("-" * 80)
                        print(rag_text[:300])
                        print("-" * 80)
                        print()

                except json.JSONDecodeError:
                    print("【原始响应】（非JSON格式）")
                    print(text[:500])
                    print()

    elif 'error' in response:
        error = response['error']
        print("✗ 远程调用失败!")
        print(f"  错误代码: {error.get('code')}")
        print(f"  错误信息: {error.get('message')}")
        print()


async def test_process_document(transport, pdf_path=None, pdf_base64=None):
    """测试process_pdf_document工具 - 通过MCP Router调用远程服务"""
    print("=" * 80)
    print("测试 process_pdf_document")
    print("=" * 80)

    tool_name = "pdf2md.process_pdf_document"

    # 准备参数
    if pdf_base64:
        args = {
            "file_data": pdf_base64
        }
        print(f"PDF数据: base64编码 ({len(pdf_base64)//1024} KB)")
    elif pdf_path:
        args = {
            "file_path": pdf_path
        }
        print(f"PDF文件: {Path(pdf_path).name}")
    else:
        print("✗ 错误：必须提供pdf_path或pdf_base64参数")
        return

    print()

    # 构建工具调用请求
    tool_call_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": args
        }
    }

    print(f"→ 调用远程工具: {tool_name}")
    start_time = time.time()
    response = await call_tool_with_retry(transport, tool_call_request)
    elapsed_time = time.time() - start_time

    # 处理结果
    if 'result' in response:
        result = response['result']
        content = result.get('content', [])

        print("✓ 远程调用成功!")
        print(f"  处理时间: {elapsed_time:.2f} 秒")
        print()

        # 提取文本内容
        for item in content:
            if item.get('type') == 'text':
                text = item.get('text', '')
                try:
                    data = json.loads(text)
                    print("文档结构:")
                    if 'document' in data:
                        doc = data['document']
                        print(f"  - title: {doc.get('title', 'N/A')}")
                        print(f"  - toc_entries: {len(doc.get('toc', []))}")
                        print(f"  - chapters: {len(doc.get('chapters', []))}")
                    if 'elements' in data:
                        elems = data['elements']
                        print(f"  - tables: {len(elems.get('tables', []))}")
                        print(f"  - figures: {len(elems.get('figures', []))}")
                        print(f"  - formulas: {len(elems.get('formulas', []))}")
                    print()

                except json.JSONDecodeError:
                    print("【原始响应】")
                    print(text[:500])
                    print()

    elif 'error' in response:
        error = response['error']
        print("✗ 远程调用失败!")
        print(f"  错误代码: {error.get('code')}")
        print(f"  错误信息: {error.get('message')}")
        print()


async def test_pdf2md_mcp(jwt_token, page_num=None, pages=None, test_document=False, pdf_path=None):
    """测试PDF2MD MCP服务 - 通过MCP Router调用远程服务"""

    print("=" * 80)
    print("PDF2MD MCP服务远程调用测试")
    print("=" * 80)

    # 确定PDF文件
    if pdf_path is None:
        pdf_path = PDF_PATH

    print(f"PDF文件: {pdf_path}")
    if Path(pdf_path).exists():
        print(f"文件大小: {Path(pdf_path).stat().st_size / 1024 / 1024:.2f} MB")
    print()

    if not Path(pdf_path).exists():
        print(f"✗ PDF文件不存在: {pdf_path}")
        return

    # 读取PDF文件为base64
    print("→ 读取PDF文件并编码为base64...")
    with open(pdf_path, 'rb') as f:
        pdf_base64 = base64.b64encode(f.read()).decode('utf-8')
    print(f"✓ PDF编码完成 ({len(pdf_base64)//1024} KB)")
    print()

    # 通过MCP Router连接
    ws_url = f"{MCP_ROUTER_URL}?token={jwt_token}"

    try:
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
                        "name": "pdf2md-remote-test",
                        "version": "1.0.0"
                    }
                }
            }
            await transport.send(json.dumps(init_request))
            response = json.loads(await transport.recv())
            print("✓ 初始化完成")
            print()

            # 执行测试
            if test_document:
                await test_process_document(transport, pdf_base64=pdf_base64)
            elif pages:
                for page in pages:
                    await test_process_page(transport, page, pdf_base64=pdf_base64)
                    await asyncio.sleep(0.5)  # 避免请求过快
            elif page_num:
                await test_process_page(transport, page_num, pdf_base64=pdf_base64)

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
        print("  cat {TOKEN_FILE}  # 检查token是否存在")
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
    # 声明全局变量
    global MCP_ROUTER_HTTP_URL, MCP_ROUTER_URL

    parser = argparse.ArgumentParser(
        description='PDF2MD MCP服务测试工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  %(prog)s --page 1                    # 测试第1页
  %(prog)s --pages 1,2,3               # 测试第1,2,3页
  %(prog)s --pages 1-5                 # 测试第1-5页
  %(prog)s --document                  # 测试文档级处理
  %(prog)s --username admin --password admin123 --page 1
        '''
    )

    parser.add_argument(
        '--page',
        type=int,
        help='测试指定页码'
    )

    parser.add_argument(
        '--pages',
        type=str,
        help='测试多个页码 (例: 1,2,3 或 1-5)'
    )

    parser.add_argument(
        '--document',
        action='store_true',
        help='测试文档级处理'
    )

    parser.add_argument(
        '--pdf-path',
        type=str,
        default=None,
        help='PDF文件路径（默认: ~/Documents/GB/GBT16749-2018.pdf）'
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
        '--force-login',
        action='store_true',
        help='强制重新登录，忽略已保存的token'
    )

    args = parser.parse_args()

    # 修改MCP Router URL
    MCP_ROUTER_HTTP_URL = args.api_url
    MCP_ROUTER_URL = args.ws_url

    # 解析页码参数
    page_num = None
    pages = None

    if args.page:
        page_num = args.page
    elif args.pages:
        pages = parse_pages_arg(args.pages)

    # 确定PDF路径
    pdf_path = args.pdf_path

    # 运行测试
    async def run_with_connection_check():
        # 1. 先登录获取token
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
        # 3. 连接成功，运行远程调用测试
        await test_pdf2md_mcp(jwt_token, page_num, pages, args.document, pdf_path)

    asyncio.run(run_with_connection_check())


if __name__ == "__main__":
    main()
