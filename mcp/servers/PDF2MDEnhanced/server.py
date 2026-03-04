from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, List, Optional

from fastmcp import FastMCP

from .page_processor import process_page
from .task_manager import TaskManager


OUTPUT_DIR = os.getenv("PDF2MD_ENH_OUTPUT_DIR", "./data/output")

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
    _ = vlm_defaults
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
    try:
        await loop.run_in_executor(None, manager.update_page_running, task_id, page_no)

        task = manager.get_task(task_id)
        result = await loop.run_in_executor(
            None,
            process_page,
            task.source_path,
            page_no,
            policy,
            vlm_config,
            routing_config,
            prev_context,
        )
        await loop.run_in_executor(None, manager.update_page_result, task_id, page_no, result)
        res = {"task_id": task_id, "page_no": page_no, "page_result": result, "next_context": result.get("next_context")}
    except Exception as exc:
        await loop.run_in_executor(None, manager.update_page_failed, task_id, page_no, str(exc))
        res = {"task_id": task_id, "page_no": page_no, "error": str(exc)}
    return json.dumps(res, ensure_ascii=False)


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
