from __future__ import annotations

import asyncio
import json
import os
import logging
from typing import Any, Dict, List, Optional

from fastmcp import FastMCP

from .page_processor import process_page
from .task_manager import TaskManager


OUTPUT_DIR = os.getenv("PDF2MD_ENH_OUTPUT_DIR", "./data/output")
PAGE_TIMEOUT_SEC = int(os.getenv("PDF2MD_ENH_PAGE_TIMEOUT_SEC", "280"))
VLM_CALL_TIMEOUT_CAP_SEC = int(os.getenv("PDF2MD_ENH_VLM_CALL_TIMEOUT_CAP_SEC", "90"))
VLM_MAX_RETRIES_CAP = int(os.getenv("PDF2MD_ENH_VLM_MAX_RETRIES_CAP", "0"))
logger = logging.getLogger(__name__)

mcp = FastMCP(name="pdf2md-enhanced", mask_error_details=True)
manager = TaskManager(output_dir=OUTPUT_DIR)


@mcp.tool("health_check")
async def health_check() -> str:
    return json.dumps({"ok": True, "service": "pdf2md-enhanced", "version": "0.1.0"}, ensure_ascii=False)


@mcp.tool("start_task")
async def start_task(
    task_name: str,
    file_path: Optional[str] = None,
    file_data: Optional[str] = None,
    pages: Optional[List[int]] = None,
    routing_config: Optional[Dict[str, Any]] = None,
    vlm_defaults: Optional[Dict[str, Any]] = None,
) -> str:
    _ = routing_config
    loop = asyncio.get_event_loop()
    try:
        task = await loop.run_in_executor(None, manager.start_task, task_name, file_path, file_data, pages)
        res = {
            "task_id": task.task_id,
            "task_name": task.task_name,
            "total_pages": task.total_pages,
            "planned_pages": task.planned_pages,
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
    policy: str = "auto",
    prev_context: Optional[Dict[str, Any]] = None,
    routing_config: Optional[Dict[str, Any]] = None,
) -> str:
    loop = asyncio.get_event_loop()
    effective_vlm_config = _normalize_vlm_config(vlm_config)
    vlm_used = _vlm_runtime_info(effective_vlm_config)
    try:
        await loop.run_in_executor(None, manager.update_page_running, task_id, page_no)

        task = manager.get_task(task_id)
        effective_routing_config = dict(routing_config or {})
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
            timeout=PAGE_TIMEOUT_SEC,
        )
        await loop.run_in_executor(None, manager.update_page_result, task_id, page_no, result)
        res = {
            "task_id": task_id,
            "page_no": page_no,
            "page_result": result,
            "next_context": result.get("next_context"),
            "vlm": vlm_used,
        }
    except asyncio.TimeoutError:
        msg = f"process_task_page timeout after {PAGE_TIMEOUT_SEC}s"
        await loop.run_in_executor(None, manager.update_page_failed, task_id, page_no, msg)
        logger.warning("process_task_page timeout: task_id=%s page_no=%s", task_id, page_no)
        res = {"task_id": task_id, "page_no": page_no, "error": msg, "vlm": vlm_used}
    except Exception as exc:
        await loop.run_in_executor(None, manager.update_page_failed, task_id, page_no, str(exc))
        logger.exception("process_task_page failed: task_id=%s page_no=%s", task_id, page_no)
        res = {"task_id": task_id, "page_no": page_no, "error": str(exc), "vlm": vlm_used}
    return json.dumps(res, ensure_ascii=False)


def _vlm_runtime_info(cfg: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    c = cfg or {}
    return {
        "provider": c.get("provider"),
        "model": c.get("model"),
        "base_url": c.get("base_url"),
    }


def _normalize_vlm_config(cfg: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not cfg:
        return cfg

    c = dict(cfg)
    raw_timeout = c.get("timeout_sec", 60)
    raw_retries = c.get("max_retries", 2)
    try:
        timeout_sec = int(raw_timeout)
    except Exception:
        timeout_sec = 60
    try:
        max_retries = int(raw_retries)
    except Exception:
        max_retries = 2

    # Avoid conflicting budgets: per-call timeout/retries must fit page timeout.
    timeout_cap = max(20, min(VLM_CALL_TIMEOUT_CAP_SEC, max(20, PAGE_TIMEOUT_SEC // 3)))
    c["timeout_sec"] = min(timeout_sec, timeout_cap)
    c["max_retries"] = max(0, min(max_retries, VLM_MAX_RETRIES_CAP))
    return c


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
