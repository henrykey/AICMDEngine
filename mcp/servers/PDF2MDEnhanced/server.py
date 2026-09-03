from __future__ import annotations

import asyncio
import json
import os
import logging
from typing import Any, Dict, List, Optional

from fastmcp import FastMCP

from .page_processor import process_page
from .single_page_tools import (
    analyze_page_layout_direct,
    extract_page_figures_direct,
    extract_page_formulas_direct,
    extract_page_layout_enhanced_direct,
    extract_page_structured_direct,
    extract_page_tables_direct,
    revise_page_markdown_direct,
)
from .task_manager import TaskManager


OUTPUT_DIR = os.getenv("PDF2MD_ENH_OUTPUT_DIR", "./data/output")
PAGE_TIMEOUT_SEC = int(os.getenv("PDF2MD_ENH_PAGE_TIMEOUT_SEC", "600"))
VLM_CALL_TIMEOUT_CAP_SEC = int(os.getenv("PDF2MD_ENH_VLM_CALL_TIMEOUT_CAP_SEC", "600"))
PAGE_TIMEOUT_GUARD_SEC = int(os.getenv("PDF2MD_ENH_PAGE_TIMEOUT_GUARD_SEC", "20"))
VLM_MAX_RETRIES_CAP = int(os.getenv("PDF2MD_ENH_VLM_MAX_RETRIES_CAP", "0"))
VLM_MAX_TOKENS_CAP = int(os.getenv("PDF2MD_ENH_VLM_MAX_TOKENS_CAP", "16384"))
logger = logging.getLogger(__name__)

mcp = FastMCP(name="pdf2md-enhanced", mask_error_details=True)
manager = TaskManager(output_dir=OUTPUT_DIR)


@mcp.tool("health_check")
async def health_check() -> str:
    return json.dumps({"ok": True, "service": "pdf2md-enhanced", "version": "0.2.0"}, ensure_ascii=False)


@mcp.tool("start_task")
async def start_task(
    task_name: str,
    file_path: Optional[str] = None,
    file_data: Optional[str] = None,
    file_url: Optional[str] = None,
    s3_bucket: Optional[str] = None,
    s3_key: Optional[str] = None,
    storage_config: Optional[Dict[str, Any]] = None,
    pages: Optional[List[int]] = None,
    description_language: str = "unknown",
    routing_config: Optional[Dict[str, Any]] = None,
    ocr_config: Optional[Dict[str, Any]] = None,
    vlm_defaults: Optional[Dict[str, Any]] = None,
) -> str:
    _ = routing_config
    _ = ocr_config
    loop = asyncio.get_event_loop()
    try:
        task = await loop.run_in_executor(
            None,
            lambda: manager.start_task(
                task_name=task_name,
                file_path=file_path,
                file_data=file_data,
                file_url=file_url,
                s3_bucket=s3_bucket,
                s3_key=s3_key,
                storage_config=storage_config,
                pages=pages,
                description_language=description_language,
            ),
        )
        res = {
            "task_id": task.task_id,
            "task_name": task.task_name,
            "total_pages": task.total_pages,
            "planned_pages": task.planned_pages,
            "source_type": task.source_type,
            "source_ref": task.source_ref,
            "source_size_bytes": task.source_size_bytes,
            "source_sha1": task.source_sha1,
            "created_at": task.created_at,
        }
    except Exception as exc:
        res = {"error": str(exc)}
    return json.dumps(res, ensure_ascii=False)


@mcp.tool("process_task_page")
async def process_task_page(
    task_id: str,
    page_no: int,
    vlm_config: Optional[Dict[str, Any]] = None,
    ocr_config: Optional[Dict[str, Any]] = None,
    policy: str = "auto",
    prev_context: Optional[Dict[str, Any]] = None,
    description_language: str = "unknown",
    routing_config: Optional[Dict[str, Any]] = None,
) -> str:
    loop = asyncio.get_event_loop()
    effective_routing_config = dict(routing_config or {})
    if ocr_config:
        effective_routing_config["ocr_config"] = ocr_config
    ocr_vlm_config = ((ocr_config or {}).get("vlm_ocr") or {}) if isinstance(ocr_config, dict) else {}
    effective_vlm_config = _normalize_vlm_config(vlm_config or (ocr_vlm_config if ocr_vlm_config.get("enabled", True) else None))
    vlm_used = _vlm_runtime_info(effective_vlm_config)
    page_timeout_sec = _resolve_page_timeout(effective_vlm_config)
    try:
        await loop.run_in_executor(None, manager.update_page_running, task_id, page_no)

        task = manager.get_task(task_id)
        effective_description_language = _known_description_language(description_language)
        if effective_description_language == "unknown":
            effective_description_language = _known_description_language(task.description_language)
        effective_routing_config["description_language"] = effective_description_language
        # Internal context for page processor policy decisions.
        effective_routing_config["__task_total_pages"] = len(task.planned_pages)
        result = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                process_page,
                task.source_path,
                page_no,
                policy,
                effective_vlm_config,
                effective_routing_config,
                prev_context,
            ),
            timeout=page_timeout_sec,
        )
        await loop.run_in_executor(None, manager.update_page_result, task_id, page_no, result)
        res = {
            "task_id": task_id,
            "page_no": page_no,
            "page_result": result,
            "next_context": result.get("next_context"),
            "route_selected": result.get("route_selected"),
            "bad_text_detected": result.get("bad_text_detected"),
            "bad_text_reasons": result.get("bad_text_reasons"),
            "text_quality_summary": result.get("text_quality_summary"),
            "vlm": vlm_used,
        }
    except asyncio.TimeoutError:
        msg = f"process_task_page timeout after {page_timeout_sec}s"
        await loop.run_in_executor(None, manager.update_page_failed, task_id, page_no, msg)
        logger.warning(
            "process_task_page timeout: task_id=%s page_no=%s timeout=%ss",
            task_id,
            page_no,
            page_timeout_sec,
        )
        res = {"task_id": task_id, "page_no": page_no, "error": msg, "vlm": vlm_used}
    except Exception as exc:
        await loop.run_in_executor(None, manager.update_page_failed, task_id, page_no, str(exc))
        logger.exception("process_task_page failed: task_id=%s page_no=%s", task_id, page_no)
        res = {"task_id": task_id, "page_no": page_no, "error": str(exc), "vlm": vlm_used}
    return json.dumps(res, ensure_ascii=False)


@mcp.tool("extract_page_tables")
async def extract_page_tables(
    file_path: Optional[str] = None,
    file_data: Optional[str] = None,
    file_url: Optional[str] = None,
    page_no: int = 1,
    input_type: str = "auto",
    output_format: str = "json",
    describe: bool = True,
    table_rows_format: str = "structured_json",
    description_language: str = "unknown",
    ocr_config: Optional[Dict[str, Any]] = None,
    vlm_config: Optional[Dict[str, Any]] = None,
    routing_config: Optional[Dict[str, Any]] = None,
) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: extract_page_tables_direct(
            file_path=file_path,
            file_data=file_data,
            file_url=file_url,
            page_no=page_no,
            input_type=input_type,
            output_format=output_format,
            describe=describe,
            table_rows_format=table_rows_format,
            description_language=description_language,
            ocr_config=ocr_config,
            vlm_config=_normalize_vlm_config(vlm_config),
            routing_config=routing_config,
        ),
    )


@mcp.tool("analyze_page_layout")
async def analyze_page_layout(
    file_path: Optional[str] = None,
    file_data: Optional[str] = None,
    file_url: Optional[str] = None,
    page_no: int = 1,
    input_type: str = "auto",
    output_format: str = "json",
    ocr_config: Optional[Dict[str, Any]] = None,
    routing_config: Optional[Dict[str, Any]] = None,
    return_crop_images: bool = False,
    need_layout_visualization: bool = False,
) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: analyze_page_layout_direct(
            file_path=file_path,
            file_data=file_data,
            file_url=file_url,
            page_no=page_no,
            input_type=input_type,
            output_format=output_format,
            ocr_config=ocr_config,
            routing_config=routing_config,
            return_crop_images=return_crop_images,
            need_layout_visualization=need_layout_visualization,
        ),
    )


@mcp.tool("extract_page_formulas")
async def extract_page_formulas(
    file_path: Optional[str] = None,
    file_data: Optional[str] = None,
    file_url: Optional[str] = None,
    page_no: int = 1,
    input_type: str = "auto",
    output_format: str = "json",
    describe: bool = True,
    description_language: str = "unknown",
    ocr_config: Optional[Dict[str, Any]] = None,
    vlm_config: Optional[Dict[str, Any]] = None,
    routing_config: Optional[Dict[str, Any]] = None,
) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: extract_page_formulas_direct(
            file_path=file_path,
            file_data=file_data,
            file_url=file_url,
            page_no=page_no,
            input_type=input_type,
            output_format=output_format,
            describe=describe,
            description_language=description_language,
            ocr_config=ocr_config,
            vlm_config=_normalize_vlm_config(vlm_config),
            routing_config=routing_config,
        ),
    )


@mcp.tool("extract_page_layout_enhanced")
async def extract_page_layout_enhanced(
    file_path: Optional[str] = None,
    file_data: Optional[str] = None,
    file_url: Optional[str] = None,
    page_no: int = 1,
    input_type: str = "auto",
    output_format: str = "json",
    ocr_config: Optional[Dict[str, Any]] = None,
    vlm_config: Optional[Dict[str, Any]] = None,
    routing_config: Optional[Dict[str, Any]] = None,
) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: extract_page_layout_enhanced_direct(
            file_path=file_path,
            file_data=file_data,
            file_url=file_url,
            page_no=page_no,
            input_type=input_type,
            output_format=output_format,
            ocr_config=ocr_config,
            vlm_config=_normalize_vlm_config(vlm_config),
            routing_config=routing_config,
        ),
    )


@mcp.tool("extract_page_figures")
async def extract_page_figures(
    file_path: Optional[str] = None,
    file_data: Optional[str] = None,
    file_url: Optional[str] = None,
    page_no: int = 1,
    input_type: str = "auto",
    output_format: str = "json",
    describe: bool = True,
    description_language: str = "unknown",
    ocr_config: Optional[Dict[str, Any]] = None,
    vlm_config: Optional[Dict[str, Any]] = None,
    routing_config: Optional[Dict[str, Any]] = None,
) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: extract_page_figures_direct(
            file_path=file_path,
            file_data=file_data,
            file_url=file_url,
            page_no=page_no,
            input_type=input_type,
            output_format=output_format,
            describe=describe,
            description_language=description_language,
            ocr_config=ocr_config,
            vlm_config=_normalize_vlm_config(vlm_config),
            routing_config=routing_config,
        ),
    )


@mcp.tool("extract_page_structured")
async def extract_page_structured(
    file_path: Optional[str] = None,
    file_data: Optional[str] = None,
    file_url: Optional[str] = None,
    page_no: int = 1,
    input_type: str = "auto",
    output_format: str = "json",
    describe: bool = True,
    description_language: str = "unknown",
    ocr_config: Optional[Dict[str, Any]] = None,
    vlm_config: Optional[Dict[str, Any]] = None,
    routing_config: Optional[Dict[str, Any]] = None,
) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: extract_page_structured_direct(
            file_path=file_path,
            file_data=file_data,
            file_url=file_url,
            page_no=page_no,
            input_type=input_type,
            output_format=output_format,
            describe=describe,
            description_language=description_language,
            ocr_config=ocr_config,
            vlm_config=_normalize_vlm_config(vlm_config),
            routing_config=routing_config,
        ),
    )


@mcp.tool("revise_page_markdown")
async def revise_page_markdown(
    file_data: Optional[str] = None,
    file_path: Optional[str] = None,
    file_url: Optional[str] = None,
    content_type: str = "image/png",
    filename: Optional[str] = None,
    page_no: int = 1,
    prompt: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    output_target: str = "page_text",
    output_format: str = "markdown",
    vlm_config: Optional[Dict[str, Any]] = None,
    routing_config: Optional[Dict[str, Any]] = None,
) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: revise_page_markdown_direct(
            file_data=file_data,
            file_path=file_path,
            file_url=file_url,
            content_type=content_type,
            filename=filename,
            page_no=page_no,
            prompt=prompt,
            context=context,
            output_target=output_target,
            output_format=output_format,
            vlm_config=_normalize_vlm_config(vlm_config),
            routing_config=routing_config,
        ),
    )


def _vlm_runtime_info(cfg: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    c = cfg or {}
    return {
        "provider": c.get("provider"),
        "model": c.get("model"),
        "base_url": c.get("base_url"),
        "max_tokens": c.get("max_tokens"),
        "context_window": c.get("context_window"),
        "dual_output_max_tokens": c.get("dual_output_max_tokens"),
    }


def _known_description_language(value: Any) -> str:
    language = str(value or "").strip().lower()
    if language in {"zh", "zh-cn", "zh_hans", "chinese"}:
        return "zh"
    if language in {"en", "en-us", "english"}:
        return "en"
    return "unknown"


def _normalize_vlm_config(cfg: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not cfg:
        return cfg

    c = dict(cfg)
    raw_timeout = c.get("timeout_sec", 60)
    raw_retries = c.get("max_retries", 2)
    raw_max_tokens = c.get("max_tokens", 4096)
    try:
        timeout_sec = int(raw_timeout)
    except Exception:
        timeout_sec = 60
    try:
        max_retries = int(raw_retries)
    except Exception:
        max_retries = 2
    try:
        max_tokens = int(raw_max_tokens)
    except Exception:
        max_tokens = 4096

    # Default behavior: honor provider-injected timeout_sec.
    # Optional cap still available via env; non-positive cap means "disabled".
    timeout_cap = int(VLM_CALL_TIMEOUT_CAP_SEC)
    if timeout_cap > 0:
        c["timeout_sec"] = max(20, min(timeout_sec, timeout_cap))
    else:
        c["timeout_sec"] = max(20, timeout_sec)
    c["max_retries"] = max(0, min(max_retries, VLM_MAX_RETRIES_CAP))
    c["max_tokens"] = max(512, min(max_tokens, VLM_MAX_TOKENS_CAP))
    return c


def _resolve_page_timeout(cfg: Optional[Dict[str, Any]]) -> int:
    """
    Ensure page timeout is never smaller than VLM timeout budget.
    Effective timeout = max(static PAGE_TIMEOUT_SEC, vlm.timeout_sec + guard).
    """
    c = cfg or {}
    raw_vlm_timeout = c.get("timeout_sec", 60)
    try:
        vlm_timeout = int(raw_vlm_timeout)
    except Exception:
        vlm_timeout = 60
    vlm_timeout = max(20, vlm_timeout)
    guard = max(5, int(PAGE_TIMEOUT_GUARD_SEC))
    return max(int(PAGE_TIMEOUT_SEC), vlm_timeout + guard)


@mcp.tool("get_task_status")
async def get_task_status(task_id: str) -> str:
    loop = asyncio.get_event_loop()
    try:
        res = await loop.run_in_executor(None, manager.status, task_id)
    except Exception as exc:
        res = {"error": str(exc)}
    return json.dumps(res, ensure_ascii=False)


@mcp.tool("retry_failed_pages")
async def retry_failed_pages(task_id: str, pages: Optional[List[int]] = None) -> str:
    loop = asyncio.get_event_loop()
    try:
        res = await loop.run_in_executor(None, manager.retry_failed_pages, task_id, pages)
    except Exception as exc:
        res = {"error": str(exc)}
    return json.dumps(res, ensure_ascii=False)


@mcp.tool("finalize_task")
async def finalize_task(task_id: str, merge_mode: str = "none") -> str:
    loop = asyncio.get_event_loop()
    try:
        res = await loop.run_in_executor(None, manager.finalize_task, task_id, merge_mode)
    except Exception as exc:
        res = {"error": str(exc)}
    return json.dumps(res, ensure_ascii=False)
