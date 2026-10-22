from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import fitz

from .models import PageRecord, TaskRecord, now_iso
from .source_resolver import PDFSourceResolver


class TaskManager:
    def __init__(self, output_dir: str) -> None:
        self._tasks: Dict[str, TaskRecord] = {}
        self._root = Path(output_dir).expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._source_resolver = PDFSourceResolver(self._root)
        self._lifecycle_lock = threading.RLock()
        self._active_page_workers: Dict[tuple[str, int], int] = {}

    def start_task(
        self,
        task_name: str,
        file_path: Optional[str] = None,
        file_data: Optional[str] = None,
        file_url: Optional[str] = None,
        s3_bucket: Optional[str] = None,
        s3_key: Optional[str] = None,
        storage_config: Optional[Dict[str, Any]] = None,
        pages: Optional[List[int]] = None,
        description_language: str = "unknown",
        source_identity: Optional[Dict[str, Any]] = None,
    ) -> TaskRecord:
        identity = dict(source_identity or {})
        if source_identity is not None:
            strings = ('tenant_id', 'doc_id', 'run_id')
            base_keys = {*strings, 'version', 'source_page_no', 'source_file_sha256', 'render_dpi'}
            keys = base_keys | ({'run_pages'} if 'run_pages' in identity else set())
            if (set(identity) != keys
                    or any(not isinstance(identity[k], str) or not 0 < len(identity[k].strip()) <= 256 for k in strings)
                    or any(type(identity[k]) is not int or identity[k] < 1 for k in ('version', 'source_page_no'))
                    or type(identity['render_dpi']) is not int or identity['render_dpi'] < 300
                    or not isinstance(identity['source_file_sha256'], str)
                    or not re.fullmatch(r'[a-f0-9]{64}', identity['source_file_sha256'])):
                raise ValueError('invalid_source_identity')
            if 'run_pages' in identity:
                run_pages = identity['run_pages']
                if (not isinstance(run_pages, list) or not run_pages
                        or any(type(page) is not int or page < 1 for page in run_pages)
                        or run_pages != sorted(set(run_pages))
                        or identity['source_page_no'] not in run_pages):
                    raise ValueError('invalid_source_identity')
            with self._lifecycle_lock:
                if self._document_run_path(identity).exists():
                    raise ValueError('document_run_already_finalized')
        source = self._source_resolver.resolve(
            task_name=task_name,
            file_path=file_path,
            file_data=file_data,
            file_url=file_url,
            s3_bucket=s3_bucket,
            s3_key=s3_key,
            storage_config=storage_config,
        )
        source_path = source.source_path

        doc = fitz.open(source_path)
        total_pages = len(doc)
        image_input = not doc.is_pdf
        doc.close()
        input_image = {}
        if image_input:
            from PIL import Image
            with Image.open(source_path) as image:
                if image.format != 'PNG':
                    raise ValueError('page_image_must_be_png')
                image.verify()
                input_image = {'width': image.width, 'height': image.height,
                               'sha256': hashlib.sha256(Path(source_path).read_bytes()).hexdigest(),
                               'content_type': 'image/png'}
        elif identity:
            raise ValueError('scoped_page_task_requires_png')

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
            source_type=source.source_type,
            source_ref=source.source_ref,
            source_size_bytes=source.size_bytes,
            source_sha1=source.sha1,
            description_language=str(description_language or "unknown"),
            source_identity=identity,
            input_image=input_image,
        )
        for p in planned_pages:
            task.pages[p] = PageRecord(page_no=p)

        with self._lifecycle_lock:
            if identity and self._document_run_path(identity).exists():
                self._delete_unreferenced_upload(source_path)
                raise ValueError('document_run_already_finalized')
            self._tasks[task_id] = task
            self._persist_task(task)
        return task

    def validate_source_identity(self, task_id: str, source_identity: Optional[Dict[str, Any]]) -> None:
        task = self.get_task(task_id)
        if task.source_identity != (source_identity or {}):
            raise ValueError('task_source_identity_mismatch')

    def get_task(self, task_id: str) -> TaskRecord:
        task = self._tasks.get(task_id)
        if not task:
            raise KeyError(f"task not found: {task_id}")
        return task

    def update_page_running(self, task_id: str, page_no: int) -> TaskRecord:
        with self._lifecycle_lock:
            task = self.get_task(task_id)
            self._ensure_document_run_open(task)
            page = self._get_page(task, page_no)
            page.status = "EXTRACTING"
            page.attempts += 1
            page.error = None
            page.updated_at = now_iso()
            task.status = "EXTRACTING"
            task.updated_at = now_iso()
            self._persist_task(task)
            return task

    def begin_page_worker(self, task_id: str, page_no: int) -> None:
        with self._lifecycle_lock:
            task = self.get_task(task_id)
            self._ensure_document_run_open(task)
            if self._get_page(task, page_no).status != "EXTRACTING":
                raise ValueError('page_not_running')
            key = (task_id, page_no)
            self._active_page_workers[key] = self._active_page_workers.get(key, 0) + 1

    def finish_page_worker(self, task_id: str, page_no: int) -> None:
        with self._lifecycle_lock:
            key = (task_id, page_no)
            count = self._active_page_workers.get(key, 0)
            if count <= 1:
                self._active_page_workers.pop(key, None)
            else:
                self._active_page_workers[key] = count - 1

    def save_calculation_source(self, task_id: str, page_no: int, object_ref: str,
                                item: Dict[str, Any], content: str) -> Dict[str, Any]:
        with self._lifecycle_lock:
            task = self.get_task(task_id)
            self._ensure_document_run_open(task)
            return self._save_calculation_source_locked(task, page_no, object_ref, item, content)

    def _save_calculation_source_locked(self, task: TaskRecord, page_no: int, object_ref: str,
                                        item: Dict[str, Any], content: str) -> Dict[str, Any]:
        """Persist an immutable object source in the existing task before semantics."""
        page = self._get_page(task, page_no)
        task_id = task.task_id
        if (not isinstance(content, str) or not content.strip() or len(content) > 100000
                or not isinstance(object_ref, str) or not 0 < len(object_ref) <= 256):
            raise ValueError('invalid_calculation_source')
        layout_id = item.get('layout_id')
        if layout_id is not None and (not isinstance(layout_id, str) or len(layout_id) > 256):
            raise ValueError('invalid_calculation_source')
        with open(task.source_path, 'rb') as source:
            source_hash = hashlib.file_digest(source, 'sha256').hexdigest()
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        source = item.get('calculation_source', {})
        origin = source.get('origin', 'existing_ocr')
        image_evidence = {key: source[key] for key in ('image_sha256', 'image_scope', 'original_bbox')
                          if key in source} if origin == 'image_transcription' else {}
        identity = {'task_id': task_id, 'page_no': task.source_identity.get('source_page_no', page_no), 'object_ref': object_ref,
                    'layout_id': layout_id, 'source_sha256': source_hash, 'content_sha256': content_hash,
                    'origin': origin, **image_evidence}
        if task.source_identity:
            identity.update(source_identity=dict(task.source_identity), input_image=dict(task.input_image), input_page_no=page_no)
        if isinstance(source.get('block_transcription'), dict):
            identity['block_transcription_sha256'] = hashlib.sha256(
                json.dumps(source['block_transcription'], sort_keys=True).encode()).hexdigest()
        artifact_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        snapshot = {**identity, 'artifact_id': artifact_id,
                    'run_id': task.source_identity.get('run_id') or f'{task_id}:{page_no}:{page.attempts}', 'created_at': now_iso(),
                    'format': 'markdown', 'original_content': content}
        if isinstance(source.get('block_transcription'), dict):
            snapshot['block_transcription'] = source['block_transcription']
        directory = self._task_dir(task_id) / 'calculation_sources'
        directory.mkdir(mode=0o700, exist_ok=True)
        destination = directory / (artifact_id + '.json')
        if not destination.exists():
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=directory, delete=False) as output:
                    temporary = Path(output.name)
                    json.dump(snapshot, output, ensure_ascii=False)
                    output.flush()
                    os.fsync(output.fileno())
                try:
                    os.link(temporary, destination)
                except FileExistsError:
                    pass
                descriptor = os.open(directory, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        stored = json.loads(destination.read_text(encoding='utf-8'))
        if any(stored.get(key) != value for key, value in identity.items()) or stored.get('original_content') != content:
            raise ValueError('calculation_source_artifact_conflict')
        return {key: value for key, value in stored.items() if key != 'original_content'}

    def update_page_result(self, task_id: str, page_no: int, result: Dict[str, Any]) -> TaskRecord:
        with self._lifecycle_lock:
            task = self.get_task(task_id)
            self._ensure_document_run_open(task)
            page = self._get_page(task, page_no)
            if task.source_identity:
                result["source_identity"] = dict(task.source_identity)
                result["input_image"] = dict(task.input_image)
            page.status = "COMPLETED"
            page.result = result
            page.error = None
            page.updated_at = now_iso()
            self._update_task_status(task)
            self._persist_task(task)
            return task

    def update_page_failed(self, task_id: str, page_no: int, error: str) -> TaskRecord:
        with self._lifecycle_lock:
            task = self.get_task(task_id)
            self._ensure_document_run_open(task)
            page = self._get_page(task, page_no)
            page.status = "FAILED"
            page.error = error
            page.updated_at = now_iso()
            self._update_task_status(task)
            self._persist_task(task)
            return task

    def retry_failed_pages(self, task_id: str, pages: Optional[List[int]] = None) -> Dict[str, Any]:
        with self._lifecycle_lock:
            task = self.get_task(task_id)
            self._ensure_document_run_open(task)
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

    def finalize_document_run(self, task_id: str, source_identity: Dict[str, Any]) -> Dict[str, Any]:
        identity = dict(source_identity or {})
        required = {'tenant_id', 'doc_id', 'run_id', 'version', 'source_page_no',
                    'source_file_sha256', 'render_dpi', 'run_pages'}
        if (set(identity) != required
                or any(not isinstance(identity.get(key), str) or not identity[key].strip()
                       for key in ('tenant_id', 'doc_id', 'run_id'))
                or not isinstance(identity.get('run_pages'), list)
                or not identity['run_pages']
                or any(type(page) is not int or page < 1 for page in identity['run_pages'])
                or identity['run_pages'] != sorted(set(identity['run_pages']))
                or type(identity.get('version')) is not int or identity['version'] < 1
                or type(identity.get('source_page_no')) is not int
                or identity['source_page_no'] not in identity['run_pages']
                or type(identity.get('render_dpi')) is not int or identity['render_dpi'] < 300
                or not isinstance(identity.get('source_file_sha256'), str)
                or not re.fullmatch(r'[a-f0-9]{64}', identity['source_file_sha256'])):
            raise ValueError('invalid_document_run_identity')

        with self._lifecycle_lock:
            task = self.get_task(task_id)
            if task.source_identity != identity:
                raise ValueError('task_source_identity_mismatch')
            run_path = self._document_run_path(identity)
            if run_path.exists():
                saved = json.loads(run_path.read_text(encoding='utf-8'))
                if (saved.get('tenant_id') != identity['tenant_id']
                        or saved.get('doc_id') != identity['doc_id']
                        or saved.get('run_id') != identity['run_id']
                        or saved.get('run_pages') != identity['run_pages']):
                    raise ValueError('document_run_identity_conflict')
                return {**saved, 'status': 'FINALIZED', 'already_finalized': True}

            current_tasks = self._load_document_run_tasks(identity['tenant_id'], identity['doc_id'], identity['run_id'])
            expected_pages = set(identity['run_pages'])
            observed_pages = set()
            nonterminal_task_ids = []
            conflicting_task_ids = []
            active_task_ids = sorted({
                worker_task_id for (worker_task_id, _), count in self._active_page_workers.items()
                if count and self._tasks.get(worker_task_id) is not None
                and self._tasks[worker_task_id].source_identity.get('tenant_id') == identity['tenant_id']
                and self._tasks[worker_task_id].source_identity.get('doc_id') == identity['doc_id']
                and self._tasks[worker_task_id].source_identity.get('run_id') == identity['run_id']
            })
            for task in current_tasks:
                task_identity = task.get('source_identity') or {}
                page_no = task_identity.get('source_page_no')
                if (task_identity.get('version') != identity['version']
                        or task_identity.get('source_file_sha256') != identity['source_file_sha256']
                        or ('run_pages' in task_identity and task_identity['run_pages'] != identity['run_pages'])
                        or type(page_no) is not int or page_no not in expected_pages):
                    conflicting_task_ids.append(task.get('task_id', ''))
                    continue
                observed_pages.add(page_no)
                if not self._persisted_task_is_terminal(task):
                    nonterminal_task_ids.append(task.get('task_id', ''))

            missing_pages = sorted(expected_pages - observed_pages)
            if missing_pages or nonterminal_task_ids or conflicting_task_ids or active_task_ids:
                return {
                    'status': 'INCOMPLETE', 'run_id': identity['run_id'],
                    'run_pages': identity['run_pages'], 'missing_pages': missing_pages,
                    'nonterminal_task_ids': nonterminal_task_ids,
                    'active_task_ids': active_task_ids,
                    'conflicting_task_ids': conflicting_task_ids,
                }

            created_at = min((task.get('created_at') or '' for task in current_tasks), default='')
            record = {
                'tenant_id': identity['tenant_id'], 'doc_id': identity['doc_id'],
                'run_id': identity['run_id'], 'version': identity['version'],
                'run_pages': identity['run_pages'], 'created_at': created_at,
                'finalized_at': now_iso(), 'status': 'FINALIZED',
            }
            peers = self._load_finalized_document_runs(identity['tenant_id'], identity['doc_id'], identity['run_pages'])
            peers = [peer for peer in peers if peer.get('run_id') != identity['run_id']]
            ordered = sorted([*peers, record], key=lambda item: (
                item.get('created_at') or '', item.get('finalized_at') or '', item.get('run_id') or ''
            ), reverse=True)
            retained_run_ids = [item['run_id'] for item in ordered[:3]]
            deleted_run_ids = [item['run_id'] for item in ordered[3:]]
            deleted_task_ids = []
            deleted_sources = []
            for run_id in deleted_run_ids:
                for task in self._load_document_run_tasks(identity['tenant_id'], identity['doc_id'], run_id):
                    task_id = task.get('task_id')
                    if task_id and self._delete_task_directory(task_id):
                        deleted_task_ids.append(task_id)
                        self._tasks.pop(task_id, None)
                        if task.get('source_path'):
                            deleted_sources.append(task['source_path'])
                for peer in peers:
                    if peer.get('run_id') == run_id:
                        self._document_run_path(peer).unlink(missing_ok=True)

            for source_path in set(deleted_sources):
                self._delete_unreferenced_upload(source_path)

            run_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=run_path.parent, delete=False) as output:
                temporary = Path(output.name)
                json.dump(record, output, ensure_ascii=False)
                output.flush()
                os.fsync(output.fileno())
            try:
                os.replace(temporary, run_path)
            finally:
                temporary.unlink(missing_ok=True)
            return {**record, 'deleted_run_ids': deleted_run_ids,
                    'deleted_task_count': len(deleted_task_ids), 'retained_run_ids': retained_run_ids,
                    'already_finalized': False}

    def _document_run_path(self, identity: Dict[str, Any]) -> Path:
        key = json.dumps([identity.get('tenant_id'), identity.get('doc_id'), identity.get('run_id')],
                         ensure_ascii=False, separators=(',', ':'))
        digest = hashlib.sha256(key.encode('utf-8')).hexdigest()
        return self._root / 'document_runs' / f'{digest}.json'

    def _ensure_document_run_open(self, task: TaskRecord) -> None:
        if task.source_identity and self._document_run_path(task.source_identity).exists():
            raise ValueError('document_run_already_finalized')

    def _load_document_run_tasks(self, tenant_id: str, doc_id: str, run_id: str) -> List[Dict[str, Any]]:
        tasks_root = self._root / 'tasks'
        if not tasks_root.is_dir():
            return []
        found = []
        for directory in tasks_root.iterdir():
            if not directory.is_dir() or directory.is_symlink():
                continue
            path = directory / 'task.json'
            try:
                item = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, json.JSONDecodeError):
                continue
            identity = item.get('source_identity') or {}
            if (identity.get('tenant_id') == tenant_id and identity.get('doc_id') == doc_id
                    and identity.get('run_id') == run_id):
                found.append(item)
        return found

    def _persisted_task_is_terminal(self, task: Dict[str, Any]) -> bool:
        planned = task.get('planned_pages')
        pages = task.get('pages')
        if not isinstance(planned, list) or not planned or not isinstance(pages, dict):
            return False
        return all((pages.get(str(page)) or {}).get('status') in {'COMPLETED', 'FAILED'} for page in planned)

    def _load_finalized_document_runs(self, tenant_id: str, doc_id: str, run_pages: List[int]) -> List[Dict[str, Any]]:
        root = self._root / 'document_runs'
        records = []
        known_run_ids = set()
        if root.is_dir():
            for path in root.glob('*.json'):
                try:
                    record = json.loads(path.read_text(encoding='utf-8'))
                except (OSError, json.JSONDecodeError):
                    continue
                if (record.get('status') == 'FINALIZED' and record.get('tenant_id') == tenant_id
                        and record.get('doc_id') == doc_id and record.get('run_pages') == run_pages):
                    records.append(record)
                    known_run_ids.add(record.get('run_id'))

        tasks_root = self._root / 'tasks'
        legacy_runs: Dict[str, List[Dict[str, Any]]] = {}
        if tasks_root.is_dir():
            for directory in tasks_root.iterdir():
                if not directory.is_dir() or directory.is_symlink():
                    continue
                try:
                    task = json.loads((directory / 'task.json').read_text(encoding='utf-8'))
                except (OSError, json.JSONDecodeError):
                    continue
                identity = task.get('source_identity') or {}
                run_id = identity.get('run_id')
                if (identity.get('tenant_id') == tenant_id and identity.get('doc_id') == doc_id
                        and isinstance(run_id, str) and run_id not in known_run_ids):
                    legacy_runs.setdefault(run_id, []).append(task)

        for run_id, tasks in legacy_runs.items():
            identities = [task.get('source_identity') or {} for task in tasks]
            observed_pages = {identity.get('source_page_no') for identity in identities}
            source_revisions = {(identity.get('version'), identity.get('source_file_sha256')) for identity in identities}
            if (any(task.get('task_id') in {task_id for task_id, _ in self._active_page_workers}
                    for task in tasks)
                    or observed_pages != set(run_pages) or len(source_revisions) != 1
                    or any(not self._persisted_task_is_terminal(task) for task in tasks)
                    or any('run_pages' in identity and identity['run_pages'] != run_pages for identity in identities)):
                continue
            created_at = min((task.get('created_at') or '' for task in tasks), default='')
            finalized_at = max((task.get('updated_at') or '' for task in tasks), default=created_at)
            records.append({'tenant_id': tenant_id, 'doc_id': doc_id, 'run_id': run_id,
                            'run_pages': run_pages, 'created_at': created_at,
                            'finalized_at': finalized_at, 'status': 'FINALIZED'})
        return records

    def _delete_task_directory(self, task_id: str) -> bool:
        tasks_root = (self._root / 'tasks').resolve()
        directory = self._root / 'tasks' / task_id
        if not directory.is_dir() or directory.is_symlink() or directory.resolve().parent != tasks_root:
            return False
        shutil.rmtree(directory)
        return True

    def _delete_unreferenced_upload(self, source_path: str) -> None:
        uploads_root = self._root / 'uploads'
        candidate = Path(source_path).expanduser()
        try:
            if candidate.is_symlink() or candidate.parent.resolve() != uploads_root.resolve() or not candidate.is_file():
                return
        except OSError:
            return
        referenced = {str(Path(task.source_path).expanduser().absolute()) for task in self._tasks.values()}
        tasks_root = self._root / 'tasks'
        if tasks_root.is_dir():
            for task_path in tasks_root.glob('*/task.json'):
                try:
                    task = json.loads(task_path.read_text(encoding='utf-8'))
                except (OSError, json.JSONDecodeError):
                    continue
                if task.get('source_path'):
                    referenced.add(str(Path(task['source_path']).expanduser().absolute()))
        if str(candidate.absolute()) not in referenced:
            candidate.unlink(missing_ok=True)

    def status(self, task_id: str) -> Dict[str, Any]:
        task = self.get_task(task_id)
        return {
            "task_id": task_id,
            "task_name": task.task_name,
            "state": task.status,
            "source_type": task.source_type,
            "source_ref": task.source_ref,
            "source_size_bytes": task.source_size_bytes,
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
            "source_type": task.source_type,
            "source_ref": task.source_ref,
            "source_size_bytes": task.source_size_bytes,
            "source_sha1": task.source_sha1,
            "source_identity": task.source_identity,
            "input_image": task.input_image,
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
