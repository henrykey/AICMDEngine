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
import ast
import base64
import json
import re
import time
from pathlib import Path
import argparse
from typing import Any, Dict, List

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


def extract_pdf_pages(pdf_path: Path, pages: list[int]) -> bytes:
    doc = fitz.open(pdf_path)
    try:
        subset_doc = fitz.open()
        for p in pages:
            subset_doc.insert_pdf(doc, from_page=p - 1, to_page=p - 1)
        return subset_doc.write()
    finally:
        doc.close()


def normalize_markdown_output(text: str) -> str:
    """Strip one outer fenced markdown/code block if present."""
    raw = (text or "").strip()
    m = re.match(r"^```[a-zA-Z0-9_-]*\n([\s\S]*?)\n```$", raw)
    if m:
        return m.group(1).strip()
    return raw


def _extract_keywords(text: str, limit: int = 6) -> List[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9_\\-]{1,}|[\u4e00-\u9fff]{2,8}", text or "")
    seen = set()
    out = []
    for w in words:
        k = w.strip()
        if not k:
            continue
        if k in seen:
            continue
        seen.add(k)
        out.append(k)
        if len(out) >= limit:
            break
    return out


def _normalize_section_path(section: str) -> List[str]:
    raw = (section or "").strip()
    if not raw:
        return []
    # e.g. 5.5.2.3 -> ["5", "5.5", "5.5.2", "5.5.2.3"]
    parts = [p for p in raw.split(".") if p]
    out: List[str] = []
    for i in range(1, len(parts) + 1):
        out.append(".".join(parts[:i]))
    return out


def _clean_page_text_for_rag(text: str) -> str:
    s = (text or "").replace("\r\n", "\n").strip()
    if not s:
        return s
    # Remove synthetic markers appended by legacy rag builder.
    s = re.sub(r"\n*\[(FORMULAS|TABLES|FIGURES)\]\n[\s\S]*$", "", s, flags=re.IGNORECASE)
    lines = [ln.rstrip() for ln in s.splitlines()]

    def _is_header_footer_line(line: str) -> bool:
        t = line.strip()
        if not t:
            return False
        # Typical standards header, e.g. GB/T 150.1—2024
        if re.match(r"^[A-Z]{1,6}\s*/?\s*[A-Z]?\s*\d+(?:\.\d+)?\s*[—-]\s*\d{4}$", t):
            return True
        # Standalone page number.
        if re.match(r"^\d{1,4}$", t):
            return True
        return False

    # Trim top/bottom noisy lines only.
    while lines and _is_header_footer_line(lines[0]):
        lines.pop(0)
    while lines and _is_header_footer_line(lines[-1]):
        lines.pop()

    s = "\n".join(lines).strip()
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s


def _clean_render_markdown(text: str) -> str:
    s = normalize_markdown_output(text or "")
    if not s:
        return s
    lines = [ln.rstrip() for ln in s.splitlines()]

    def _is_header_footer_line(line: str) -> bool:
        t = line.strip()
        if not t:
            return False
        if re.match(r"^[A-Z]{1,6}\s*/?\s*[A-Z]?\s*\d+(?:\.\d+)?\s*[—-]\s*\d{4}$", t):
            return True
        if re.match(r"^\d{1,4}$", t):
            return True
        return False

    # remove matched header/footer lines anywhere in markdown output
    cleaned = [ln for ln in lines if not _is_header_footer_line(ln)]
    s = "\n".join(cleaned).strip()
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s


def _normalize_figure_desc(value: Any) -> str:
    s = str(value or "").strip()
    if not s:
        return ""
    # Handle stringified dict: "{'description': '...'}"
    if s.startswith("{") and s.endswith("}"):
        try:
            obj = ast.literal_eval(s)
            if isinstance(obj, dict):
                d = obj.get("description")
                if d:
                    return str(d).strip()
        except Exception:
            pass
    return s


def _parse_markdown_table_to_array(table_text: str) -> tuple[List[str], List[List[str]]]:
    """
    Parse markdown table into (columns, raw_array).
    - columns: header row
    - raw_array: data rows only
    """
    lines = [ln.strip() for ln in (table_text or "").splitlines() if ln.strip()]
    table_lines = [ln for ln in lines if "|" in ln]
    if not table_lines:
        return [], []

    def _split_row(line: str) -> List[str]:
        row = line.strip()
        if row.startswith("|"):
            row = row[1:]
        if row.endswith("|"):
            row = row[:-1]
        return [c.strip() for c in row.split("|")]

    rows = [_split_row(ln) for ln in table_lines]
    if not rows:
        return [], []

    columns = rows[0]
    data_rows = rows[1:]
    if data_rows:
        sep = data_rows[0]
        # markdown separator row: --- / :---: / ---:
        if all(re.fullmatch(r":?-{3,}:?", (x or "").strip()) for x in sep):
            data_rows = data_rows[1:]

    return columns, data_rows


def _extract_markdown_tables(markdown: str) -> List[str]:
    lines = (markdown or "").splitlines()
    out: List[str] = []
    i = 0
    n = len(lines)
    sep_re = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
    while i < n - 1:
        if "|" in lines[i] and sep_re.match(lines[i + 1] or ""):
            start = i
            j = i + 2
            while j < n and "|" in (lines[j] or ""):
                j += 1
            block = "\n".join([ln.rstrip() for ln in lines[start:j] if ln.strip()]).strip()
            if block:
                out.append(block)
            i = j
            continue
        i += 1
    return out


def _extract_formulas_from_markdown(markdown: str) -> List[str]:
    text = markdown or ""
    found = re.findall(r"\$\$([\s\S]+?)\$\$|\$([^$\n]+)\$", text)
    out: List[str] = []
    seen = set()
    for g1, g2 in found:
        f = (g1 or g2 or "").strip()
        if not f:
            continue
        if f in seen:
            continue
        seen.add(f)
        out.append(f)
    return out


def _extract_figures_from_markdown(markdown: str) -> List[str]:
    text = markdown or ""
    out: List[str] = []
    seen = set()

    for m in re.findall(r"\[FIGURE:\s*([^\]]+)\]", text, flags=re.IGNORECASE):
        t = m.strip()
        if t and t not in seen:
            seen.add(t)
            out.append(t)

    for m in re.findall(r"\*\[(.*?)\]\*", text):
        t = m.strip()
        if t and t not in seen:
            seen.add(t)
            out.append(t)

    return out


def _strip_markdown_tables(markdown: str) -> str:
    text = markdown or ""
    for tbl in _extract_markdown_tables(text):
        text = text.replace(tbl, "")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def _normalize_table_value(value: Any) -> tuple[List[str], List[List[str]], str]:
    """
    Accept table value in multiple forms and normalize to:
    (columns, raw_array, semantic_desc)
    supported:
    - markdown string table
    - dict: {"header":[...], "rows":[...]}
    - stringified dict of above
    """
    if isinstance(value, dict):
        header = value.get("header") or value.get("columns") or []
        rows = value.get("rows") or value.get("raw_array") or []
        columns = [str(x).strip() for x in header if str(x).strip()]
        raw_array = []
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, list):
                raw_array.append([str(x).strip() for x in row])
        semantic_desc = (
            f"表格包含{len(raw_array)}行"
            + (f"，主要列为：{'、'.join(columns[:5])}" if columns else "")
        )
        return columns, raw_array, semantic_desc

    text = str(value or "").strip()
    if not text:
        return [], [], ""

    # stringified dict case
    if text.startswith("{") and text.endswith("}"):
        try:
            obj = ast.literal_eval(text)
            if isinstance(obj, dict):
                return _normalize_table_value(obj)
        except Exception:
            pass

    columns, raw_array = _parse_markdown_table_to_array(text)
    if columns or raw_array:
        semantic_desc = (
            f"表格包含{len(raw_array)}行"
            + (f"，主要列为：{'、'.join(columns[:5])}" if columns else "")
        )
    else:
        semantic_desc = text[:400]
    return columns, raw_array, semantic_desc


def _build_canonical_page_record(
    task_id: str,
    doc_id: str,
    source_page_no: int,
    page_result: Dict[str, Any],
    next_context: Dict[str, Any],
    vlm_meta: Dict[str, Any],
) -> Dict[str, Any]:
    render_markdown = _clean_render_markdown(((page_result.get("render") or {}).get("markdown") or ""))
    rag_obj = page_result.get("rag") or {}
    page_text_raw = str(rag_obj.get("page_text") or "").strip() or _strip_markdown_tables(render_markdown)
    page_text = _clean_page_text_for_rag(page_text_raw)

    section = str((next_context or {}).get("current_section") or "").strip()
    section_path = _normalize_section_path(section)

    elements_block = (rag_obj.get("elements") or {}) if isinstance(rag_obj, dict) else {}
    model_formulas = elements_block.get("formulas") or []
    model_tables = elements_block.get("tables") or []
    model_figures = elements_block.get("figures") or []

    # Canonical RAG reconstruction rule:
    # Prefer deterministic extraction from render markdown; fallback to model rag.elements.
    tables = _extract_markdown_tables(render_markdown) or model_tables
    formulas = _extract_formulas_from_markdown(render_markdown) or model_formulas
    figures = _extract_figures_from_markdown(render_markdown) or model_figures

    flat_elements: List[Dict[str, Any]] = []
    refs: List[str] = []

    for idx, val in enumerate(tables, start=1):
        columns, raw_array, semantic_desc = _normalize_table_value(val)
        if not columns and not raw_array and not semantic_desc:
            continue
        eid = f"p{source_page_no}_t{idx}"
        refs.append(eid)
        flat_elements.append(
            {
                "id": eid,
                "type": "table",
                "anchor": None,
                "columns": columns,
                "raw_array": raw_array,
                "semantic_desc": semantic_desc,
                "keywords": _extract_keywords(" ".join(columns) + " " + semantic_desc),
            }
        )

    for idx, val in enumerate(formulas, start=1):
        text = str(val).strip()
        if not text:
            continue
        eid = f"p{source_page_no}_f{idx}"
        refs.append(eid)
        flat_elements.append(
            {
                "id": eid,
                "type": "formula",
                "anchor": None,
                "latex": text,
                "semantic_desc": text[:280],
                "keywords": _extract_keywords(text),
            }
        )

    for idx, val in enumerate(figures, start=1):
        text = _normalize_figure_desc(val)
        if not text:
            continue
        eid = f"p{source_page_no}_g{idx}"
        refs.append(eid)
        flat_elements.append(
            {
                "id": eid,
                "type": "figure",
                "anchor": None,
                "semantic_desc": text[:400],
                "keywords": _extract_keywords(text),
            }
        )

    return {
        "task_id": task_id,
        "doc_id": doc_id,
        "page_no": source_page_no,
        "section_path": section_path,
        "page_text": page_text,
        "elements": flat_elements,
        # chunks are intentionally not generated here; chunking is client-pipeline responsibility.
        "trace": {
            "source_page_no": source_page_no,
            "source_offsets": [],
            "model": (vlm_meta or {}).get("model"),
            "provider": (vlm_meta or {}).get("provider"),
            "base_url": (vlm_meta or {}).get("base_url"),
        },
    }


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


async def run_task_pages(
    transport,
    task_name,
    pdf_path,
    pages,
    policy,
    merge_mode,
    check_merge,
    full_output,
    output_prefix,
    render_dpi=220,
    debug_layout_probe=False,
):
    start_tool = "pdf2md-enhanced.start_task"
    process_tool = "pdf2md-enhanced.process_task_page"
    finalize_tool = "pdf2md-enhanced.finalize_task"
    status_tool = "pdf2md-enhanced.get_task_status"

    print(f"→ 调用远程工具: {start_tool}")
    start_req_args = {
        "task_name": task_name,
        "file_path": str(pdf_path),
        "pages": pages,
    }
    start_resp = await _call_tool(
        transport,
        start_tool,
        start_req_args,
        req_id=10,
    )
    start_data = _extract_json_from_tool_response(start_resp)

    used_subset_pdf = False
    original_pages = list(pages)
    # Docker/remote MCP often cannot access host local path; use file_data subset transfer for remote execution.
    if start_data and start_data.get("error") and "no such file" in str(start_data.get("error")).lower():
        print("  ℹ️  检测到远程MCP不可访问本地路径，改用 file_data(仅请求页) 传输")
        subset_bytes = extract_pdf_pages(pdf_path, pages)
        subset_b64 = base64.b64encode(subset_bytes).decode("utf-8")
        start_req_args = {
            "task_name": task_name,
            "file_data": subset_b64,
            "pages": list(range(1, len(pages) + 1)),
        }
        start_resp = await _call_tool(transport, start_tool, start_req_args, req_id=11)
        start_data = _extract_json_from_tool_response(start_resp)
        used_subset_pdf = True

    if not start_data or start_data.get("error") or not start_data.get("task_id"):
        print("✗ start_task 失败")
        print(start_data)
        return

    task_id = start_data["task_id"]
    planned_pages = start_data.get("planned_pages", pages)
    print(f"✓ 任务已创建: {task_id}")
    print(f"  planned_pages: {planned_pages}")

    page_outputs = []
    md_file = None
    rag_file = None
    pages_file = None
    if output_prefix:
        out_prefix = Path(output_prefix)
        out_prefix.parent.mkdir(parents=True, exist_ok=True)
        doc_id = Path(pdf_path).stem
        md_file = f"{output_prefix}.md"
        rag_file = f"{output_prefix}.json"
        pages_file = f"{output_prefix}.pages.json"
        # truncate/create
        Path(md_file).write_text("", encoding="utf-8")
        Path(rag_file).write_text("[]", encoding="utf-8")
        Path(pages_file).write_text("[]", encoding="utf-8")
    prev_context = None
    for idx, page_no in enumerate(planned_pages, start=1):
        display_page_no = original_pages[page_no - 1] if used_subset_pdf and 1 <= page_no <= len(original_pages) else page_no
        print(f"\n→ 处理第 {display_page_no} 页 ({idx}/{len(planned_pages)})")
        start_time = time.time()

        process_resp = await _call_tool(
            transport,
            process_tool,
            {
                "task_id": task_id,
                "page_no": page_no,
                "policy": policy,
                "routing_config": {
                    "render_dpi": int(render_dpi),
                    "debug_layout_probe": bool(debug_layout_probe),
                },
                "prev_context": prev_context,
            },
            req_id=1000 + page_no,
        )
        elapsed = time.time() - start_time
        process_data = _extract_json_from_tool_response(process_resp)
        if not process_data or process_data.get("error"):
            print(f"  ✗ page {display_page_no} 失败: {process_data}")
            continue
        if process_data.get("raw_text"):
            raw = str(process_data.get("raw_text", ""))
            print(f"  ✗ page {display_page_no} 非结构化返回: {raw[:220]}")
            continue

        page_result = process_data.get("page_result", {})
        decision = page_result.get("decision", {})
        print(
            f"  ✓ {elapsed:.2f}s mode={decision.get('mode')} "
            f"vlm_calls={decision.get('vlm_calls')} text_chars={((decision.get('metrics') or {}).get('text_chars'))}"
        )

        if not output_prefix:
            render_text = _clean_render_markdown(((page_result.get("render") or {}).get("markdown") or ""))
            rag_text = ((page_result.get("rag") or {}).get("content") or "")
            print("  Render预览(前120):", render_text[:120].replace("\n", " "))
            print("  RAG预览(前120):", rag_text[:120].replace("\n", " "))

        if output_prefix:
            render_text = _clean_render_markdown(((page_result.get("render") or {}).get("markdown") or ""))
            rag_obj = (page_result.get("rag") or {})
            next_ctx = process_data.get("next_context") or {}
            canonical = _build_canonical_page_record(
                task_id=task_id,
                doc_id=doc_id,
                source_page_no=display_page_no,
                page_result=page_result,
                next_context=next_ctx,
                vlm_meta=(process_data.get("vlm") or {}),
            )
            if render_text:
                with open(md_file, "a", encoding="utf-8") as f:
                    f.write(f"{render_text}\n\n")
            # Incremental pretty-json write (rewrite full array each page for readability)
            rag_arr = []
            pages_arr = []
            try:
                rag_arr = json.loads(Path(rag_file).read_text(encoding="utf-8"))
                if not isinstance(rag_arr, list):
                    rag_arr = []
            except Exception:
                rag_arr = []
            try:
                pages_arr = json.loads(Path(pages_file).read_text(encoding="utf-8"))
                if not isinstance(pages_arr, list):
                    pages_arr = []
            except Exception:
                pages_arr = []

            rag_arr.append(canonical)
            pages_arr.append(
                {
                    "task_page_no": page_no,
                    "source_page_no": display_page_no,
                    "result": page_result,
                }
            )
            Path(rag_file).write_text(json.dumps(rag_arr, ensure_ascii=False, indent=2), encoding="utf-8")
            Path(pages_file).write_text(json.dumps(pages_arr, ensure_ascii=False, indent=2), encoding="utf-8")

        page_outputs.append({
            "task_page_no": page_no,
            "source_page_no": display_page_no,
            "result": page_result,
        })
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
        screen_output = not output_prefix  # 只有没有--out参数时才输出到屏幕

        if screen_output:
            print(f"  merged_markdown长度: {len(md)}")

        if full_output:
            if screen_output:
                print("  merged_markdown完整内容:")
                print("-" * 80)
                print(md)
                print("-" * 80)
            if output_prefix:
                md_file = f"{output_prefix}.md"
                with open(md_file, 'w', encoding='utf-8') as f:
                    f.write(md)
                if screen_output:
                    print(f"  ✓ 已保存MD内容到: {md_file}")
        else:
            if screen_output:
                print("  merged_markdown预览(前300):")
                print("-" * 80)
                print(md[:300])
                print("-" * 80)

    if merge_mode in {"rag", "both"}:
        rag = finalize_data.get("merged_rag") or []
        screen_output = not output_prefix  # 只有没有--out参数时才输出到屏幕

        if screen_output:
            print(f"  merged_rag条数: {len(rag)}")

        if full_output:
            if screen_output:
                print("  merged_rag完整内容:")
                print("-" * 80)
                print(json.dumps(rag, ensure_ascii=False, indent=2))
                print("-" * 80)
            if output_prefix:
                rag_file = f"{output_prefix}.json"
                with open(rag_file, 'w', encoding='utf-8') as f:
                    json.dump(rag, f, ensure_ascii=False, indent=2)
                if screen_output:
                    print(f"  ✓ 已保存RAG内容到: {rag_file}")

    if output_prefix:
        print(f"✓ 已按页增量保存输出文件: {output_prefix}.md / {output_prefix}.json / {output_prefix}.pages.json")

    if check_merge:
        ok, issues = validate_merge(finalize_data, merge_mode)
        if ok:
            print("✓ 合并逻辑校验通过")
        else:
            print("✗ 合并逻辑校验失败")
            for item in issues:
                print(f"  - {item}")


async def test_pdf2md_enhanced_mcp(
    jwt_token,
    page_num=None,
    pages=None,
    test_document=False,
    pdf_path=None,
    policy="auto",
    merge_mode="none",
    check_merge=False,
    full_output=False,
    output_prefix=None,
    render_dpi=220,
    debug_layout_probe=False,
):
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
    print(f"render_dpi: {render_dpi}")
    print(f"debug_layout_probe: {debug_layout_probe}")
    print()

    if not pdf_path.exists():
        print(f"✗ PDF文件不存在: {pdf_path}")
        return

    ws_url = f"{MCP_ROUTER_URL}?token={jwt_token}"
    try:
        # 增加消息大小限制到20MB，支持单页PDF传输
        async with websockets.connect(ws_url, max_size=20*1024*1024, ping_timeout=300, close_timeout=10) as websocket:
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

            total_pages = get_pdf_total_pages(pdf_path)

            if page_num:
                target_pages = [page_num]
            elif test_document:
                target_pages = list(range(1, total_pages + 1))
            elif pages:
                target_pages = [p for p in pages if 1 <= p <= total_pages]
            else:
                target_pages = [1]

            await run_task_pages(
                transport=transport,
                task_name=f"multi-page-{int(time.time())}",
                pdf_path=pdf_path,
                pages=target_pages,
                policy=policy,
                merge_mode=merge_mode,
                check_merge=check_merge,
                full_output=full_output,
                output_prefix=output_prefix,
                render_dpi=render_dpi,
                debug_layout_probe=debug_layout_probe,
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
  %(prog)s --document --merge-mode markdown
  %(prog)s --pages 1-5 --check-merge
  %(prog)s --pages 1,2,3 --full --out result
  %(prog)s --document --full --out output
        '''
    )

    parser.add_argument('--page', type=int, help='测试指定页码')
    parser.add_argument('--pages', type=str, help='测试多个页码 (例: 1,2,3 或 1-5)')
    parser.add_argument('--document', action='store_true', help='测试文档级处理(全页)')
    parser.add_argument('--pdf-path', type=str, default=None, help='PDF文件路径')

    parser.add_argument('--policy', type=str, default='auto', choices=['auto', 'force_direct', 'force_vlm'], help='页处理策略')
    parser.add_argument('--render-dpi', type=int, default=220, help='渲染页图DPI（默认220，建议220-300）')
    parser.add_argument('--debug-layout-probe', action='store_true', help='仅测试：启用recognize_layout探针并回传到decision.layout_probe')
    parser.add_argument('--merge-mode', type=str, default='none', choices=['none', 'markdown', 'rag', 'both'], help='finalize合并模式（默认none，由client端拼接）')
    parser.add_argument('--check-merge', action='store_true', help='启用多页合并逻辑校验')
    parser.add_argument('--full', action='store_true', help='输出完整结果，而不是预览')
    parser.add_argument('--out', type=str, help='输出文件前缀（MD输出到{prefix}.md，RAG输出到{prefix}.json），设置此参数将不输出到屏幕')

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
            full_output=args.full,
            output_prefix=args.out,
            render_dpi=args.render_dpi,
            debug_layout_probe=args.debug_layout_probe,
        )

    asyncio.run(run_with_connection_check())


if __name__ == '__main__':
    main()
