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
ocr_package = types.ModuleType(f"{PACKAGE_NAME}.ocr_clients")
ocr_package.__path__ = [str(ROOT / "mcp/servers/PDF2MDEnhanced/ocr_clients")]
sys.modules[f"{PACKAGE_NAME}.ocr_clients"] = ocr_package

_load_module(f"{PACKAGE_NAME}.vlm_client", ROOT / "mcp/servers/PDF2MDEnhanced/vlm_client.py")
_load_module(f"{PACKAGE_NAME}.ocr_clients.ocr_models", ROOT / "mcp/servers/PDF2MDEnhanced/ocr_clients/ocr_models.py")
_load_module(f"{PACKAGE_NAME}.ocr_clients.ocr_normalizers", ROOT / "mcp/servers/PDF2MDEnhanced/ocr_clients/ocr_normalizers.py")
_load_module(
    f"{PACKAGE_NAME}.ocr_clients.openai_compatible_ocr_client",
    ROOT / "mcp/servers/PDF2MDEnhanced/ocr_clients/openai_compatible_ocr_client.py",
)
_load_module(f"{PACKAGE_NAME}.ocr_clients", ROOT / "mcp/servers/PDF2MDEnhanced/ocr_clients/__init__.py")
_load_module(f"{PACKAGE_NAME}.models", ROOT / "mcp/servers/PDF2MDEnhanced/models.py")
page_processor = _load_module(f"{PACKAGE_NAME}.page_processor", ROOT / "mcp/servers/PDF2MDEnhanced/page_processor.py")
task_manager_module = _load_module(f"{PACKAGE_NAME}.task_manager", ROOT / "mcp/servers/PDF2MDEnhanced/task_manager.py")

PageRecord = sys.modules[f"{PACKAGE_NAME}.models"].PageRecord
TaskRecord = sys.modules[f"{PACKAGE_NAME}.models"].TaskRecord
TaskManager = task_manager_module.TaskManager
OcrElement = sys.modules[f"{PACKAGE_NAME}.ocr_clients.ocr_models"].OcrElement
OcrResult = sys.modules[f"{PACKAGE_NAME}.ocr_clients.ocr_models"].OcrResult


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
    region_structured = {"formulas": [], "tables": [], "figures": []}

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
        return self.region_structured

    def cleanup_markdown_table_noise(self, markdown_text):
        return markdown_text


def test_direct_markdown_preserves_multiple_numbered_sections_in_one_text_block():
    page = FakePage(
        text="7 结构\n7.1 总体结构\n7.1.1 本文件中发卡式热交换器主要包括。\n",
        blocks=[
            (10.0, 10.0, 70.0, 20.0,
             "7 结构\n7.1 总体结构\n7.1.1 本文件中发卡式热交换器主要包括。\n", 0, 0)
        ],
    )

    markdown = page_processor._build_direct_markdown(page)

    assert "7 结构" in markdown
    assert "7.1 总体结构" in markdown
    assert "7.1.1 本文件中发卡式热交换器主要包括。" in markdown

class FakeGLMOcrClient:
    result = None
    error = None

    def __init__(self, cfg, source="glm_ocr"):
        self.enabled = bool((cfg or {}).get("enabled"))
        self.source = source

    def extract_page(self, image_path):
        _ = image_path
        if self.error:
            raise RuntimeError(self.error)
        if self.result is not None:
            return self.result
        return OcrResult(
            markdown="GLM OCR markdown",
            page_text="GLM OCR text",
            formulas=[OcrElement(kind="formula", source="glm_ocr", latex="a=b+c")],
        )


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
    monkeypatch.setattr(page_processor, "OpenAICompatibleOcrClient", FakeGLMOcrClient)
    FakeGLMOcrClient.result = None
    FakeGLMOcrClient.error = None
    FakeVLMClient.render = "VLM markdown"
    FakeVLMClient.page_text = "VLM page text"
    FakeVLMClient.region_structured = {"formulas": [], "tables": [], "figures": []}


def _build_structured_pdf_fixture(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text(
        (48, 64),
        "4.1 Structured extraction fixture\n"
        "This authorized synthetic page validates local routing and structured element contracts.\n"
        "Formula: t = pD / (2 sigma phi - p). Variables are defined below.\n"
        "Table 1 Fixture measurements",
        fontsize=11,
    )

    left, top, cell_width, cell_height = 48, 150, 140, 28
    for row in range(4):
        y = top + row * cell_height
        page.draw_line((left, y), (left + 2 * cell_width, y))
    for col in range(3):
        x = left + col * cell_width
        page.draw_line((x, top), (x, top + 3 * cell_height))
    page.insert_text((left + 8, top + 19), "Name", fontsize=10)
    page.insert_text((left + cell_width + 8, top + 19), "Value", fontsize=10)
    page.insert_text((left + 8, top + cell_height + 19), "alpha", fontsize=10)
    page.insert_text((left + cell_width + 8, top + cell_height + 19), "1.25", fontsize=10)
    page.insert_text((left + 8, top + 2 * cell_height + 19), "beta", fontsize=10)
    page.insert_text((left + cell_width + 8, top + 2 * cell_height + 19), "2.50", fontsize=10)

    page.draw_circle((420, 210), 38)
    page.draw_line((382, 210), (458, 210))
    page.draw_line((420, 172), (420, 248))
    page.insert_text((370, 270), "Figure 1 Calibration schematic", fontsize=10)
    doc.save(path)
    doc.close()


def test_real_pdf_auto_glm_to_vlm_preserves_structured_element_contract(monkeypatch, tmp_path):
    pdf_path = tmp_path / "structured-extraction-fixture.pdf"
    _build_structured_pdf_fixture(pdf_path)

    with fitz.open(pdf_path) as doc:
        assert len(doc) == 1
        assert doc[0].find_tables().tables

    class FixtureGLMOcrClient:
        calls = 0

        def __init__(self, cfg, source="glm_ocr"):
            self.enabled = bool((cfg or {}).get("enabled"))
            self.source = source

        def extract_page(self, image_path):
            FixtureGLMOcrClient.calls += 1
            assert Path(image_path).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
            return OcrResult(
                markdown="GLM OCR fixture markdown",
                formulas=[
                    OcrElement(
                        kind="formula",
                        source="glm_ocr",
                        latex="t=\\frac{pD}{2\\sigma\\phi-p}",
                        description="GLM formula only; table intentionally omitted to exercise fallback.",
                    )
                ]
            )

    class FixtureVLMClient:
        calls = 0

        def __init__(self, cfg):
            self.enabled = bool(cfg)
            self.provider = "fixture"
            self.model = "fixture-vlm"
            self.base_url = "local://fixture"
            self.timeout_sec = 5
            self.max_retries = 0

        def extract_region_structured(self, image_path):
            FixtureVLMClient.calls += 1
            assert Path(image_path).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
            return {
                "tables": [
                    {
                        "title": "Table 1 Fixture measurements",
                        "markdown": "| Name | Value |\n| --- | --- |\n| alpha | 1.25 |\n| beta | 2.50 |",
                        "description": "Synthetic calibration values for the local persistence contract.",
                        "bbox": [48, 150, 328, 234],
                        "confidence": 0.99,
                        "status": "EXTRACTED",
                    }
                ],
                "formulas": [
                    {
                        "latex": "t=\\frac{pD}{2\\sigma\\phi-p}",
                        "description": "Computes the required wall thickness from pressure, diameter, stress, and efficiency.",
                        "variables": "t thickness; p pressure; D diameter; sigma stress; phi efficiency",
                        "context": "Formula on the synthetic validation page.",
                        "bbox": [48, 92, 360, 112],
                        "confidence": 0.98,
                        "status": "EXTRACTED",
                    }
                ],
                "figures": [
                    {
                        "caption": "Figure 1 Calibration schematic",
                        "type": "schematic",
                        "description": "A circle with horizontal and vertical center lines.",
                        "labels": ["horizontal axis", "vertical axis"],
                        "context": "Synthetic calibration figure.",
                        "bbox": [370, 172, 458, 270],
                        "confidence": 0.97,
                        "status": "EXTRACTED",
                    }
                ],
            }

        def full_page_dual_output(self, image_path):
            return {
                "render": "VLM fixture markdown",
                "rag": {
                    "page_text": "VLM fixture page text",
                    "elements": self.extract_region_structured(image_path),
                },
            }

        def cleanup_markdown_table_noise(self, markdown_text):
            return markdown_text

    monkeypatch.setattr(page_processor, "OpenAICompatibleOcrClient", FixtureGLMOcrClient)
    monkeypatch.setattr(page_processor, "DynamicVLMClient", FixtureVLMClient)

    result = page_processor.process_page(
        source_path=str(pdf_path),
        page_no=1,
        policy="auto",
        vlm_config={"provider": "fixture"},
        routing_config={
            "formula_score_region_vlm": 0.01,
            "table_score_region_vlm": 0.01,
            "ocr_config": {
                "glm_ocr": {
                    "enabled": True,
                    "model": "fixture-glm",
                    "api_key": "unused",
                    "base_url": "local://fixture",
                }
            },
            "render_cleanup_with_llm": False,
        },
        prev_context=None,
    )

    assert result["route_selected"] == "full_vlm_ocr"
    assert result["decision"]["fallback_reason"] == "glm_ocr_insufficient_structured_output"
    assert result["decision"]["glm_calls"] == FixtureGLMOcrClient.calls == 1
    assert result["decision"]["vlm_calls"] == FixtureVLMClient.calls == 1
    assert result["semantic_status"] == {"complete": True, "missing": [], "reason": ""}

    table = result["elements"]["tables"][0]
    assert table["title"] == "Table 1 Fixture measurements"
    assert table["markdown"].splitlines()[-1] == "| beta | 2.50 |"
    assert table["semantic_summary"] == "Synthetic calibration values for the local persistence contract."
    assert table["bbox"] == [48, 150, 328, 234]
    assert table["confidence"] == 0.99
    assert table["status"] == "EXTRACTED"

    formula = result["elements"]["formulas"][0]
    assert formula["latex"] == "t=\\frac{pD}{2\\sigma\\phi-p}"
    assert formula["semantic_summary"].startswith("Computes the required wall thickness")
    assert formula["variables"].startswith("t thickness")
    assert formula["context"] == "Formula on the synthetic validation page."
    assert formula["bbox"] == [48, 92, 360, 112]
    assert formula["confidence"] == 0.98
    assert formula["status"] == "EXTRACTED"

    figure = result["elements"]["figures"][0]
    assert figure["caption"] == "Figure 1 Calibration schematic"
    assert figure["type"] == "schematic"
    assert figure["description"] == "A circle with horizontal and vertical center lines."
    assert figure["labels"] == ["horizontal axis", "vertical axis"]
    assert figure["context"] == "Synthetic calibration figure."
    assert figure["bbox"] == [370, 172, 458, 270]
    assert figure["confidence"] == 0.97
    assert figure["status"] == "EXTRACTED"


def test_full_glm_keeps_usable_markdown_when_structured_fallback_fails(monkeypatch, tmp_path):
    pdf_path = tmp_path / "large-table-recovery-fixture.pdf"
    _build_structured_pdf_fixture(pdf_path)

    glm_markdown = (
        "# Table 1 Fixture measurements\n\n"
        "| Name | Value |\n| --- | --- |\n| alpha | 1.25 |\n| beta | 2.50 |"
    )

    class MarkdownOnlyGLMClient:
        def __init__(self, cfg, source="glm_ocr"):
            self.enabled = True
            self.source = source

        def extract_page(self, image_path):
            _ = image_path
            return OcrResult(markdown=glm_markdown, page_text=glm_markdown)

    class FailingDualVLMClient:
        def __init__(self, cfg):
            self.enabled = True
            self.provider = "fixture"
            self.model = "fixture-vlm"
            self.base_url = "local://fixture"
            self.timeout_sec = 5
            self.max_retries = 0

        def full_page_dual_output(self, image_path):
            _ = image_path
            raise ValueError("dual output json parse failed")

        def cleanup_markdown_table_noise(self, markdown_text):
            return markdown_text

    monkeypatch.setattr(page_processor, "OpenAICompatibleOcrClient", MarkdownOnlyGLMClient)
    monkeypatch.setattr(page_processor, "DynamicVLMClient", FailingDualVLMClient)

    result = page_processor.process_page(
        source_path=str(pdf_path),
        page_no=1,
        policy="auto",
        vlm_config={"provider": "fixture"},
        routing_config={
            "formula_score_region_vlm": 0.01,
            "table_score_region_vlm": 0.01,
            "render_cleanup_with_llm": False,
            "ocr_config": {
                "glm_ocr": {
                    "enabled": True,
                    "model": "fixture-glm",
                    "api_key": "unused",
                    "base_url": "local://fixture",
                }
            },
        },
        prev_context=None,
    )

    assert result["render"]["markdown"] == glm_markdown
    assert result["route_selected"] == "full_glm_ocr"
    assert result["decision"]["fallback_reason"] == "dual output json parse failed"
    assert result["semantic_status"]["complete"] is False
    assert "formula_latex" in result["semantic_status"]["missing"]
    assert len(result["elements"]["tables"]) == 1


def test_unreadable_empty_structured_objects_do_not_count_as_extracted():
    structured = page_processor._normalize_structured(
        {
            "tables": [{"title": "Unreadable table", "markdown": "", "status": "UNREADABLE"}],
            "formulas": [{"latex": "", "status": "UNREADABLE"}],
            "figures": [{"caption": "", "description": "", "status": "UNREADABLE"}],
        }
    )

    assert structured == {"tables": [], "formulas": [], "figures": []}


def test_good_text_page_uses_vlm_when_glm_is_unavailable(monkeypatch):
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

    assert result["route_selected"] == "full_vlm_ocr"
    assert result["legacy_route_selected"] == "vlm"
    assert result["bad_text_detected"] is False
    assert result["bad_text_reasons"] == []
    assert result["render"]["markdown"] == "VLM markdown"
    assert result["text_quality_summary"]["missing_unicode_mapping"] is False


def test_text_only_page_formats_split_clause_titles_as_markdown(monkeypatch):
    text = (
        "3.7\n"
        "加强环\n"
        "reinforcement rings\n"
        "用于提高波纹管局部刚度的构件。\n\n"
        "3. 10\n"
        "辅助套筒\n"
        "auxiliary sleeve\n"
        "用于保护波纹管的部件。\n\n"
        "4 .1\n"
        "通则\n"
        "波纹膨胀节应符合本标准的规定。"
    )
    page = FakePage(
        text=text,
        blocks=[(10, 10, 80, 80, text, 0, 0)],
        dict_payload=_text_block_payload(text),
        rawdict_payload=_text_block_payload(text),
    )
    _patch_page_runtime(monkeypatch, page)

    result = page_processor.process_page(
        source_path="/tmp/gbt16749-page-7.pdf",
        page_no=1,
        policy="force_direct",
        vlm_config=None,
        routing_config={"render_cleanup_with_llm": False},
        prev_context=None,
    )

    assert result["route_selected"] == "text_only"
    assert "## 3.7 加强环" in result["render"]["markdown"]
    assert "## 3.10 辅助套筒" in result["render"]["markdown"]
    assert "## 4.1 通则" in result["render"]["markdown"]
    assert "用于提高波纹管局部刚度的构件。" in result["render"]["markdown"]


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

    assert result["route_selected"] == "full_vlm_ocr"
    assert result["legacy_route_selected"] == "vlm"
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

    assert result["route_selected"] == "full_vlm_ocr"
    assert result["bad_text_detected"] is True
    assert "empty_or_near-empty_text_with_visual_content" in result["bad_text_reasons"]
    assert result["render"]["markdown"] == "Scanned OCR markdown"


def test_formula_page_uses_hybrid_glm_when_enabled(monkeypatch):
    text = (
        "本页说明承压部件厚度按下式计算，并给出变量说明。"
        "计算结果应结合设计压力和许用应力校核。"
        "t = pD / (2σφ - p)。式中 p 为设计压力，D 为内径，σ 为许用应力。"
    )
    page = FakePage(
        text=text,
        blocks=[(0, 0, 100, 20, text, 0, 0)],
        dict_payload=_text_block_payload(text),
        rawdict_payload=_text_block_payload(text),
    )
    _patch_page_runtime(monkeypatch, page)
    FakeGLMOcrClient.result = OcrResult(
        markdown="所需壁厚按下式计算。",
        page_text="",
        formulas=[
            OcrElement(
                kind="formula",
                source="glm_ocr",
                latex="t=\\frac{pD}{2\\sigma\\phi-p}",
                description="用于计算承压部件所需壁厚。",
            )
        ],
    )

    result = page_processor.process_page(
        source_path="/tmp/formula.pdf",
        page_no=1,
        policy="auto",
        vlm_config=None,
        routing_config={
            "ocr_config": {"glm_ocr": {"enabled": True, "model": "glm-ocr", "api_key": "x", "base_url": "http://x"}},
            "render_cleanup_with_llm": False,
        },
        prev_context=None,
    )

    assert result["route_selected"] == "full_glm_ocr"
    assert result["decision"]["glm_calls"] == 1
    assert result["elements"]["formulas"][0]["source"] == "glm_ocr"
    assert result["elements"]["formulas"][0]["semantic_summary"] == "用于计算承压部件所需壁厚。"
    assert result["semantic_status"]["complete"] is True


def test_formula_page_without_ocr_result_is_not_marked_complete(monkeypatch):
    text = "所需壁厚按下式计算：t = pD / (2σφ - p)。式中 p 为设计压力。"
    page = FakePage(
        text=text,
        blocks=[(10, 10, 80, 30, text, 0, 0)],
        dict_payload=_text_block_payload(text),
        rawdict_payload=_text_block_payload(text),
    )
    _patch_page_runtime(monkeypatch, page)

    result = page_processor.process_page(
        source_path="/tmp/formula-missing.pdf",
        page_no=1,
        policy="auto",
        vlm_config=None,
        routing_config={"render_cleanup_with_llm": False, "vlm_ocr_enabled": False},
        prev_context=None,
    )

    assert result["route_selected"] == "text_only"
    assert result["elements"]["formulas"] == []
    assert result["semantic_status"]["complete"] is False
    assert result["semantic_status"]["missing"] == ["formula_latex"]
    assert result["semantic_status"]["reason"] == "vlm_ocr_disabled"


def test_scanned_page_uses_full_glm_then_falls_back_to_vlm(monkeypatch):
    page = FakePage(
        text="",
        blocks=[],
        dict_payload={"blocks": [{"type": 1}]},
        rawdict_payload={"blocks": []},
        images=[(1,)],
        image_rects={1: [fitz.Rect(0, 0, 90, 90)]},
    )
    _patch_page_runtime(monkeypatch, page)
    FakeGLMOcrClient.error = "glm unavailable"
    FakeVLMClient.render = "Fallback VLM markdown"
    FakeVLMClient.page_text = "Fallback VLM text"

    result = page_processor.process_page(
        source_path="/tmp/scanned.pdf",
        page_no=1,
        policy="auto",
        vlm_config={"provider": "fake"},
        routing_config={
            "bad_text_policy": BAD_TEXT_POLICY,
            "ocr_config": {"glm_ocr": {"enabled": True, "model": "glm-ocr", "api_key": "x", "base_url": "http://x"}},
            "render_cleanup_with_llm": False,
        },
        prev_context=None,
    )

    assert result["route_selected"] == "full_vlm_ocr"
    assert result["decision"]["glm_calls"] == 1
    assert result["decision"]["vlm_calls"] == 1
    assert result["decision"]["fallback_reason"] == "glm unavailable"
    assert result["render"]["markdown"] == "Fallback VLM markdown"


def test_vlm_disabled_marks_missing_figure_semantics_incomplete(monkeypatch):
    text = "本页包含工程结构示意图，正文说明用于保持文本层可靠。" * 6
    page = FakePage(
        text=text,
        blocks=[(0, 0, 100, 20, text, 0, 0)],
        dict_payload=_text_block_payload(text),
        rawdict_payload=_text_block_payload(text),
        images=[(1,)],
        image_rects={1: [fitz.Rect(0, 0, 60, 60)]},
    )
    _patch_page_runtime(monkeypatch, page)
    FakeGLMOcrClient.result = OcrResult(markdown="工程结构示意图正文。")

    result = page_processor.process_page(
        source_path="/tmp/figure.pdf",
        page_no=1,
        policy="auto",
        vlm_config=None,
        routing_config={
            "vlm_ocr_enabled": False,
            "ocr_config": {"glm_ocr": {"enabled": True, "model": "glm-ocr", "api_key": "x", "base_url": "http://x"}},
            "render_cleanup_with_llm": False,
        },
        prev_context=None,
    )

    assert result["route_selected"] == "full_glm_ocr"
    assert result["semantic_status"]["complete"] is False
    assert result["semantic_status"]["missing"] == ["figure_description"]
    assert result["semantic_status"]["reason"] == "vlm_ocr_disabled"


def test_visual_page_prefers_full_glm_ocr_for_page_markdown(monkeypatch):
    text = "本页包含工程结构示意图，正文说明用于保持文本层可靠。" * 6
    page = FakePage(
        text=text,
        blocks=[(0, 0, 100, 20, text, 0, 0)],
        dict_payload=_text_block_payload(text),
        rawdict_payload=_text_block_payload(text),
        images=[(1,)],
        image_rects={1: [fitz.Rect(0, 0, 60, 60)]},
    )
    _patch_page_runtime(monkeypatch, page)
    FakeGLMOcrClient.result = OcrResult(markdown="7 结构\n\n7.1 总体结构")
    FakeVLMClient.region_structured = {
        "formulas": [],
        "tables": [],
        "figures": [{"caption": "图1", "description": "发卡式热交换器结构示意图。"}],
    }

    result = page_processor.process_page(
        source_path="/tmp/figure-page.pdf",
        page_no=1,
        policy="auto",
        vlm_config={"provider": "fake"},
        routing_config={
            "ocr_config": {"glm_ocr": {"enabled": True, "model": "glm-ocr", "api_key": "x", "base_url": "http://x"}},
            "render_cleanup_with_llm": False,
        },
        prev_context=None,
    )

    assert result["route_selected"] == "full_glm_ocr"
    assert result["decision"]["glm_calls"] == 1
    assert result["decision"]["vlm_calls"] == 1
    assert result["render"]["markdown"] == "7 结构\n\n7.1 总体结构"
    assert result["elements"]["figures"][0]["semantic_summary"] == "发卡式热交换器结构示意图。"


def test_bad_glm_markdown_falls_back_to_full_vlm(monkeypatch):
    text = "本页包含工程结构示意图，正文说明用于保持文本层可靠。" * 6
    page = FakePage(
        text=text,
        blocks=[(0, 0, 100, 20, text, 0, 0)],
        dict_payload=_text_block_payload(text),
        rawdict_payload=_text_block_payload(text),
        images=[(1,)],
        image_rects={1: [fitz.Rect(0, 0, 60, 60)]},
    )
    _patch_page_runtime(monkeypatch, page)
    FakeGLMOcrClient.result = OcrResult(markdown="\ufffd\ufffd\ufffd????")
    FakeVLMClient.region_structured = {"formulas": [], "tables": [], "figures": []}

    result = page_processor.process_page(
        source_path="/tmp/bad-glm-page.pdf",
        page_no=1,
        policy="auto",
        vlm_config={"provider": "fake"},
        routing_config={
            "ocr_config": {"glm_ocr": {"enabled": True, "model": "glm-ocr", "api_key": "x", "base_url": "http://x"}},
            "render_cleanup_with_llm": False,
        },
        prev_context=None,
    )

    assert result["route_selected"] == "full_vlm_ocr"
    assert result["decision"]["glm_calls"] == 1
    assert result["decision"]["vlm_calls"] == 1
    assert result["decision"]["fallback_reason"] == "glm_ocr_bad_markdown"
    assert result["render"]["markdown"] == "VLM markdown"


def test_blank_page_completes_placeholder_without_vlm(monkeypatch):
    page = FakePage(text="", blocks=[], dict_payload={"blocks": []}, rawdict_payload={"blocks": []})
    _patch_page_runtime(monkeypatch, page)

    result = page_processor.process_page(
        source_path="/tmp/blank.pdf",
        page_no=1,
        policy="auto",
        vlm_config=None,
        routing_config={"render_cleanup_with_llm": False},
        prev_context=None,
    )

    assert result["route_selected"] == "blank"
    assert result["render"]["markdown"] == ""
    assert result["semantic_status"]["complete"] is True
    assert result["page_type"] == "blank"
    assert result["layout_status"] == "EXTRACTED"
    assert result["page_width"] == result["page_height"] == 1.0
    assert result["layout"] == []
    assert result["reconciliation"]["accounted_for"] is True
    assert result["reconciliation"]["complete"] is True


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


class LayoutLedgerGLMOcrClient:
    raw = {}

    def __init__(self, cfg, source="glm_ocr"):
        self.enabled = bool((cfg or {}).get("enabled"))
        self.use_layout_parsing = True
        self.source = source

    def parse_layout(self, image_path, return_crop_images=False, need_layout_visualization=False):
        _ = image_path
        _ = return_crop_images
        _ = need_layout_visualization
        return self.raw

    def extract_page(self, image_path):
        _ = image_path
        return OcrResult(markdown=str(self.raw.get("md_results") or ""))


class LayoutLedgerVLMClient:
    recovered = {"tables": [], "formulas": [], "figures": []}
    calls = 0
    last_blocks = []

    def __init__(self, cfg):
        self.enabled = bool(cfg)
        self.provider = "fixture"
        self.model = "fixture-vlm"
        self.base_url = "local://fixture"
        self.timeout_sec = 5
        self.max_retries = 0
        self.last_call_info = {}
        self.last_dual_output_budget = {}

    def extract_layout_structured(self, image_path, layout_blocks):
        _ = image_path
        assert layout_blocks
        type(self).calls += 1
        type(self).last_blocks = layout_blocks
        return self.recovered

    def cleanup_markdown_table_noise(self, markdown_text):
        return markdown_text


def _run_layout_ledger_page(monkeypatch, raw, recovered=None):
    page = FakePage(
        text="fixture text layer",
        blocks=[(0, 0, 100, 100, "fixture text layer", 0, 0)],
        dict_payload=_text_block_payload("fixture text layer"),
        rawdict_payload=_text_block_payload("fixture text layer"),
    )
    monkeypatch.setattr(page_processor.fitz, "open", lambda source_path: FakeDoc([page]))
    monkeypatch.setattr(page_processor, "_render_page_image", lambda *args, **kwargs: Path("/tmp/layout-page.png"))
    monkeypatch.setattr(page_processor, "OpenAICompatibleOcrClient", LayoutLedgerGLMOcrClient)
    monkeypatch.setattr(page_processor, "DynamicVLMClient", LayoutLedgerVLMClient)
    LayoutLedgerGLMOcrClient.raw = raw
    LayoutLedgerVLMClient.recovered = recovered or {"tables": [], "formulas": [], "figures": []}
    LayoutLedgerVLMClient.calls = 0
    LayoutLedgerVLMClient.last_blocks = []
    return page_processor.process_page(
        source_path="/tmp/layout-fixture.pdf",
        page_no=1,
        policy="force_direct",
        vlm_config={"provider": "fixture"} if recovered is not None else None,
        routing_config={
            "ocr_config": {
                "glm_ocr": {
                    "enabled": True,
                    "model": "glm-ocr",
                    "api_key": "unused",
                    "base_url": "local://fixture",
                }
            },
            "render_cleanup_with_llm": False,
        },
        prev_context=None,
    )


def _layout_raw(blocks, markdown="fixture markdown"):
    return {
        "md_results": markdown,
        "data_info": {"width": 100, "height": 100},
        "layout_details": [blocks],
    }


def test_process_page_layout_ledger_is_authoritative_for_two_tables(monkeypatch):
    first = "| A | B |\n| --- | --- |\n| 1 | 2 |"
    second = "| C | D |\n| --- | --- |\n| 3 | 4 |"
    result = _run_layout_ledger_page(
        monkeypatch,
        _layout_raw(
            [
                {"index": 10, "label": "text", "bbox_2d": [10, 5, 90, 15], "content": "before"},
                {"index": 20, "label": "table", "bbox_2d": [10, 20, 90, 40], "content": first},
                {"index": 30, "label": "text", "bbox_2d": [10, 45, 90, 55], "content": "between"},
                {"index": 40, "label": "table", "bbox_2d": [10, 60, 90, 85], "content": second},
                {"index": 50, "label": "text", "bbox_2d": [10, 90, 90, 98], "content": "after"},
            ],
            markdown=f"before\n\n{first}\n\nbetween\n\n{second}\n\nafter",
        ),
    )

    assert result["layout_status"] == "EXTRACTED"
    assert [item["type"] for item in result["layout"]] == ["text", "table", "text", "table", "text"]
    assert [item["reading_order"] for item in result["layout"]] == [1, 2, 3, 4, 5]
    assert result["layout"][1]["bbox"] == [0.1, 0.2, 0.9, 0.4]
    assert [item["source_block_index"] for item in result["elements"]["tables"]] == [20, 40]
    assert all(item["bbox_space"] == "normalized_page" for item in result["elements"]["tables"])
    assert all(item["layout_id"] for item in result["elements"]["tables"])
    assert result["layout"][1]["payload_ref"] == {"collection": "tables", "index": 0}
    assert result["layout"][3]["payload_ref"] == {"collection": "tables", "index": 1}
    assert result["reconciliation"]["by_type"]["table"] == {
        "identified": 2,
        "extracted": 2,
        "failed": 0,
    }
    assert result["reconciliation"]["accounted_for"] is True
    assert result["reconciliation"]["complete"] is True
    assert LayoutLedgerVLMClient.calls == 0


def test_process_page_layout_complete_html_tables_do_not_trigger_recovery(monkeypatch):
    tables = [
        "<table><tr><td>A</td><td>B</td></tr><tr><td>1</td><td>2</td></tr></table>",
        "<table><tr><td>C</td><td>D</td></tr><tr><td>3</td><td>4</td></tr></table>",
        "<table><tr><td>E</td><td>F</td></tr><tr><td>5</td><td>6</td></tr></table>",
    ]
    result = _run_layout_ledger_page(
        monkeypatch,
        _layout_raw(
            [
                {
                    "index": index,
                    "label": "table",
                    "bbox_2d": [10, 10 + offset, 90, 25 + offset],
                    "content": table,
                }
                for index, offset, table in zip((10, 20, 30), (0, 30, 60), tables)
            ],
            markdown="\n\n".join(tables),
        ),
        recovered={"tables": [], "formulas": [], "figures": []},
    )

    assert [item["status"] for item in result["layout"]] == ["EXTRACTED"] * 3
    assert [item["markdown"] for item in result["elements"]["tables"]] == tables
    assert result["reconciliation"]["complete"] is True
    assert LayoutLedgerVLMClient.calls == 0


def test_process_page_layout_recovers_only_incomplete_second_html_table(monkeypatch):
    first = "<table><tr><td>A</td><td>B</td></tr><tr><td>1</td><td>2</td></tr></table>"
    incomplete_second = "<table><tr><td>C</td><td>D</td></tr><tr><td>3</td><td>"
    recovered_second = "<table><tr><td>C</td><td>D</td></tr><tr><td>3</td><td>4</td></tr></table>"
    first_bbox = [0.1, 0.1, 0.9, 0.4]
    second_bbox = [0.1, 0.5, 0.9, 0.9]
    result = _run_layout_ledger_page(
        monkeypatch,
        _layout_raw(
            [
                {"index": 10, "label": "table", "bbox_2d": [10, 10, 90, 40], "content": first},
                {
                    "index": 20,
                    "label": "table",
                    "bbox_2d": [10, 50, 90, 90],
                    "content": incomplete_second,
                },
            ],
            markdown=f"{first}\n\n{incomplete_second}",
        ),
        recovered={
            "tables": [
                {
                    "layout_id": "p1-o002-table",
                    "source_block_index": 20,
                    "markdown": recovered_second,
                }
            ],
            "formulas": [],
            "figures": [],
        },
    )

    assert LayoutLedgerVLMClient.calls == 1
    assert [block["layout_id"] for block in LayoutLedgerVLMClient.last_blocks] == ["p1-o002-table"]
    assert [item["status"] for item in result["layout"]] == ["EXTRACTED", "EXTRACTED"]
    assert [item["reading_order"] for item in result["layout"]] == [1, 2]
    assert [item["bbox"] for item in result["layout"]] == [first_bbox, second_bbox]
    assert result["elements"]["tables"][0]["markdown"] == first
    assert result["elements"]["tables"][0]["source"] == "glm_ocr_layout"
    assert result["elements"]["tables"][1]["markdown"] == recovered_second
    assert result["elements"]["tables"][1]["source"] == "glm_ocr_layout+vlm_ocr"
    assert result["elements"]["tables"][1]["layout_id"] == "p1-o002-table"
    assert result["reconciliation"]["complete"] is True


def test_process_page_layout_incomplete_table_recovery_failure_is_isolated(monkeypatch):
    first = "<table><tr><td>A</td><td>B</td></tr><tr><td>1</td><td>2</td></tr></table>"
    incomplete_second = "<table><tr><td>C</td><td>D</td></tr><tr><td>3</td><td>"
    result = _run_layout_ledger_page(
        monkeypatch,
        _layout_raw(
            [
                {"index": 10, "label": "table", "bbox_2d": [10, 10, 90, 40], "content": first},
                {
                    "index": 20,
                    "label": "table",
                    "bbox_2d": [10, 50, 90, 90],
                    "content": incomplete_second,
                },
            ]
        ),
        recovered={
            "tables": [
                {
                    "layout_id": "p1-o002-table",
                    "source_block_index": 20,
                    "markdown": incomplete_second,
                }
            ],
            "formulas": [],
            "figures": [],
        },
    )

    assert LayoutLedgerVLMClient.calls == 1
    assert [block["layout_id"] for block in LayoutLedgerVLMClient.last_blocks] == ["p1-o002-table"]
    assert [item["status"] for item in result["layout"]] == ["EXTRACTED", "FAILED"]
    assert result["layout"][1]["error"] == {
        "code": "layout_table_content_incomplete",
        "stage": "layout_content",
        "retryable": True,
    }
    assert [item["markdown"] for item in result["elements"]["tables"]] == [first]
    assert result["reconciliation"]["accounted_for"] is True
    assert result["reconciliation"]["complete"] is False
    assert result["reconciliation"]["by_type"]["table"] == {
        "identified": 2,
        "extracted": 1,
        "failed": 1,
    }


def test_process_page_layout_ledger_covers_figure_and_table(monkeypatch):
    table = "| A | B |\n| --- | --- |\n| 1 | 2 |"
    result = _run_layout_ledger_page(
        monkeypatch,
        _layout_raw(
            [
                {"index": 1, "label": "text", "bbox_2d": [5, 5, 95, 15], "content": "before"},
                {"index": 2, "label": "image", "bbox_2d": [5, 20, 45, 55], "content": ""},
                {"index": 3, "label": "table", "bbox_2d": [50, 20, 95, 55], "content": table},
                {"index": 4, "label": "text", "bbox_2d": [5, 60, 95, 75], "content": "after"},
            ]
        ),
        recovered={
            "tables": [],
            "formulas": [],
            "figures": [
                {
                    "source_block_index": 2,
                    "caption": "Figure 1",
                    "description": "A local mocked schematic.",
                }
            ],
        },
    )

    assert [item["type"] for item in result["layout"]] == ["text", "figure", "table", "text"]
    assert [item["status"] for item in result["layout"]] == ["EXTRACTED"] * 4
    assert result["elements"]["figures"][0]["description"] == "A local mocked schematic."
    assert result["elements"]["figures"][0]["layout_id"] == result["layout"][1]["layout_id"]
    assert len(result["elements"]["tables"]) == 1
    assert result["reconciliation"]["complete"] is True


def test_process_page_layout_ledger_covers_figure_and_formula(monkeypatch):
    result = _run_layout_ledger_page(
        monkeypatch,
        _layout_raw(
            [
                {"index": 1, "label": "text", "bbox_2d": [5, 5, 95, 15], "content": "before"},
                {"index": 2, "label": "image", "bbox_2d": [5, 20, 45, 55], "content": ""},
                {"index": 3, "label": "formula", "bbox_2d": [50, 20, 95, 35], "content": "x=y+z"},
                {"index": 4, "label": "text", "bbox_2d": [5, 60, 95, 75], "content": "after"},
            ]
        ),
        recovered={
            "tables": [],
            "formulas": [],
            "figures": [
                {
                    "source_block_index": 2,
                    "caption": "Figure 1",
                    "description": "A mocked diagram beside a formula.",
                }
            ],
        },
    )

    assert [item["type"] for item in result["layout"]] == ["text", "figure", "formula", "text"]
    assert result["elements"]["formulas"][0]["latex"] == "x=y+z"
    assert result["elements"]["formulas"][0]["reading_order"] == 3
    assert result["elements"]["figures"][0]["description"] == "A mocked diagram beside a formula."
    assert result["reconciliation"]["complete"] is True


def test_process_page_layout_failure_does_not_stop_other_mixed_objects(monkeypatch):
    result = _run_layout_ledger_page(
        monkeypatch,
        _layout_raw(
            [
                {"index": 1, "label": "text", "bbox_2d": [5, 5, 95, 15], "content": "before"},
                {"index": 2, "label": "table", "bbox_2d": [5, 20, 95, 40], "content": ""},
                {"index": 3, "label": "image", "bbox_2d": [5, 45, 45, 70], "content": ""},
                {"index": 4, "label": "formula", "bbox_2d": [50, 45, 95, 60], "content": "x=y"},
                {"index": 5, "label": "text", "bbox_2d": [5, 75, 95, 90], "content": "after"},
            ]
        ),
        recovered={
            "tables": [],
            "formulas": [],
            "figures": [
                {
                    "source_block_index": 3,
                    "caption": "Figure 1",
                    "description": "Recovered figure while the table remains failed.",
                }
            ],
        },
    )

    assert [item["status"] for item in result["layout"]] == [
        "EXTRACTED",
        "FAILED",
        "EXTRACTED",
        "EXTRACTED",
        "EXTRACTED",
    ]
    assert result["layout"][1]["error"] == {
        "code": "layout_table_content_missing",
        "stage": "layout_content",
        "retryable": True,
    }
    assert result["elements"]["tables"] == []
    assert len(result["elements"]["figures"]) == 1
    assert len(result["elements"]["formulas"]) == 1
    assert result["layout"][-1]["content"] == "after"
    assert result["reconciliation"]["accounted_for"] is True
    assert result["reconciliation"]["complete"] is False
    assert result["reconciliation"]["failed"] == 1


def test_process_page_layout_recovery_rejects_wrong_explicit_layout_id(monkeypatch):
    result = _run_layout_ledger_page(
        monkeypatch,
        _layout_raw(
            [
                {"index": 1, "label": "text", "bbox_2d": [5, 5, 95, 15], "content": "before"},
                {"index": 2, "label": "image", "bbox_2d": [5, 20, 45, 55], "content": ""},
                {"index": 3, "label": "formula", "bbox_2d": [50, 20, 95, 35], "content": "x=y"},
            ]
        ),
        recovered={
            "tables": [],
            "formulas": [],
            "figures": [
                {
                    "layout_id": "p1-o999-figure",
                    "source_block_index": 2,
                    "caption": "Wrong correlation",
                    "description": "Must not attach by the weaker block index.",
                }
            ],
        },
    )

    assert result["layout"][1]["status"] == "FAILED"
    assert result["elements"]["figures"] == []
    assert result["reconciliation"]["unmatched_payload_layout_ids"] == ["p1-o999-figure"]
    assert result["layout"][2]["status"] == "EXTRACTED"


def test_process_page_layout_unknown_and_invalid_bbox_are_explicit_failures(monkeypatch):
    result = _run_layout_ledger_page(
        monkeypatch,
        _layout_raw(
            [
                {"index": 1, "label": "mystery", "bbox_2d": [5, 5, 95, 15], "content": "unknown"},
                {"index": 2, "label": "text", "bbox_2d": [], "content": "missing bbox"},
                {"index": 3, "label": "formula", "bbox_2d": [95, 20, 5, 30], "content": "x=y"},
                {"index": 4, "label": "text", "bbox_2d": [5, 35, 95, 45], "content": "after"},
            ]
        ),
    )

    assert [item["type"] for item in result["layout"]] == ["unknown", "text", "formula", "text"]
    assert result["layout"][0]["error"]["code"] == "unsupported_layout_type"
    assert result["layout"][1]["error"]["code"] == "layout_bbox_missing"
    assert result["layout"][2]["error"]["code"] == "layout_bbox_invalid"
    assert result["layout"][3]["status"] == "EXTRACTED"
    assert result["reconciliation"]["accounted_for"] is True
    assert result["reconciliation"]["complete"] is False


def test_process_page_layout_unavailable_preserves_legacy_output_but_is_not_complete(monkeypatch):
    text = "legacy fallback remains available"
    page = FakePage(
        text=text,
        blocks=[(0, 0, 100, 20, text, 0, 0)],
        dict_payload=_text_block_payload(text),
        rawdict_payload=_text_block_payload(text),
    )
    _patch_page_runtime(monkeypatch, page)

    result = page_processor.process_page(
        source_path="/tmp/legacy-fallback.pdf",
        page_no=1,
        policy="force_direct",
        vlm_config=None,
        routing_config={"render_cleanup_with_llm": False},
        prev_context=None,
    )

    assert result["render"]["markdown"]
    assert result["rag"]["elements"] == result["elements"]
    assert result["layout_status"] == "FAILED"
    assert result["layout_error"] == "layout_analysis_unavailable"
    assert result["reconciliation"]["identified"] is None
    assert result["reconciliation"]["accounted_for"] is False
    assert result["reconciliation"]["complete"] is False


def test_process_page_layout_ledger_can_be_disabled_for_rollback(monkeypatch):
    text = "legacy rollback path"
    page = FakePage(
        text=text,
        blocks=[(0, 0, 100, 20, text, 0, 0)],
        dict_payload=_text_block_payload(text),
        rawdict_payload=_text_block_payload(text),
    )
    _patch_page_runtime(monkeypatch, page)

    result = page_processor.process_page(
        source_path="/tmp/layout-disabled.pdf",
        page_no=1,
        policy="force_direct",
        vlm_config=None,
        routing_config={"layout_ledger_enabled": False, "render_cleanup_with_llm": False},
        prev_context=None,
    )

    assert result["render"]["markdown"]
    assert "layout" not in result
    assert "reconciliation" not in result
    assert "layout_status" not in result["decision"]
    assert "layout_error" not in result["decision"]


def test_layout_reconciliation_turns_missing_success_payload_into_explicit_failure():
    layout = [
        {
            "layout_id": "p1-o001-table",
            "type": "table",
            "status": "EXTRACTED",
            "payload_ref": None,
            "error": None,
        }
    ]

    reconciliation = page_processor.reconcile_layout(
        "EXTRACTED",
        layout,
        {"tables": [], "formulas": [], "figures": []},
    )

    assert layout[0]["status"] == "FAILED"
    assert layout[0]["error"] == {
        "code": "layout_payload_missing",
        "stage": "reconciliation",
        "retryable": True,
    }
    assert reconciliation["identified"] == 1
    assert reconciliation["extracted"] == 0
    assert reconciliation["failed"] == 1
    assert reconciliation["unmatched_layout_ids"] == ["p1-o001-table"]
    assert reconciliation["accounted_for"] is False
