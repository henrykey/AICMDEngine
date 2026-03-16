from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import fitz

from .models import PageRecord, TaskRecord, now_iso


class TaskManager:
    def __init__(self, output_dir: str) -> None:
        self._tasks: Dict[str, TaskRecord] = {}
        self._root = Path(output_dir).expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def start_task(
        self,
        task_name: str,
        file_path: Optional[str] = None,
        file_data: Optional[str] = None,
        pages: Optional[List[int]] = None,
    ) -> TaskRecord:
        if not file_path and not file_data:
            raise ValueError("file_path or file_data is required")
        if file_path and file_data:
            raise ValueError("file_path and file_data cannot both be provided")

        if file_data:
            source_path = self._save_base64_pdf(file_data, task_name)
        else:
            source_path = str(Path(file_path).expanduser().resolve())

        doc = fitz.open(source_path)
        total_pages = len(doc)
        doc.close()

        if pages is None:
            planned_pages = list(range(1, total_pages + 1))
        else:
            planned_pages = sorted(set([p for p in pages if isinstance(p, int) and 1 <= p <= total_pages]))
            if not planned_pages:
                raise ValueError("pages is empty or out of range")

        task_id = self._new_task_id(task_name, source_path)
        task = TaskRecord(
            task_id=task_id,
            task_name=task_name,
            source_path=source_path,
            total_pages=total_pages,
            planned_pages=planned_pages,
        )
        for p in planned_pages:
            task.pages[p] = PageRecord(page_no=p)

        self._tasks[task_id] = task
        self._persist_task(task)
        return task

    def get_task(self, task_id: str) -> TaskRecord:
        task = self._tasks.get(task_id)
        if not task:
            raise KeyError(f"task not found: {task_id}")
        return task

    def update_page_running(self, task_id: str, page_no: int) -> TaskRecord:
        task = self.get_task(task_id)
        page = self._get_page(task, page_no)
        page.status = "EXTRACTING"
        page.attempts += 1
        page.error = None
        page.updated_at = now_iso()
        task.status = "EXTRACTING"
        task.updated_at = now_iso()
        self._persist_task(task)
        return task

    def update_page_result(self, task_id: str, page_no: int, result: Dict[str, Any]) -> TaskRecord:
        task = self.get_task(task_id)
        page = self._get_page(task, page_no)
        page.status = "COMPLETED"
        page.result = result
        page.error = None
        page.updated_at = now_iso()
        self._update_task_status(task)
        self._persist_task(task)
        return task

    def update_page_failed(self, task_id: str, page_no: int, error: str) -> TaskRecord:
        task = self.get_task(task_id)
        page = self._get_page(task, page_no)
        page.status = "FAILED"
        page.error = error
        page.updated_at = now_iso()
        self._update_task_status(task)
        self._persist_task(task)
        return task

    def retry_failed_pages(self, task_id: str, pages: Optional[List[int]] = None) -> Dict[str, Any]:
        task = self.get_task(task_id)
        candidates = task.failed_pages()
        if pages is not None:
            wanted = set([p for p in pages if isinstance(p, int)])
            candidates = [p for p in candidates if p in wanted]

        for p in candidates:
            pr = task.pages[p]
            pr.status = "PENDING"
            pr.error = None
            pr.updated_at = now_iso()

        self._update_task_status(task)
        self._persist_task(task)
        return {"task_id": task_id, "retry_pages": candidates, "count": len(candidates)}

    def finalize_task(self, task_id: str, merge_mode: str = "none") -> Dict[str, Any]:
        task = self.get_task(task_id)
        completed = task.completed_pages()
        failed = task.failed_pages()
        failed_page_errors = self._failed_page_errors(task)

        merged_markdown = ""
        merged_rag: List[Dict[str, Any]] = []
        if merge_mode in {"markdown", "both"}:
            parts: List[str] = []
            for p in completed:
                res = task.pages[p].result or {}
                md = ((res.get("render") or {}).get("markdown") or "").strip()
                if md:
                    parts.append(f"<!-- page:{p} -->\n" + md)
            merged_markdown = "\n\n".join(parts)

        if merge_mode in {"rag", "both"}:
            for p in completed:
                res = task.pages[p].result or {}
                rag = res.get("rag") or {}
                merged_rag.append({"page_no": p, "rag": rag})

        summary = {
            "task_id": task_id,
            "status": task.status,
            "total_pages": task.total_pages,
            "planned_pages": task.planned_pages,
            "completed_pages": completed,
            "failed_pages": failed,
            "failed_page_errors": failed_page_errors,
            "progress": task.progress(),
        }
        return {
            "summary": summary,
            "merged_markdown": merged_markdown if merge_mode in {"markdown", "both"} else None,
            "merged_rag": merged_rag if merge_mode in {"rag", "both"} else None,
            "failed_page_errors": failed_page_errors,
            "page_stats": {
                "completed": len(completed),
                "failed": len(failed),
                "pending": len(task.pending_pages()),
            },
        }

    def status(self, task_id: str) -> Dict[str, Any]:
        task = self.get_task(task_id)
        return {
            "task_id": task_id,
            "task_name": task.task_name,
            "state": task.status,
            "total_pages": task.total_pages,
            "planned_pages": task.planned_pages,
            "completed_pages": task.completed_pages(),
            "failed_pages": task.failed_pages(),
            "failed_page_errors": self._failed_page_errors(task),
            "pending_pages": task.pending_pages(),
            "progress": task.progress(),
            "updated_at": task.updated_at,
        }

    def _get_page(self, task: TaskRecord, page_no: int) -> PageRecord:
        if page_no not in task.pages:
            raise ValueError(f"page {page_no} is not in task planned_pages")
        return task.pages[page_no]

    def _update_task_status(self, task: TaskRecord) -> None:
        failed = task.failed_pages()
        pending = task.pending_pages()
        completed = task.completed_pages()

        if completed and not failed and not pending:
            task.status = "COMPLETED"
        elif failed and not pending:
            task.status = "FAILED"
        elif failed and pending:
            task.status = "PARTIAL_FAILED"
        elif any(task.pages[p].status == "EXTRACTING" for p in task.planned_pages):
            task.status = "EXTRACTING"
        else:
            task.status = "UPLOADED"

        task.updated_at = now_iso()

    def _failed_page_errors(self, task: TaskRecord) -> Dict[str, str]:
        return {
            str(page_no): str(task.pages[page_no].error or "")
            for page_no in task.failed_pages()
            if task.pages[page_no].error
        }

    def _new_task_id(self, task_name: str, source_path: str) -> str:
        seed = f"{task_name}:{source_path}:{now_iso()}".encode("utf-8")
        return f"task_{hashlib.sha1(seed).hexdigest()[:16]}"

    def _task_dir(self, task_id: str) -> Path:
        d = self._root / "tasks" / task_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _persist_task(self, task: TaskRecord) -> None:
        d = self._task_dir(task.task_id)
        payload: Dict[str, Any] = {
            "task_id": task.task_id,
            "task_name": task.task_name,
            "source_path": task.source_path,
            "total_pages": task.total_pages,
            "planned_pages": task.planned_pages,
            "status": task.status,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "pages": {
                str(k): {
                    "page_no": v.page_no,
                    "status": v.status,
                    "attempts": v.attempts,
                    "error": v.error,
                    "updated_at": v.updated_at,
                }
                for k, v in task.pages.items()
            },
        }
        (d / "task.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        for page_no, page in task.pages.items():
            if page.result:
                (d / f"page_{page_no}.json").write_text(
                    json.dumps(page.result, ensure_ascii=False, indent=2), encoding="utf-8"
                )

    def _save_base64_pdf(self, file_data: str, task_name: str) -> str:
        raw = base64.b64decode(file_data)
        digest = hashlib.sha1(raw).hexdigest()[:12]
        d = self._root / "uploads"
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{task_name}_{digest}.pdf"
        path.write_bytes(raw)
        return str(path)
