#!/usr/bin/env python3
"""
PDF2MD Enhanced MCP服务远程调用测试工具

用法:
  python test_pdf2md_enhanced_mcp.py --page 1
  python test_pdf2md_enhanced_mcp.py --pages 1,2,3
  python test_pdf2md_enhanced_mcp.py --document
  python test_pdf2md_enhanced_mcp.py --pages 1-5 --merge-mode both --check-merge
"""

import asyncio
import base64
import json
import time
from pathlib import Path
import argparse

import aiohttp
import fitz
import websockets
import websockets.exceptions

# 配置
MCP_ROUTER_URL = "ws://localhost:8000/mcp/v1"
MCP_ROUTER_HTTP_URL = "http://localhost:8000"
PDF_PATH = Path.home() / "Documents/GB/GB∕T 150.1~4-2024 压力容器 扫描版.pdf"
TOKEN_FILE = "/tmp/pdf2md_token.txt"


class WebSocketTransport:
    def __init__(self, websocket):
        self.websocket = websocket

    async def send(self, text: str):
        await self.websocket.send(text)

    async def recv(self) -> str:
        return await self.websocket.recv()


def parse_pages_arg(pages_str):
    pages = []
    for part in pages_str.split(','):
        part = part.strip()
        if '-' in part:
            start, end = part.split('-')
            pages.extend(range(int(start), int(end) + 1))
        else:
            pages.append(int(part))
    return sorted(set(pages))


def get_pdf_total_pages(pdf_path: Path) -> int:
    doc = fitz.open(pdf_path)
    try:
        return len(doc)
    finally:
        doc.close()


def extract_pdf_page(pdf_path: Path, page_num: int) -> bytes:
    doc = fitz.open(pdf_path)
    try:
        single_page_doc = fitz.open()
        single_page_doc.insert_pdf(doc, from_page=page_num - 1, to_page=page_num - 1)
        return single_page_doc.write()
    finally:
        doc.close()


async def call_tool_with_retry(transport, tool_request, max_retries=2):
    for attempt in range(max_retries + 1):
        try:
            await transport.send(json.dumps(tool_request))
            raw = await transport.recv()
            response = json.loads(raw)
            if 'error' in response:
                error = response['error']
                if 'timeout' in str(error.get('message', '')).lower() and attempt < max_retries:
                    print(f"  ⚠️  超时，重试 {attempt + 1}/{max_retries}...")
                    await asyncio.sleep(2)
                    continue
            return response
        except asyncio.TimeoutError:
            if attempt < max_retries:
                print(f"  ⚠️  asyncio 超时，重试 {attempt + 1}/{max_retries}...")
                await asyncio.sleep(2)
                continue
            return {'error': {'code': -1, 'message': f'Timeout after {max_retries} retries'}}
        except Exception as e:
            if attempt < max_retries:
                print(f"  ⚠️  错误: {e}，重试 {attempt + 1}/{max_retries}...")
                await asyncio.sleep(2)
                continue
            return {'error': {'code': -1, 'message': f'RPC error after {max_retries} retries: {e}'}}


async def _call_tool(transport, tool_name, args, req_id):
    req = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": args},
    }
    return await call_tool_with_retry(transport, req)


def _extract_json_from_tool_response(response):
    if 'result' not in response:
        return None
    result_obj = response.get("result", {})
    if result_obj.get("isError") is True:
        # Router-level error transport: keep text for caller decision.
        content = result_obj.get("content", [])
        msg = ""
        if content and isinstance(content, list):
            first = content[0] or {}
            msg = first.get("text", "") if isinstance(first, dict) else str(first)
        return {"error": msg or "tool_error"}

    for item in response['result'].get('content', []):
        if item.get('type') == 'text':
            text = item.get('text', '')
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"raw_text": text}
    return None


def validate_merge(finalize_data, merge_mode):
    summary = finalize_data.get("summary", {})
    completed_pages = summary.get("completed_pages", [])
    ok = True
    issues = []

    if merge_mode in {"markdown", "both"}:
        merged_markdown = finalize_data.get("merged_markdown") or ""
        if not merged_markdown and completed_pages:
            ok = False
            issues.append("merged_markdown为空")
        for p in completed_pages:
            marker = f"<!-- page:{p} -->"
            if marker not in merged_markdown:
                ok = False
                issues.append(f"missing markdown marker for page {p}")

    if merge_mode in {"rag", "both"}:
        merged_rag = finalize_data.get("merged_rag") or []
        rag_pages = sorted([x.get("page_no") for x in merged_rag if isinstance(x, dict)])
        if rag_pages != sorted(completed_pages):
            ok = False
            issues.append(f"merged_rag页不匹配: expected={sorted(completed_pages)} actual={rag_pages}")

    return ok, issues


async def login_and_get_token(username="admin", password="admin123", force_login=False):
    if not force_login and Path(TOKEN_FILE).exists():
        existing_token = open(TOKEN_FILE).read().strip()
        if existing_token:
            print("→ 验证已保存的JWT token...")
            if await test_mcp_connection(existing_token):
                print("✓ 已保存的token有效，直接使用")
                return existing_token
            print("⚠️  已保存的token无效或已过期")

    print("→ 登录MCP Router获取JWT token...")
    print(f"  用户: {username}")
    print(f"  MCP Router: {MCP_ROUTER_HTTP_URL}")

    login_url = f"{MCP_ROUTER_HTTP_URL}/v1/auth/login"
    payload = {"username": username, "password": password}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(login_url, json=payload, headers={"Content-Type": "application/json"}) as response:
                if response.status != 200:
                    print(f"✗ 登录失败: {response.status}")
                    print(f"  错误详情: {await response.text()}")
                    return None
                data = await response.json()
                token = data.get('access_token')
                if token:
                    with open(TOKEN_FILE, 'w') as f:
                        f.write(token)
                    print("✓ 登录成功，JWT token已保存")
                return token
    except Exception as e:
        print(f"✗ 登录请求失败: {e}")
        return None


async def test_mcp_connection(jwt_token):
    ws_url = f"{MCP_ROUTER_URL}?token={jwt_token}"
    try:
        print("→ 测试MCP Router连接...")
        async with websockets.connect(ws_url):
            print("✓ MCP Router连接正常")
            return True
    except Exception as e:
        print(f"✗ MCP Router连接失败: {e}")
        return False


async def fetch_router_vlm_info(server_name: str = "pdf2md-enhanced"):
    """读取 Router 侧 MCP->LLM 绑定，并打印 model/base_url。"""
    info = {
        "server_name": server_name,
        "llm_provider": None,
        "source": None,
        "model": None,
        "base_url": None,
    }
    try:
        async with aiohttp.ClientSession() as session:
            bind_url = f"{MCP_ROUTER_HTTP_URL}/v1/mcp/servers/{server_name}/llm-provider"
            async with session.get(bind_url) as resp:
                if resp.status != 200:
                    return info
                bind = await resp.json()
                info["llm_provider"] = bind.get("llm_provider")
                info["source"] = bind.get("source")

            provider = info["llm_provider"]
            if provider:
                detail_url = f"{MCP_ROUTER_HTTP_URL}/api/llm/providers/{provider}"
                async with session.get(detail_url) as resp:
                    if resp.status == 200:
                        detail = await resp.json()
                        info["model"] = detail.get("model")
                        info["base_url"] = detail.get("base_url")
    except Exception:
        pass
    return info


async def run_task_pages(transport, task_name, pdf_base64, pages, policy, merge_mode, check_merge):
    start_tool = "pdf2md-enhanced.start_task"
    process_tool = "pdf2md-enhanced.process_task_page"
    finalize_tool = "pdf2md-enhanced.finalize_task"
    status_tool = "pdf2md-enhanced.get_task_status"

    print(f"→ 调用远程工具: {start_tool}")
    start_resp = await _call_tool(
        transport,
        start_tool,
        {"task_name": task_name, "file_data": pdf_base64, "pages": pages},
        req_id=10,
    )
    start_data = _extract_json_from_tool_response(start_resp)
    if not start_data or start_data.get("error") or not start_data.get("task_id"):
        print("✗ start_task 失败")
        print(start_data)
        return

    task_id = start_data["task_id"]
    planned_pages = start_data.get("planned_pages", pages)
    print(f"✓ 任务已创建: {task_id}")
    print(f"  planned_pages: {planned_pages}")

    prev_context = None
    for idx, page_no in enumerate(planned_pages, start=1):
        print(f"\n→ 处理第 {page_no} 页 ({idx}/{len(planned_pages)})")
        start_time = time.time()
        process_resp = await _call_tool(
            transport,
            process_tool,
            {
                "task_id": task_id,
                "page_no": page_no,
                "policy": policy,
                "prev_context": prev_context,
            },
            req_id=1000 + page_no,
        )
        elapsed = time.time() - start_time
        process_data = _extract_json_from_tool_response(process_resp)
        if not process_data or process_data.get("error"):
            print(f"  ✗ page {page_no} 失败: {process_data}")
            continue
        if process_data.get("raw_text"):
            raw = str(process_data.get("raw_text", ""))
            print(f"  ✗ page {page_no} 非结构化返回: {raw[:220]}")
            continue

        page_result = process_data.get("page_result", {})
        decision = page_result.get("decision", {})
        print(
            f"  ✓ {elapsed:.2f}s mode={decision.get('mode')} "
            f"vlm_calls={decision.get('vlm_calls')} text_chars={((decision.get('metrics') or {}).get('text_chars'))}"
        )

        render_text = ((page_result.get("render") or {}).get("markdown") or "")
        rag_text = ((page_result.get("rag") or {}).get("content") or "")
        print("  Render预览(前120):", render_text[:120].replace("\n", " "))
        print("  RAG预览(前120):", rag_text[:120].replace("\n", " "))
        prev_context = process_data.get("next_context")

    print(f"\n→ 调用远程工具: {status_tool}")
    status_resp = await _call_tool(transport, status_tool, {"task_id": task_id}, req_id=20)
    status_data = _extract_json_from_tool_response(status_resp)
    print("任务状态:", json.dumps(status_data or {}, ensure_ascii=False))

    print(f"\n→ 调用远程工具: {finalize_tool}")
    finalize_resp = await _call_tool(
        transport,
        finalize_tool,
        {"task_id": task_id, "merge_mode": merge_mode},
        req_id=21,
    )
    finalize_data = _extract_json_from_tool_response(finalize_resp)
    if not finalize_data or finalize_data.get("error"):
        print("✗ finalize_task 失败")
        print(finalize_data)
        return

    summary = finalize_data.get("summary", {})
    print("✓ finalize 完成")
    print(f"  status: {summary.get('status')}")
    print(f"  progress: {summary.get('progress')}%")
    print(f"  completed_pages: {summary.get('completed_pages')}")
    print(f"  failed_pages: {summary.get('failed_pages')}")

    if merge_mode in {"markdown", "both"}:
        md = finalize_data.get("merged_markdown") or ""
        print(f"  merged_markdown长度: {len(md)}")
        print("  merged_markdown预览(前300):")
        print("-" * 80)
        print(md[:300])
        print("-" * 80)

    if merge_mode in {"rag", "both"}:
        rag = finalize_data.get("merged_rag") or []
        print(f"  merged_rag条数: {len(rag)}")

    if check_merge:
        ok, issues = validate_merge(finalize_data, merge_mode)
        if ok:
            print("✓ 合并逻辑校验通过")
        else:
            print("✗ 合并逻辑校验失败")
            for item in issues:
                print(f"  - {item}")


async def test_pdf2md_enhanced_mcp(jwt_token, page_num=None, pages=None, test_document=False, pdf_path=None, policy="auto", merge_mode="both", check_merge=False):
    print("=" * 80)
    print("PDF2MD Enhanced MCP服务远程调用测试")
    print("=" * 80)

    if pdf_path is None:
        pdf_path = PDF_PATH

    pdf_path = Path(pdf_path)
    print(f"PDF文件: {pdf_path}")
    if pdf_path.exists():
        print(f"文件大小: {pdf_path.stat().st_size / 1024 / 1024:.2f} MB")
    vlm_info = await fetch_router_vlm_info("pdf2md-enhanced")
    print("VLM配置来源: MCP Router 运行时注入")
    print(f"VLM绑定(provider/source): {vlm_info.get('llm_provider')} / {vlm_info.get('source')}")
    print(f"VLM模型(model): {vlm_info.get('model')}")
    print(f"VLM地址(base_url): {vlm_info.get('base_url')}")
    print(f"policy: {policy}")
    print(f"merge_mode: {merge_mode}")
    print(f"check_merge: {check_merge}")
    print()

    if not pdf_path.exists():
        print(f"✗ PDF文件不存在: {pdf_path}")
        return

    ws_url = f"{MCP_ROUTER_URL}?token={jwt_token}"
    try:
        async with websockets.connect(ws_url, max_size=2**24, ping_timeout=300, close_timeout=10) as websocket:
            transport = WebSocketTransport(websocket)
            print("✓ WebSocket连接成功 (JWT认证通过)")

            init_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "pdf2md-enhanced-remote-test", "version": "1.1.0"},
                },
            }
            await transport.send(json.dumps(init_request))
            _ = json.loads(await transport.recv())
            print("✓ 初始化完成")
            print()

            if page_num:
                print(f"→ 提取第{page_num}页并编码...")
                page_data = extract_pdf_page(pdf_path, page_num)
                page_base64 = base64.b64encode(page_data).decode('utf-8')
                print(f"✓ 第{page_num}页编码完成 ({len(page_base64)//1024} KB)")
                await run_task_pages(
                    transport=transport,
                    task_name=f"single-page-{page_num}-{int(time.time())}",
                    pdf_base64=page_base64,
                    pages=[1],
                    policy=policy,
                    merge_mode=merge_mode,
                    check_merge=check_merge,
                )
                return

            print("→ 读取完整PDF并编码...")
            with open(pdf_path, 'rb') as f:
                pdf_base64 = base64.b64encode(f.read()).decode('utf-8')
            total_pages = get_pdf_total_pages(pdf_path)
            print(f"✓ PDF编码完成 ({len(pdf_base64)//1024} KB), total_pages={total_pages}")

            if test_document:
                target_pages = list(range(1, total_pages + 1))
            elif pages:
                target_pages = [p for p in pages if 1 <= p <= total_pages]
            else:
                target_pages = [1]

            await run_task_pages(
                transport=transport,
                task_name=f"multi-page-{int(time.time())}",
                pdf_base64=pdf_base64,
                pages=target_pages,
                policy=policy,
                merge_mode=merge_mode,
                check_merge=check_merge,
            )

    except websockets.exceptions.InvalidStatusCode as e:
        print(f"✗ WebSocket连接失败 - HTTP状态码: {e.status_code}")
    except websockets.exceptions.WebSocketException as e:
        print(f"✗ WebSocket错误: {e}")
    except OSError as e:
        print(f"✗ 网络连接错误: {e}")
    except Exception as e:
        print(f"✗ 未预期的错误: {e}")


def main():
    global MCP_ROUTER_HTTP_URL, MCP_ROUTER_URL

    parser = argparse.ArgumentParser(
        description='PDF2MD Enhanced MCP服务测试工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  %(prog)s --page 1
  %(prog)s --pages 1,2,3 --check-merge
  %(prog)s --document --merge-mode both
  %(prog)s --pages 1-5 --check-merge
        '''
    )

    parser.add_argument('--page', type=int, help='测试指定页码')
    parser.add_argument('--pages', type=str, help='测试多个页码 (例: 1,2,3 或 1-5)')
    parser.add_argument('--document', action='store_true', help='测试文档级处理(全页)')
    parser.add_argument('--pdf-path', type=str, default=None, help='PDF文件路径')

    parser.add_argument('--policy', type=str, default='auto', choices=['auto', 'force_direct', 'force_vlm'], help='页处理策略')
    parser.add_argument('--merge-mode', type=str, default='both', choices=['none', 'markdown', 'rag', 'both'], help='finalize合并模式')
    parser.add_argument('--check-merge', action='store_true', help='启用多页合并逻辑校验')

    parser.add_argument('--username', type=str, default='admin', help='Membership API用户名')
    parser.add_argument('--password', type=str, default='admin123', help='Membership API密码')
    parser.add_argument('--api-url', type=str, default=MCP_ROUTER_HTTP_URL, help=f'MCP Router地址 (默认: {MCP_ROUTER_HTTP_URL})')
    parser.add_argument('--ws-url', type=str, default=MCP_ROUTER_URL, help=f'MCP Router WebSocket URL (默认: {MCP_ROUTER_URL})')
    parser.add_argument('--force-login', action='store_true', help='强制重新登录，忽略已保存的token')

    args = parser.parse_args()

    MCP_ROUTER_HTTP_URL = args.api_url
    MCP_ROUTER_URL = args.ws_url

    page_num = args.page if args.page else None
    pages = parse_pages_arg(args.pages) if args.pages else None

    async def run_with_connection_check():
        jwt_token = await login_and_get_token(args.username, args.password, args.force_login)
        if not jwt_token:
            print("✗ 无法获取JWT token")
            return

        if not await test_mcp_connection(jwt_token):
            print("✗ 无法连接到MCPRouter")
            return

        await test_pdf2md_enhanced_mcp(
            jwt_token=jwt_token,
            page_num=page_num,
            pages=pages,
            test_document=args.document,
            pdf_path=args.pdf_path,
            policy=args.policy,
            merge_mode=args.merge_mode,
            check_merge=args.check_merge,
        )

    asyncio.run(run_with_connection_check())


if __name__ == '__main__':
    main()
