import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "pdf2md_enhanced_testpkg"


def _load_module(module_name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(ROOT / "mcp/servers/PDF2MDEnhanced")]
sys.modules[PACKAGE_NAME] = package

_load_module(f"{PACKAGE_NAME}.models", ROOT / "mcp/servers/PDF2MDEnhanced/models.py")
task_manager_module = _load_module(f"{PACKAGE_NAME}.task_manager", ROOT / "mcp/servers/PDF2MDEnhanced/task_manager.py")

PageRecord = sys.modules[f"{PACKAGE_NAME}.models"].PageRecord
TaskRecord = sys.modules[f"{PACKAGE_NAME}.models"].TaskRecord
TaskManager = task_manager_module.TaskManager


def _build_manager_with_task(tmp_path):
    manager = TaskManager(str(tmp_path))
    task = TaskRecord(
        task_id="task_test",
        task_name="demo",
        source_path="/tmp/demo.pdf",
        total_pages=3,
        planned_pages=[1, 2, 3],
    )
    task.pages[1] = PageRecord(page_no=1, status="COMPLETED", result={"render": {"markdown": "# ok"}})
    task.pages[2] = PageRecord(page_no=2, status="FAILED", error="VLM token quota exhausted")
    task.pages[3] = PageRecord(page_no=3, status="FAILED", error="provider timeout")
    task.status = "FAILED"
    manager._tasks[task.task_id] = task
    return manager, task.task_id


def test_status_includes_failed_page_errors(tmp_path):
    manager, task_id = _build_manager_with_task(tmp_path)

    status = manager.status(task_id)

    assert status["failed_pages"] == [2, 3]
    assert status["failed_page_errors"] == {
        "2": "VLM token quota exhausted",
        "3": "provider timeout",
    }


def test_finalize_includes_failed_page_errors(tmp_path):
    manager, task_id = _build_manager_with_task(tmp_path)

    result = manager.finalize_task(task_id, merge_mode="markdown")

    assert result["failed_page_errors"] == {
        "2": "VLM token quota exhausted",
        "3": "provider timeout",
    }
    assert result["summary"]["failed_page_errors"] == {
        "2": "VLM token quota exhausted",
        "3": "provider timeout",
    }


def test_task_record_retains_description_language():
    task = TaskRecord(
        task_id="task_language",
        task_name="demo",
        source_path="/tmp/demo.pdf",
        total_pages=1,
        planned_pages=[1],
        description_language="zh",
    )

    assert task.description_language == "zh"


def test_calculation_source_is_immutable_and_scoped_before_page_completion(tmp_path):
    import hashlib
    import json
    manager, task_id = _build_manager_with_task(tmp_path)
    pdf = tmp_path / 'source.pdf'; pdf.write_bytes(b'synthetic source bytes')
    manager.get_task(task_id).source_path = str(pdf)
    text = 'Limits\n$x<y$'
    first = manager.save_calculation_source(task_id, 2, 'tables:0', {'layout_id': 'region-a'}, text)
    path = tmp_path / 'tasks' / task_id / 'calculation_sources' / (first['artifact_id'] + '.json')
    saved = json.loads(path.read_text())
    assert saved['original_content'] == text
    assert saved['content_sha256'] == hashlib.sha256(text.encode()).hexdigest()
    assert saved['source_sha256'] == hashlib.sha256(pdf.read_bytes()).hexdigest()
    assert saved['page_no'] == 2 and saved['layout_id'] == 'region-a'
    assert path.stat().st_mode & 0o777 == 0o600
    assert manager.get_task(task_id).pages[2].status == 'FAILED'
    assert manager.save_calculation_source(task_id, 2, 'tables:0', {'layout_id': 'region-a'}, text) == first
    other = manager.save_calculation_source(task_id, 2, 'tables:1', {'layout_id': 'region-b'}, text)
    revised = manager.save_calculation_source(task_id, 2, 'tables:0', {'layout_id': 'region-a'}, text + '\n$z=2$')
    assert len({first['artifact_id'], other['artifact_id'], revised['artifact_id']}) == 3
    assert json.loads(path.read_text()) == saved


def test_calculation_source_rejects_unknown_task_page_and_empty_content(tmp_path):
    import pytest
    manager, task_id = _build_manager_with_task(tmp_path)
    for target, page, text in [('unknown', 2, 'x'), (task_id, 9, 'x'), (task_id, 2, '')]:
        with pytest.raises((KeyError, ValueError)):
            manager.save_calculation_source(target, page, 'tables:0', {}, text)
    assert not list(tmp_path.rglob('*calculation*'))


def _png_data(seed):
    import base64
    import io
    from PIL import Image
    output = io.BytesIO()
    Image.new('RGB', (2, 2), color=(seed % 255, 40, 80)).save(output, format='PNG')
    return base64.b64encode(output.getvalue()).decode('ascii')


def _finish_document_run(manager, tenant, doc, run, pages, seed, failed_pages=()):
    identities = []
    task_ids = []
    paths = []
    for page_no in pages:
        identity = {
            'tenant_id': tenant, 'doc_id': doc, 'version': 1, 'run_id': run,
            'source_page_no': page_no, 'source_file_sha256': 'a' * 64,
            'render_dpi': 300, 'run_pages': list(pages),
        }
        task = manager.start_task(
            f'{doc}-page-{page_no}', file_data=_png_data(seed + page_no), pages=[1],
            source_identity=identity,
        )
        task_ids.append(task.task_id)
        identities.append(identity)
        paths.append(task.source_path)
        if page_no in failed_pages:
            manager.update_page_failed(task.task_id, 1, 'synthetic page error')
        else:
            manager.update_page_result(task.task_id, 1, {'render': {'markdown': 'ok'}})
        manager.finalize_task(task.task_id)
    return identities[-1], task_ids, paths


def _finish_legacy_run(manager, tenant, doc, run, pages, seed):
    task_ids = []
    paths = []
    for page_no in pages:
        identity = {
            'tenant_id': tenant, 'doc_id': doc, 'version': 1, 'run_id': run,
            'source_page_no': page_no, 'source_file_sha256': 'a' * 64, 'render_dpi': 300,
        }
        task = manager.start_task(f'{doc}-page-{page_no}', file_data=_png_data(seed + page_no),
                                  pages=[1], source_identity=identity)
        task_ids.append(task.task_id)
        paths.append(task.source_path)
        manager.update_page_result(task.task_id, 1, {'render': {'markdown': 'ok'}})
        manager.finalize_task(task.task_id)
    return task_ids, paths


def test_document_run_retention_keeps_latest_three_exact_page_sets_and_removes_orphan_uploads(tmp_path):
    manager = TaskManager(str(tmp_path))
    runs = []
    first_paths = []
    for index in range(3):
        identity, task_ids, paths = _finish_document_run(
            manager, 'tenant-1', 'document-1', f'run-{index}', [2, 7], index * 20)
        if index == 0:
            assert not list((tmp_path / 'document_runs').glob('*.json'))
        result = manager.finalize_document_run(task_ids[-1], identity)
        assert result['status'] == 'FINALIZED'
        runs.append((identity['run_id'], task_ids))
        if index == 0:
            first_paths = paths

    manager = TaskManager(str(tmp_path))
    identity, task_ids, _ = _finish_document_run(
        manager, 'tenant-1', 'document-1', 'run-3', [2, 7], 60)
    result = manager.finalize_document_run(task_ids[-1], identity)
    runs.append((identity['run_id'], task_ids))

    assert result['deleted_run_ids'] == ['run-0']
    assert result['deleted_task_count'] == 2
    assert result['retained_run_ids'] == ['run-3', 'run-2', 'run-1']
    assert all(not (tmp_path / 'tasks' / task_id).exists() for task_id in runs[0][1])
    assert all(Path(path).exists() is False for path in first_paths)
    assert len(list((tmp_path / 'document_runs').glob('*.json'))) == 3

    other_identity, other_ids, _ = _finish_document_run(
        manager, 'tenant-1', 'document-1', 'different-pages', [2, 8], 110)
    assert manager.finalize_document_run(other_ids[-1], other_identity)['deleted_run_ids'] == []
    other_tenant_identity, other_tenant_ids, _ = _finish_document_run(
        manager, 'tenant-2', 'document-1', 'other-tenant', [2, 7], 130)
    assert manager.finalize_document_run(other_tenant_ids[-1], other_tenant_identity)['deleted_run_ids'] == []
    assert all((tmp_path / 'tasks' / task_id).is_dir() for task_id in other_ids + other_tenant_ids)


def test_document_run_retention_skips_incomplete_page_set_and_keeps_older_results(tmp_path):
    manager = TaskManager(str(tmp_path))
    identity, older_ids, _ = _finish_document_run(
        manager, 'tenant-1', 'document-1', 'older-complete', [2, 7], 10)
    manager.finalize_document_run(older_ids[-1], identity)

    partial_identity = {
        'tenant_id': 'tenant-1', 'doc_id': 'document-1', 'version': 1, 'run_id': 'partial',
        'source_page_no': 2, 'source_file_sha256': 'a' * 64, 'render_dpi': 300,
        'run_pages': [2, 7],
    }
    task = manager.start_task('partial-page-2', file_data=_png_data(55), pages=[1], source_identity=partial_identity)
    manager.update_page_result(task.task_id, 1, {'render': {'markdown': 'ok'}})
    manager.finalize_task(task.task_id)

    result = manager.finalize_document_run(task.task_id, partial_identity)

    assert result['status'] == 'INCOMPLETE'
    assert result['missing_pages'] == [7]
    assert all((tmp_path / 'tasks' / task_id).is_dir() for task_id in older_ids)
    assert (tmp_path / 'tasks' / task.task_id).is_dir()


def test_document_run_with_failed_pages_is_terminal_and_same_run_cannot_restart(tmp_path):
    import pytest
    manager = TaskManager(str(tmp_path))
    identity, task_ids, _ = _finish_document_run(
        manager, 'tenant-1', 'document-1', 'run-failed-page', [2, 7], 80, failed_pages={7})

    result = manager.finalize_document_run(task_ids[-1], identity)

    assert result['status'] == 'FINALIZED'
    with pytest.raises(ValueError, match='document_run_already_finalized'):
        manager.start_task('late-page', file_data=_png_data(99), pages=[1], source_identity={
            **identity, 'source_page_no': 2,
        })
    assert all((tmp_path / 'tasks' / task_id).is_dir() for task_id in task_ids)
    with pytest.raises(ValueError, match='document_run_already_finalized'):
        manager.retry_failed_pages(task_ids[1])
    with pytest.raises(ValueError, match='document_run_already_finalized'):
        manager.update_page_running(task_ids[1], 1)
    assert manager.get_task(task_ids[1]).pages[1].status == 'FAILED'


def test_document_run_pruning_preserves_uploads_shared_with_retained_runs(tmp_path):
    manager = TaskManager(str(tmp_path))
    shared_paths = []
    for index in range(4):
        identity, task_ids, paths = _finish_document_run(
            manager, 'tenant-1', 'document-1', f'shared-{index}', [4], 90)
        shared_paths = paths
        result = manager.finalize_document_run(task_ids[-1], identity)

    assert result['deleted_run_ids'] == ['shared-0']
    assert len(shared_paths) == 1 and Path(shared_paths[0]).is_file()


def test_document_run_retention_counts_legacy_complete_runs_by_observed_page_set(tmp_path):
    manager = TaskManager(str(tmp_path))
    legacy_ids = []
    first_paths = []
    for index in range(3):
        task_ids, paths = _finish_legacy_run(
            manager, 'tenant-1', 'document-1', f'legacy-{index}', [2, 7], index * 20)
        legacy_ids.append(task_ids)
        if index == 0:
            first_paths = paths

    partial_identity = {
        'tenant_id': 'tenant-1', 'doc_id': 'document-1', 'version': 1, 'run_id': 'legacy-partial',
        'source_page_no': 2, 'source_file_sha256': 'a' * 64, 'render_dpi': 300,
    }
    partial = manager.start_task('document-page-2-partial', file_data=_png_data(100), pages=[1],
                                 source_identity=partial_identity)
    manager.update_page_result(partial.task_id, 1, {'render': {'markdown': 'ok'}})
    manager.finalize_task(partial.task_id)

    identity, current_ids, _ = _finish_document_run(
        manager, 'tenant-1', 'document-1', 'current', [2, 7], 80)
    result = manager.finalize_document_run(current_ids[-1], identity)

    assert result['deleted_run_ids'] == ['legacy-0']
    assert all(not (tmp_path / 'tasks' / task_id).exists() for task_id in legacy_ids[0])
    assert all((tmp_path / 'tasks' / task_id).is_dir() for task_id in legacy_ids[1] + legacy_ids[2] + current_ids)
    assert all(not Path(path).exists() for path in first_paths)
    assert (tmp_path / 'tasks' / partial.task_id).is_dir()


def test_finalize_document_run_requires_a_task_with_the_same_identity(tmp_path):
    import pytest
    manager = TaskManager(str(tmp_path))
    identity, task_ids, _ = _finish_document_run(
        manager, 'tenant-1', 'document-1', 'run-bound-task', [2], 150)
    other_identity, other_task_ids, _ = _finish_document_run(
        manager, 'tenant-2', 'document-1', 'other-tenant', [2], 170)

    with pytest.raises(ValueError, match='task_source_identity_mismatch'):
        manager.finalize_document_run(other_task_ids[0], identity)

    assert manager.finalize_document_run(task_ids[0], identity)['status'] == 'FINALIZED'


def test_document_run_finalization_serializes_against_page_restart(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    import pytest

    manager = TaskManager(str(tmp_path))
    identity, task_ids, _ = _finish_document_run(
        manager, 'tenant-1', 'document-1', 'run-serialized', [2], 190)
    scan_started = Event()
    resume_scan = Event()
    update_attempted = Event()
    original_load = manager._load_document_run_tasks

    def paused_load(tenant_id, doc_id, run_id):
        scan_started.set()
        assert resume_scan.wait(5)
        return original_load(tenant_id, doc_id, run_id)

    manager._load_document_run_tasks = paused_load
    with ThreadPoolExecutor(max_workers=2) as executor:
        finalize = executor.submit(manager.finalize_document_run, task_ids[0], identity)
        assert scan_started.wait(2)

        def restart_page():
            update_attempted.set()
            return manager.update_page_running(task_ids[0], 1)

        update = executor.submit(restart_page)
        assert update_attempted.wait(2)
        assert not update.done()
        resume_scan.set()
        assert finalize.result(timeout=2)['status'] == 'FINALIZED'
        with pytest.raises(ValueError, match='document_run_already_finalized'):
            update.result(timeout=2)

    assert manager.get_task(task_ids[0]).pages[1].status == 'COMPLETED'


def test_document_run_stays_open_until_timed_out_worker_exits_and_blocks_late_source_writes(tmp_path):
    import pytest

    manager = TaskManager(str(tmp_path))
    identity, task_ids, _ = _finish_document_run(
        manager, 'tenant-1', 'document-1', 'run-late-worker', [2], 210)
    task_id = task_ids[0]
    manager.update_page_running(task_id, 1)
    manager.begin_page_worker(task_id, 1)
    manager.update_page_failed(task_id, 1, 'synthetic timeout')

    pending = manager.finalize_document_run(task_id, identity)
    assert pending['status'] == 'INCOMPLETE'
    assert pending['active_task_ids'] == [task_id]
    assert not list((tmp_path / 'document_runs').glob('*.json'))

    manager.finish_page_worker(task_id, 1)
    assert manager.finalize_document_run(task_id, identity)['status'] == 'FINALIZED'
    with pytest.raises(ValueError, match='document_run_already_finalized'):
        manager.save_calculation_source(task_id, 1, 'object-1', {}, 'late worker output')
    assert not (tmp_path / 'tasks' / task_id / 'calculation_sources').exists()
