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
