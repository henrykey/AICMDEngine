import importlib.util
import sys
import types
from pathlib import Path

import fitz


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "pdf2md_enhanced_bad_text_testpkg"


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

_load_module(f"{PACKAGE_NAME}.vlm_client", ROOT / "mcp/servers/PDF2MDEnhanced/vlm_client.py")
_load_module(f"{PACKAGE_NAME}.models", ROOT / "mcp/servers/PDF2MDEnhanced/models.py")
page_processor = _load_module(f"{PACKAGE_NAME}.page_processor", ROOT / "mcp/servers/PDF2MDEnhanced/page_processor.py")
task_manager_module = _load_module(f"{PACKAGE_NAME}.task_manager", ROOT / "mcp/servers/PDF2MDEnhanced/task_manager.py")

PageRecord = sys.modules[f"{PACKAGE_NAME}.models"].PageRecord
TaskRecord = sys.modules[f"{PACKAGE_NAME}.models"].TaskRecord
TaskManager = task_manager_module.TaskManager


BAD_TEXT_POLICY = {
    "enabled": True,
    "fallback_action": "force_vlm_for_page",
    "persist_bad_text": False,
    "signals": [
        "missing_unicode_mapping",
        "low_cjk_ratio",
        "high_ascii_symbol_ratio",
        "long_ascii_symbol_runs",
        "empty_or_near-empty_text_with_visual_content",
    ],
    "thresholds": {
        "max_cjk_ratio": 0.01,
        "min_ascii_symbol_ratio": 0.60,
        "min_long_symbol_runs": 3,
    },
}


class FakeTableFinder:
    def __init__(self, tables=None):
        self.tables = tables or []


class FakePage:
    def __init__(
        self,
        text,
        blocks,
        dict_payload=None,
        rawdict_payload=None,
        images=None,
        image_rects=None,
        drawings=None,
    ):
        self.rect = fitz.Rect(0, 0, 100, 100)
        self._text = text
        self._blocks = blocks
        self._dict_payload = dict_payload or {"blocks": []}
        self._rawdict_payload = rawdict_payload or self._dict_payload
        self._images = images or []
        self._image_rects = image_rects or {}
        self._drawings = drawings or []

    def get_text(self, mode):
        if mode == "text":
            return self._text
        if mode == "blocks":
            return self._blocks
        if mode == "dict":
            return self._dict_payload
        if mode == "rawdict":
            return self._rawdict_payload
        raise ValueError(f"unsupported mode: {mode}")

    def get_images(self, full=True):
        _ = full
        return self._images

    def get_image_rects(self, xref):
        return self._image_rects.get(xref, [])

    def get_drawings(self):
        return self._drawings

    def find_tables(self):
        return FakeTableFinder()


class FakeDoc:
    def __init__(self, pages):
        self._pages = pages

    def __len__(self):
        return len(self._pages)

    def __getitem__(self, idx):
        return self._pages[idx]

    def close(self):
        return None


class FakeVLMClient:
    render = "VLM markdown"
    page_text = "VLM page text"

    def __init__(self, cfg):
        self.enabled = bool(cfg is not None)
        self.provider = "fake"
        self.model = "fake-vlm"
        self.base_url = "http://fake"
        self.timeout_sec = 30
        self.max_retries = 0

    def full_page_dual_output(self, image_path):
        _ = image_path
        return {
            "render": self.render,
            "rag": {
                "page_text": self.page_text,
                "elements": {"formulas": [], "tables": [], "figures": []},
            },
        }

    def full_page_markdown(self, image_path):
        _ = image_path
        return self.render

    def extract_region_structured(self, image_path):
        _ = image_path
        return {"formulas": [], "tables": [], "figures": []}

    def cleanup_markdown_table_noise(self, markdown_text):
        return markdown_text


def _text_block_payload(text):
    return {
        "blocks": [
            {
                "type": 0,
                "lines": [
                    {
                        "spans": [
                            {
                                "text": text,
                                "chars": [{"c": ch} for ch in text],
                            }
                        ]
                    }
                ],
            }
        ]
    }


def _patch_page_runtime(monkeypatch, page):
    monkeypatch.setattr(page_processor.fitz, "open", lambda source_path: FakeDoc([page]))
    monkeypatch.setattr(page_processor, "_render_page_image", lambda *args, **kwargs: Path("/tmp/fake_page.png"))
    monkeypatch.setattr(page_processor, "DynamicVLMClient", FakeVLMClient)


def test_good_text_page_stays_on_text_layer(monkeypatch):
    text = "这是正常中文文本，用于测试文本层提取。\n第二段包含 English words and numbers 123."
    page = FakePage(
        text=text,
        blocks=[(0, 0, 100, 20, text, 0, 0)],
        dict_payload=_text_block_payload(text),
        rawdict_payload=_text_block_payload(text),
    )
    _patch_page_runtime(monkeypatch, page)

    result = page_processor.process_page(
        source_path="/tmp/good.pdf",
        page_no=1,
        policy="auto",
        vlm_config=None,
        routing_config={"bad_text_policy": BAD_TEXT_POLICY, "render_cleanup_with_llm": False},
        prev_context=None,
    )

    assert result["route_selected"] == "text_layer"
    assert result["bad_text_detected"] is False
    assert result["bad_text_reasons"] == []
    assert "正常中文文本" in result["render"]["markdown"]
    assert result["text_quality_summary"]["missing_unicode_mapping"] is False


def test_bad_font_page_switches_to_vlm(monkeypatch):
    dirty_text = "%&!'\" !!!!!\n(cid:12)\n%%%%\n####\n!!!!!"
    page = FakePage(
        text=dirty_text,
        blocks=[(0, 0, 100, 20, dirty_text, 0, 0)],
        dict_payload=_text_block_payload(dirty_text),
        rawdict_payload=_text_block_payload(dirty_text),
    )
    _patch_page_runtime(monkeypatch, page)
    FakeVLMClient.render = "Recovered VLM markdown"
    FakeVLMClient.page_text = "Recovered VLM page text"

    result = page_processor.process_page(
        source_path="/tmp/bad.pdf",
        page_no=1,
        policy="auto",
        vlm_config={"provider": "fake"},
        routing_config={"bad_text_policy": BAD_TEXT_POLICY, "render_cleanup_with_llm": False},
        prev_context=None,
    )

    assert result["route_selected"] == "vlm"
    assert result["bad_text_detected"] is True
    assert "missing_unicode_mapping" in result["bad_text_reasons"]
    assert "long_ascii_symbol_runs" in result["bad_text_reasons"]
    assert result["render"]["markdown"] == "Recovered VLM markdown"
    assert "%&!'" not in result["render"]["markdown"]
    assert "!!!!!" not in result["render"]["markdown"]


def test_scanned_page_routes_to_vlm(monkeypatch):
    page = FakePage(
        text="",
        blocks=[],
        dict_payload={"blocks": [{"type": 1}]},
        rawdict_payload={"blocks": []},
        images=[(1,)],
        image_rects={1: [fitz.Rect(0, 0, 90, 90)]},
    )
    _patch_page_runtime(monkeypatch, page)
    FakeVLMClient.render = "Scanned OCR markdown"
    FakeVLMClient.page_text = "Scanned OCR text"

    result = page_processor.process_page(
        source_path="/tmp/scanned.pdf",
        page_no=1,
        policy="auto",
        vlm_config={"provider": "fake"},
        routing_config={"bad_text_policy": BAD_TEXT_POLICY, "render_cleanup_with_llm": False},
        prev_context=None,
    )

    assert result["route_selected"] == "vlm"
    assert result["bad_text_detected"] is True
    assert "empty_or_near-empty_text_with_visual_content" in result["bad_text_reasons"]
    assert result["render"]["markdown"] == "Scanned OCR markdown"


def test_finalize_markdown_excludes_bad_text_sample(tmp_path):
    manager = TaskManager(str(tmp_path))
    task = TaskRecord(
        task_id="task_bad_text",
        task_name="demo",
        source_path="/tmp/demo.pdf",
        total_pages=2,
        planned_pages=[1, 2],
    )
    task.pages[1] = PageRecord(
        page_no=1,
        status="COMPLETED",
        result={
            "render": {"markdown": "Clean text layer markdown"},
            "route_selected": "text_layer",
            "bad_text_detected": False,
        },
    )
    task.pages[2] = PageRecord(
        page_no=2,
        status="COMPLETED",
        result={
            "render": {"markdown": "Recovered VLM markdown"},
            "route_selected": "vlm",
            "bad_text_detected": True,
            "bad_text_reasons": ["missing_unicode_mapping", "long_ascii_symbol_runs"],
        },
    )
    task.status = "COMPLETED"
    manager._tasks[task.task_id] = task

    result = manager.finalize_task(task.task_id, merge_mode="markdown")
    merged = result["merged_markdown"] or ""

    assert "Clean text layer markdown" in merged
    assert "Recovered VLM markdown" in merged
    assert "%&!'" not in merged
    assert "!!!!!" not in merged
