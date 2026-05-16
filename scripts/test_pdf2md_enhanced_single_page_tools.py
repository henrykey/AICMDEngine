#!/usr/bin/env python3
"""
Smoke-test PDF2MD Enhanced single-page extraction tools with a real file.

Examples:
  python scripts/test_pdf2md_enhanced_single_page_tools.py --input /path/to/page.pdf --page 1
  python scripts/test_pdf2md_enhanced_single_page_tools.py --input /path/to/page.png --input-type image
  python scripts/test_pdf2md_enhanced_single_page_tools.py --input /path/to/doc.pdf --page 12 --provider ZAI-OCR
  python scripts/test_pdf2md_enhanced_single_page_tools.py --input /path/to/page.pdf --tool all

By default the script:
  1. reads provider config from mcp-router /api/llm/providers/{provider}
  2. calls pdf2md-enhanced directly through FastMCP streamable HTTP
  3. passes the input as base64 file_data, so container file paths are irrelevant
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_MCP_URL = "http://localhost:9010/mcp"
DEFAULT_ROUTER_URL = "http://localhost:8000"
DEFAULT_PROVIDER = "ZAI-OCR"
TOOL_NAMES = {
    "layout": "analyze_page_layout",
    "enhanced": "extract_page_layout_enhanced",
    "tables": "extract_page_tables",
    "formulas": "extract_page_formulas",
    "figures": "extract_page_figures",
    "structured": "extract_page_structured",
}


def _read_json(url: str, timeout: int = 30) -> Dict[str, Any]:
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GET {url} failed: HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"GET {url} failed: {exc}") from exc
    return json.loads(raw)


def _resolve_api_key(api_key_ref: str, explicit_api_key: Optional[str]) -> str:
    if explicit_api_key:
        return explicit_api_key
    if api_key_ref and api_key_ref.replace("_", "").isalnum():
        env_value = os.environ.get(api_key_ref)
        if env_value:
            return env_value
    if api_key_ref and len(api_key_ref) > 10:
        return api_key_ref
    raise RuntimeError(
        "Could not resolve provider API key. Pass --api-key, set the env var named by api_key_ref, "
        "or store a direct key in the provider config."
    )


def _build_ocr_config(args: argparse.Namespace) -> Dict[str, Any]:
    if args.ocr_config:
        with open(args.ocr_config, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        glm = cfg.get("glm_ocr") if isinstance(cfg, dict) else {}
        cfg_timeout = int((glm or {}).get("timeout_sec") or args.http_timeout)
        args.effective_timeout = int(args.timeout or cfg_timeout)
        return cfg

    if args.provider_config:
        with open(args.provider_config, "r", encoding="utf-8") as f:
            provider = json.load(f)
    else:
        router = args.router_url.rstrip("/")
        provider = _read_json(f"{router}/api/llm/providers/{args.provider}", timeout=args.http_timeout)

    api_key = _resolve_api_key(str(provider.get("api_key_ref") or ""), args.api_key)
    provider_timeout = int(provider.get("timeout") or args.http_timeout)
    args.effective_timeout = int(args.timeout or provider_timeout)
    glm_ocr = {
        "enabled": True,
        "provider": provider.get("name") or args.provider,
        "base_url": provider.get("base_url"),
        "model": provider.get("model") or "glm-ocr",
        "api_key": api_key,
        "timeout_sec": provider_timeout,
        "max_tokens": int(provider.get("max_tokens") or 4096),
        "temperature": float(provider.get("temperature") or 0),
        "max_retries": int(args.max_retries),
    }
    if not glm_ocr["base_url"]:
        raise RuntimeError("Provider config does not include base_url")
    return {"glm_ocr": glm_ocr}


def _encode_file(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"input file not found: {path}")
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _parse_tool_text(result: Any) -> str:
    content = getattr(result, "content", None)
    if isinstance(content, list):
        parts = []
        for item in content:
            text = getattr(item, "text", None)
            if text is None and isinstance(item, dict):
                text = item.get("text")
            if text is not None:
                parts.append(str(text))
        if parts:
            return "\n".join(parts)
    if isinstance(result, str):
        return result
    return str(result)


async def _call_direct_mcp(args: argparse.Namespace, tool_name: str, payload: Dict[str, Any]) -> str:
    from fastmcp import Client

    async with Client(args.mcp_url, timeout=args.effective_timeout, init_timeout=args.http_timeout) as client:
        result = await client.call_tool(tool_name, payload, timeout=args.effective_timeout)
    return _parse_tool_text(result)


def _post_json(url: str, payload: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"POST {url} failed: HTTP {exc.code}: {body}") from exc
    return json.loads(raw)


async def _call_router(args: argparse.Namespace, tool_name: str, payload: Dict[str, Any]) -> str:
    router = args.router_url.rstrip("/")
    urls = [
        f"{router}/v1/mcp/servers/pdf2md-enhanced/tools/{tool_name}/execute",
        f"{router}/v1/mcp/servers/pdf2md-enhanced/tools/{tool_name}",
    ]
    last_error = None
    for url in urls:
        try:
            response = _post_json(url, payload, timeout=args.effective_timeout)
            break
        except RuntimeError as exc:
            last_error = exc
    else:
        raise last_error or RuntimeError("router call failed")

    if "result" in response:
        content = response["result"].get("content") or []
        if content and isinstance(content[0], dict):
            return str(content[0].get("text") or "")
    if "content" in response:
        return str(response.get("content") or "")
    return json.dumps(response, ensure_ascii=False, indent=2)


def _print_items_summary(items: list[Dict[str, Any]], label: str = "items") -> None:
    print(f"{label}: {len(items)}")
    for i, item in enumerate(items, 1):
        markdown = str(item.get("markdown") or item.get("latex") or item.get("description") or "")
        print(f"{label}[{i}].source: {item.get('source')}")
        print(f"{label}[{i}].preview: {markdown[:300]}")


def _print_summary(tool_key: str, text: str) -> None:
    try:
        data = json.loads(text)
    except Exception:
        print(text)
        return

    print(json.dumps(data, ensure_ascii=False, indent=2))
    print("\n--- summary ---")
    print(f"tool: {data.get('tool')}")
    print(f"model_calls: {data.get('model_calls')}")
    warnings = data.get("warnings") or []
    if warnings:
        print(f"warnings: {warnings}")
    if tool_key == "structured":
        _print_items_summary(data.get("tables") or [], "tables")
        _print_items_summary(data.get("formulas") or [], "formulas")
        _print_items_summary(data.get("figures") or [], "figures")
        print(f"semantic_status: {data.get('semantic_status')}")
    elif tool_key in {"layout", "enhanced"}:
        summary = data.get("summary") or {}
        print(f"recommended_tool: {summary.get('recommended_tool')}")
        print(f"dominant_type: {summary.get('dominant_type')}")
        print(f"block_counts: {summary.get('block_counts')}")
        print(f"blocks: {len(data.get('blocks') or [])}")
        if tool_key == "enhanced":
            print(f"tables: {len(data.get('tables') or [])}")
            print(f"formulas: {len(data.get('formulas') or [])}")
            print(f"figures: {len(data.get('figures') or [])}")
    else:
        _print_items_summary(data.get("items") or [], "items")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test pdf2md-enhanced single-page extraction tools")
    parser.add_argument("--input", required=True, help="Path to a single-page image or PDF/document PDF")
    parser.add_argument(
        "--tool",
        choices=["layout", "enhanced", "tables", "formulas", "figures", "structured", "all"],
        default="tables",
        help="Tool to test. Default starts with tables.",
    )
    parser.add_argument("--page", type=int, default=1, help="PDF page number; ignored for images")
    parser.add_argument("--input-type", choices=["auto", "pdf", "image"], default="auto")
    parser.add_argument("--output-format", choices=["json", "markdown"], default="json")
    parser.add_argument("--describe", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--provider", default=DEFAULT_PROVIDER, help="LLM provider name to read from mcp-router")
    parser.add_argument("--router-url", default=DEFAULT_ROUTER_URL)
    parser.add_argument("--mcp-url", default=DEFAULT_MCP_URL, help="Direct pdf2md-enhanced MCP streamable HTTP URL")
    parser.add_argument("--via", choices=["direct", "router"], default="direct")
    parser.add_argument("--api-key", default=None, help="Override provider API key")
    parser.add_argument("--provider-config", default=None, help="JSON file with provider config")
    parser.add_argument("--ocr-config", default=None, help="JSON file with full ocr_config")
    parser.add_argument("--timeout", type=int, default=None, help="Override call timeout. Defaults to provider timeout.")
    parser.add_argument("--http-timeout", type=int, default=30, help="Timeout for short config/API setup calls.")
    parser.add_argument("--max-retries", type=int, default=0)
    parser.add_argument("--render-dpi", type=int, default=220)
    parser.add_argument("--output", default=None, help="Optional output file for raw tool response text")
    return parser.parse_args()


async def async_main() -> int:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    ocr_config = _build_ocr_config(args)
    payload = {
        "file_data": _encode_file(input_path),
        "page_no": args.page,
        "input_type": args.input_type,
        "output_format": args.output_format,
        "ocr_config": ocr_config,
        "routing_config": {"render_dpi": args.render_dpi},
    }

    tool_keys = list(TOOL_NAMES.keys()) if args.tool == "all" else [args.tool]
    outputs: Dict[str, str] = {}
    for tool_key in tool_keys:
        tool_name = TOOL_NAMES[tool_key]
        print(f"\n=== {tool_name} ===")
        call_payload = dict(payload)
        if tool_key not in {"layout", "enhanced"}:
            call_payload["describe"] = args.describe
        if args.via == "router":
            text = await _call_router(args, tool_name, call_payload)
        else:
            text = await _call_direct_mcp(args, tool_name, call_payload)
        outputs[tool_key] = text
        _print_summary(tool_key, text)

    if args.output:
        out_path = Path(args.output).expanduser()
        if len(outputs) == 1:
            out_path.write_text(next(iter(outputs.values())), encoding="utf-8")
        else:
            out_path.write_text(json.dumps(outputs, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def main() -> int:
    try:
        return asyncio.run(async_main())
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
