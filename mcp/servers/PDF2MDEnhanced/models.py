from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


TERMINAL_PAGE_STATUSES = {"COMPLETED", "FAILED"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PageRecord:
    page_no: int
    status: str = "PENDING"
    attempts: int = 0
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    updated_at: str = field(default_factory=now_iso)


@dataclass
class TaskRecord:
    task_id: str
    task_name: str
    source_path: str
    total_pages: int
    planned_pages: List[int]
    source_type: str = "unknown"
    source_ref: Optional[str] = None
    source_size_bytes: Optional[int] = None
    source_sha1: Optional[str] = None
    description_language: str = "unknown"
    status: str = "UPLOADED"
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    pages: Dict[int, PageRecord] = field(default_factory=dict)

    def progress(self) -> int:
        if not self.planned_pages:
            return 0
        done = sum(1 for p in self.pages.values() if p.status == "COMPLETED")
        return int((done / len(self.planned_pages)) * 100)

    def failed_pages(self) -> List[int]:
        return sorted([p.page_no for p in self.pages.values() if p.status == "FAILED"])

    def completed_pages(self) -> List[int]:
        return sorted([p.page_no for p in self.pages.values() if p.status == "COMPLETED"])

    def pending_pages(self) -> List[int]:
        return sorted([p.page_no for p in self.pages.values() if p.status not in TERMINAL_PAGE_STATUSES])
