import importlib.util
import sys
import types
from pathlib import Path

import fitz
import pytest


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
    is_pdf = True
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


def test_real_pdf_explicit_vlm_preserves_structured_element_contract(monkeypatch, tmp_path):
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
        policy="force_vlm",
        vlm_config={"provider": "fixture"},
        routing_config={
            "formula_score_region_vlm": 0.01,
            "table_score_region_vlm": 0.01,
            "ocr_config": {
                "glm_ocr": {
                    "enabled": False,
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
    assert not result["decision"]["fallback_reason"]
    assert result["decision"]["glm_calls"] == FixtureGLMOcrClient.calls == 0
    assert result["decision"]["vlm_calls"] == FixtureVLMClient.calls == 1
    assert result["semantic_status"]["complete"] is False
    assert result["semantic_status"]["missing"] == ["formulas[0].formula_name"]
    assert result["elements"]["formulas"][0]["semantic_status"] == "complete"

    table = result["elements"]["tables"][0]
    assert table["title"] == "Table 1 Fixture measurements"
    assert table["markdown"].splitlines()[-1] == "| beta | 2.50 |"
    assert table["semantic_summary"] == "Table 1 Fixture measurements: Synthetic calibration values for the local persistence contract."
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


def test_full_glm_keeps_usable_markdown_without_implicit_structured_fallback(monkeypatch, tmp_path):
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
    assert result["decision"]["vlm_calls"] == 0
    assert result["decision"]["glm_calls"] == 1
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

    semantic_calls = []
    def semantics(self, page_text, semantic_objects):
        semantic_calls.append(semantic_objects)
        assert semantic_objects[0]["latex"] == "t=\\frac{pD}{2\\sigma\\phi-p}"
        return {"formulas": [{"object_ref": "formulas:0", "formula_name": "壁厚计算公式",
                               "description": "用于计算承压部件所需壁厚。"}]}
    monkeypatch.setattr(FakeVLMClient, "describe_formulas_text", semantics, raising=False)

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
    assert result["elements"]["formulas"][0]["latex"] == r"t=\frac{pD}{2\sigma\phi-p}"
    assert result["semantic_status"]["complete"] is False
    assert result["semantic_status"]["reason"] == "docs_semantics_pending"
    assert len(semantic_calls) == result["decision"]["vlm_calls"] == 0


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


def test_scanned_page_returns_glm_failure_without_fallback(monkeypatch):
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

    monkeypatch.setattr(FakeVLMClient, 'full_page_dual_output', lambda *args: pytest.fail('unexpected fallback'))
    with pytest.raises(ValueError, match='ocr_conversion_failed'):
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

    assert result['route_selected'] == 'full_glm_ocr'
    assert result['decision']['glm_calls'] == 1
    assert result['decision']['vlm_calls'] == 0
    assert result['render']['markdown'] == '7 结构\n\n7.1 总体结构'
    assert result['elements']['figures'] == []
    assert result['semantic_status']['complete'] is False
    assert 'figure_description' in result['semantic_status']['missing']


def test_bad_glm_markdown_returns_failure_without_fallback(monkeypatch):
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

    monkeypatch.setattr(FakeVLMClient, 'full_page_dual_output', lambda *args: pytest.fail('unexpected fallback'))
    with pytest.raises(ValueError, match='ocr_conversion_failed'):
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
    calls = []
    crop_results = []
    crop_calls = []

    def __init__(self, cfg, source="glm_ocr"):
        self.enabled = bool((cfg or {}).get("enabled"))
        self.use_layout_parsing = True
        self.source = source

    def parse_layout(self, image_path, return_crop_images=False, need_layout_visualization=False):
        type(self).calls.append(str(image_path))
        if self.request_guard is not None:
            self.request_guard()
        _ = return_crop_images
        _ = need_layout_visualization
        assert "layout-recovery-" not in str(image_path), "layout endpoint is not an object content contract"
        return self.raw

    def extract_page(self, image_path):
        _ = image_path
        return OcrResult(markdown=str(self.raw.get("md_results") or ""))

    def extract_table_html(self, image_path):
        type(self).crop_calls.append(str(image_path))
        if self.request_guard is not None:
            self.request_guard()
        self.last_object_call_info = {"finish_reason": "stop", "json_status": "html"}
        return type(self).crop_results.pop(0) if type(self).crop_results else ""


class LayoutLedgerVLMClient:
    recovered = {"tables": [], "formulas": [], "figures": []}
    calls = 0
    last_blocks = []
    last_image_paths = []
    configs = []
    physical_requests = 0

    def __init__(self, cfg):
        type(self).configs.append(dict(cfg or {}))
        self.enabled = bool(cfg)
        self.provider = "fixture"
        self.model = "fixture-vlm"
        self.base_url = "local://fixture"
        self.timeout_sec = 5
        self.max_retries = 0
        self.last_call_info = {}
        self.last_dual_output_budget = {}
        self.physical_request_limit = (cfg or {}).get("table_analysis_max_physical_requests", 0)
        type(self).physical_requests = 0

    def _count_physical_request(self, _request=None):
        if type(self).physical_requests >= self.physical_request_limit:
            raise RuntimeError("vlm_physical_budget_exhausted")
        type(self).physical_requests += 1

    def extract_object_structured(self, image_path, block, compact=False):
        _ = compact
        self._count_physical_request()
        type(self).calls += 1
        type(self).last_blocks = [block]
        type(self).last_image_paths.append(str(image_path))
        self.last_object_call_info = {"json_status": "object", "finish_reason": "stop"}
        collection = {"table": "tables", "formula": "formulas", "figure": "figures"}[block["type"]]
        values = self.recovered.get(collection, [])
        if not values:
            return {"layout_id": block["layout_id"], "type": block["type"], "status": "FAILED", "complete": False}
        value = {**values[0], "type": block["type"], "status": "EXTRACTED", "complete": True}
        if block.get("recovery_target") == "table_content_with_cell_images":
            value.setdefault("contains_images", False)
        return value

    def extract_table_html(self, image_path, block, compact=False):
        result = self.extract_object_structured(image_path, block, compact=compact)
        self.last_object_call_info["json_status"] = "html"
        return result.get("markdown", "")

    def cleanup_markdown_table_noise(self, markdown_text):
        return markdown_text


def _run_layout_ledger_page(monkeypatch, raw, recovered=None, recovery_max_objects=0, crop_results=None,
                            request_limit=2):
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
    crop_calls = []

    def fake_crop(image_path, block, output_dir, padding_ratio=0.02, source_dpi=150):
        _ = image_path
        _ = output_dir
        crop_calls.append({"layout_id": block["layout_id"], "bbox": list(block["bbox"])})
        return Path(f"/tmp/layout-recovery-{block['layout_id']}.png"), {
            "pixel_bbox": [8, 8, 92, 92],
            "width": 84,
            "height": 84,
            "padding_ratio": padding_ratio,
        }

    monkeypatch.setattr(page_processor, "_crop_layout_block_image", fake_crop, raising=False)
    monkeypatch.setattr(page_processor, "_shrink_recovery_image", lambda path, info, scale: (path, info))
    LayoutLedgerGLMOcrClient.raw = raw
    LayoutLedgerGLMOcrClient.calls = []
    LayoutLedgerGLMOcrClient.crop_results = list(crop_results or [])
    LayoutLedgerGLMOcrClient.crop_calls = []
    LayoutLedgerVLMClient.recovered = recovered or {"tables": [], "formulas": [], "figures": []}
    LayoutLedgerVLMClient.calls = 0
    LayoutLedgerVLMClient.last_blocks = []
    LayoutLedgerVLMClient.last_image_paths = []
    LayoutLedgerVLMClient.configs = []
    LayoutLedgerVLMClient.physical_requests = 0
    result = page_processor.process_page(
        source_path="/tmp/layout-fixture.pdf",
        page_no=1,
        policy="force_direct",
        vlm_config={"provider": "fixture", "table_analysis_max_model_calls": request_limit}
                   if recovered is not None else None,
        routing_config={
            "ocr_config": {
                "glm_ocr": {
                    "enabled": True,
                    "model": "glm-ocr",
                    "api_key": "unused",
                    "base_url": "local://fixture",
                }
            },
            "layout_recovery_max_objects": recovery_max_objects,
            "render_cleanup_with_llm": False,
        },
        prev_context=None,
    )
    if ((recovered is not None or crop_results) and isinstance(result.get('_docs_raw_layout'), dict)
            and '_docs_layout_snapshot' not in result['_docs_raw_layout']):
        original_layout = result['_docs_raw_layout']
        ids = [item['layout_id'] for item in result.get('layout', []) if item.get('type') == 'table']
        figure_ids = [item['layout_id'] for item in result.get('layout', []) if item.get('type') == 'figure']
        result = page_processor.process_page(
            source_path='/tmp/layout-fixture.pdf', page_no=1, policy='force_direct',
            vlm_config={'provider': 'fixture', 'table_analysis_max_model_calls': request_limit},
            routing_config={'ocr_config': {'glm_ocr': {'enabled': True, 'model': 'glm-ocr',
                'api_key': 'unused', 'base_url': 'local://fixture'}},
                'layout_recovery_max_objects': recovery_max_objects, 'render_cleanup_with_llm': False,
                'docs_recovery_phase': 'recover', '__docs_saved_layout': original_layout,
                'docs_recovery_selection': {'tables': ids, 'table_images': ids,
                    'figures': figure_ids, 'visual_types': figure_ids,
                    'table_provider_plan': ['glm_ocr', 'vlm_ocr', 'vlm_ocr'],
                    'image_provider_plan': ['vlm_ocr', 'vlm_ocr'],
                    'visual_provider_plan': ['vlm_ocr', 'vlm_ocr'],
                    'table_model_budget': 3 * min(len(ids), recovery_max_objects),
                    'image_model_budget': 2 * min(len(ids), recovery_max_objects),
                    'visual_model_budget': 2 * min(len(figure_ids), recovery_max_objects)}}, prev_context=None)
    result["_fixture_crop_calls"] = crop_calls
    return result


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
    assert result["source_page_width"] == 100
    assert result["source_page_height"] == 100
    assert result["source_bbox_space"] == "pixel_page"
    assert result["source_page_index"] == 0
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
    assert result["_fixture_crop_calls"] == []


def test_layout_recovery_crop_clamps_bbox_and_keeps_small_padding(tmp_path):
    source = tmp_path / "page.png"
    pixmap = page_processor.fitz.Pixmap(page_processor.fitz.csRGB, page_processor.fitz.IRect(0, 0, 100, 80), False)
    pixmap.clear_with(255)
    pixmap.save(str(source))

    cropped, crop_info = page_processor._crop_layout_block_image(
        source,
        {"layout_id": "p1-o002-table", "bbox": [0.0, 0.0, 0.2, 0.2]},
        tmp_path,
        padding_ratio=0.02,
    )

    cropped_pixmap = page_processor.fitz.Pixmap(str(cropped))
    assert crop_info == {
        "pixel_bbox": [0, 0, 22, 18],
        "width": 22,
        "height": 18,
        "padding_ratio": 0.02,
    }
    assert (cropped_pixmap.width, cropped_pixmap.height) == (22, 18)


def test_layout_caption_survives_table_recovery_without_reusing_previous_title(monkeypatch):
    table = "<table><tr><td>A</td></tr></table>"
    result = _run_layout_ledger_page(monkeypatch, _layout_raw([
        {"label": "table_caption", "bbox_2d": [10, 1, 90, 8], "content": "表 8（续）"},
        {"label": "table", "bbox_2d": [10, 10, 90, 40], "content": table},
        {"label": "table_caption", "bbox_2d": [10, 42, 90, 48], "content": "表 9 修正系数"},
        {"label": "table", "bbox_2d": [10, 50, 90, 90], "content": "<table><tr><td>"},
    ]), recovered={"tables": [{"layout_id": "p1-o004-table", "markdown": table.replace("A", "B")}]})
    assert [t['title'] for t in result['elements']['tables']] == ['表 8（续）']
    assert result['layout'][3]['title'] == '表 9 修正系数'
    assert result['layout'][3]['status'] == 'FAILED'
    assert LayoutLedgerVLMClient.calls == 0


def test_layout_caption_overrides_recovery_candidate_title(monkeypatch):
    table = "<table><tr><td>A</td></tr></table>"
    result = _run_layout_ledger_page(monkeypatch, _layout_raw([
        {"label": "table_caption", "bbox_2d": [10, 1, 90, 8], "content": "表 8（续）"},
        {"label": "table", "bbox_2d": [10, 10, 90, 40], "content": table},
        {"label": "table_caption", "bbox_2d": [10, 42, 90, 48], "content": "表 9 修正系数"},
        {"label": "table", "bbox_2d": [10, 50, 90, 90], "content": "<table><tr><td>"},
    ]), recovered={"tables": [{
        "layout_id": "p1-o004-table", "markdown": table.replace("A", "B"), "title": "表 8（续）"
    }]})
    assert [t['title'] for t in result['elements']['tables']] == ['表 8（续）']
    assert result['layout'][3]['title'] == '表 9 修正系数'
    assert result['layout'][3]['status'] == 'FAILED'
    assert LayoutLedgerVLMClient.calls == 0


def test_layout_untitled_table_does_not_inherit_first_page_caption(monkeypatch):
    result = _run_layout_ledger_page(monkeypatch, _layout_raw([
        {"label": "table_caption", "bbox_2d": [10, 1, 90, 8], "content": "表 8（续）"},
        {"label": "table", "bbox_2d": [10, 10, 90, 40], "content": "<table><tr><td>A</td></tr></table>"},
        {"label": "table", "bbox_2d": [10, 50, 90, 90], "content": "<table><tr><td>B</td></tr></table>"},
    ]))
    assert result["elements"]["tables"][1]["title"] == ""


@pytest.mark.parametrize("caption,box", [
    ("图 3 示意图", [10, 1, 90, 8]),
    ("表 3 系数", [1, 1, 9, 8]),
    ("表 3 系数", [10, 50, 90, 60]),
])
def test_table_caption_requires_table_evidence_and_matching_geometry(caption, box):
    outcome = page_processor.build_layout_outcome(_layout_raw([
        {"label": "caption", "bbox_2d": box, "content": caption},
        {"label": "table", "bbox_2d": [10, 10, 90, 40], "content": "<table><tr><td>A</td></tr></table>"},
    ]), 1, 100, 100)
    assert outcome["payloads"]["tables"][0]["title"] == ""


def test_legacy_table_title_fallback_does_not_guess_on_multi_caption_page():
    assert page_processor._title_for_table("<table></table>", ["表 8（续）", "表 9 系数"]) == ""
    # Even a single caption must not be reassigned to a layout object without a bound title.
    elements = page_processor._build_layout_output_elements("表 8（续）", {"tables": [
        {"layout_id": "p1-o004-table", "markdown": "<table><tr><td>B</td></tr></table>"}
    ]}, "glm_ocr_layout")
    assert elements["tables"][0]["title"] == ""


def test_process_page_layout_uses_object_content_contract_for_original_layout_id(monkeypatch):
    complete = "<table><tr><td>A</td><td>B</td></tr><tr><td>1</td><td>2</td></tr></table>"
    incomplete = "<table><tr><td>C</td><td>D</td></tr><tr><td>3</td><td>"
    recovered = "<table><tr><td>C</td><td>D</td></tr><tr><td>3</td><td>4</td></tr></table>"
    result = _run_layout_ledger_page(
        monkeypatch,
        _layout_raw(
            [
                {"index": 10, "label": "table", "bbox_2d": [10, 10, 90, 40], "content": complete},
                {"index": 20, "label": "table", "bbox_2d": [10, 50, 90, 90], "content": incomplete},
            ]
        ),
        recovered={"tables": [{"layout_id": "p1-o002-table", "markdown": recovered}]},
    )

    assert result['_fixture_crop_calls'] == []
    assert LayoutLedgerVLMClient.calls == 0
    assert LayoutLedgerGLMOcrClient.calls == ['/tmp/layout-page.png']
    item = result['layout'][1]
    assert item['layout_id'] == 'p1-o002-table'
    assert item['reading_order'] == 2
    assert item['bbox'] == [0.1, 0.5, 0.9, 0.9]
    assert item['status'] == 'FAILED'
    assert item['content'] == incomplete
    assert [t['markdown'] for t in result['elements']['tables']] == [complete]
    assert result['reconciliation']['complete'] is False


def test_process_page_recovers_successfully_parsed_incomplete_table_from_its_crop(monkeypatch):
    incomplete = "<table><tr><td>参数</td></tr><tr><td>未闭合"
    recovered = "<table><tr><td>参数</td></tr><tr><td>完整值</td></tr></table>"
    raw = _layout_raw([
        {"label": "table", "bbox_2d": [10, 20, 90, 90], "content": incomplete},
    ], markdown="表8-5浮头法兰计算\n\n" + incomplete)
    result = _run_layout_ledger_page(monkeypatch, raw, recovery_max_objects=1,
                                     crop_results=[recovered])

    assert len(LayoutLedgerGLMOcrClient.calls) == 1
    assert len(LayoutLedgerGLMOcrClient.crop_calls) == 1
    assert LayoutLedgerVLMClient.configs[0]["table_analysis_max_model_calls"] == 2
    assert LayoutLedgerVLMClient.configs[0]["table_analysis_max_physical_requests"] == 2
    assert result["layout"][0]["status"] == "EXTRACTED"
    assert result["layout"][0]["error"] is None
    assert result["layout_recovery"]["objects"][0]["outcome"] == "content_recovered_image_pending"
    assert result["elements"]["tables"][0]["markdown"] == recovered
    assert recovered in result["render"]["markdown"]
    assert incomplete not in result["render"]["markdown"]
    assert result["reconciliation"]["complete"] is True


def test_incomplete_table_recovers_content_then_cell_images(monkeypatch):
    incomplete = "<table><tr><td>参数</td></tr><tr><td>未闭合"
    recovered = "<table><tr><td>参数</td></tr><tr><td>完整值</td></tr></table>"
    raw = _layout_raw([
        {"label": "table", "bbox_2d": [10, 20, 90, 90], "content": incomplete},
    ], markdown="表8-5浮头法兰计算\n\n" + incomplete)
    candidate = {
        "layout_id": "p1-o001-table", "type": "table", "status": "EXTRACTED", "complete": True,
        "markdown": recovered, "contains_images": True,
        "source_cells": [{"row": 1, "col": 0, "rowspan": 1, "colspan": 1,
                           "bbox": [0.1, 0.1, 0.9, 0.9], "bbox_space": "normalized_crop",
                           "image_regions": [{"image_id": "diagram", "bbox": [0.2, 0.2, 0.8, 0.8],
                                              "bbox_space": "normalized_crop"}]}],
    }
    monkeypatch.setattr(page_processor, "_validate_cell_image_recovery", lambda block, payload, crop_info, image_path: ("", payload))
    monkeypatch.setattr(page_processor, "_table_image_problem", lambda table: False)
    monkeypatch.setattr(page_processor, "_attach_figure_assets", lambda *args, **kwargs: None)
    result = _run_layout_ledger_page(
        monkeypatch, raw, recovered={"tables": [candidate]}, recovery_max_objects=1,
        crop_results=[incomplete],
    )

    assert LayoutLedgerGLMOcrClient.crop_calls
    assert LayoutLedgerVLMClient.calls == 2
    assert result["decision"]["provider_requests"] == {
        "glm_ocr": 1, "vlm_ocr": 2, "limits": {"glm_ocr": 2, "vlm_ocr": 2},
        "limit_scope": "per_object_operation",
    }
    assert LayoutLedgerVLMClient.last_blocks[0]["recovery_target"] == "cell_images"
    assert result["layout_recovery"]["objects"][0]["outcome"] == "recovered"
    assert result["elements"]["tables"][0]["contains_images"] is True


def test_complete_ocr_crop_still_runs_vlm_and_keeps_ocr_table_source(monkeypatch):
    incomplete = "<table><tr><td>参数</td></tr><tr><td>未闭合"
    ocr_table = "<table><tr><td>OCR 表格正文</td></tr></table>"
    vlm_table = "<table><tr><td>VLM 改写正文</td></tr></table>"
    raw = _layout_raw([
        {"label": "table", "bbox_2d": [10, 20, 90, 90], "content": incomplete},
    ], markdown="表8-5\n\n" + incomplete)
    result = _run_layout_ledger_page(
        monkeypatch, raw, recovered={"tables": [{"markdown": vlm_table}],
                                     "formulas": [], "figures": []},
        recovery_max_objects=1, crop_results=[ocr_table],
    )

    assert 1 <= LayoutLedgerVLMClient.calls <= 2
    assert result["elements"]["tables"][0]["markdown"] == ocr_table
    assert result["decision"]["provider_requests"]["glm_ocr"] == 1
    assert result["decision"]["provider_requests"]["vlm_ocr"] == 2


@pytest.mark.parametrize("request_limit", [1, 2])
def test_configured_provider_budget_preserves_recovered_content(monkeypatch, request_limit):
    html = "<table><tr><td>Recovered source</td></tr></table>"
    raw = _layout_raw([{"label": "table", "bbox_2d": [10, 20, 90, 90],
                       "content": "<table><tr><td>incomplete"}])
    result = _run_layout_ledger_page(
        monkeypatch, raw, recovered={"tables": [{"layout_id": "p1-o001-table", "markdown": html,
            "contains_images": False, "source_cells": [], "image_unresolved": []}]},
        recovery_max_objects=1, crop_results=[html], request_limit=request_limit,
    )
    budget = result["decision"]["provider_requests"]
    assert budget["limits"] == {"glm_ocr": request_limit, "vlm_ocr": request_limit}
    assert budget["limit_scope"] == "per_object_operation"
    # Page layout and targeted table content have independent finite caps.
    assert budget["glm_ocr"] <= 2 * request_limit
    assert budget["vlm_ocr"] <= request_limit
    assert len(result["elements"]["tables"]) == 1
    assert result["elements"]["tables"][0]["markdown"] == html


@pytest.mark.parametrize("image_signal", [False, True])
def test_cell_image_layout_recovery_only_runs_for_explicit_image_signal(monkeypatch, image_signal):
    table = {
        "label": "table", "bbox_2d": [10, 20, 90, 90],
        "content": "<table><tr><td>参数</td></tr></table>",
    }
    if image_signal:
        table.update(contains_images=True, image_unresolved=[{"reason": "missing_cell_image_geometry"}])
    raw = _layout_raw([table])
    calls = []
    def recover(*args, **kwargs):
        calls.append(args[2])
        return 0, 0, {"objects": []}
    monkeypatch.setattr(page_processor, "_recover_missing_table_images", recover)
    monkeypatch.setattr(page_processor, "_attach_figure_assets", lambda *args, **kwargs: None)

    _run_layout_ledger_page(monkeypatch, raw, recovered={"tables": []}, recovery_max_objects=1)

    assert len(calls) == int(image_signal)


@pytest.mark.parametrize(
    "truncated_tail",
    [
        "<tr><td>0.00</td><td>1.000</td><td>1.000</td><td>0.980</td><td>0.95",
        "<tr><td>0.00</td><td>1.000</td><td>1.000</td><td>0.980</td><td>0.950</td><td>0.90",
    ],
)
def test_process_page_layout_retains_incomplete_large_table_for_docs(monkeypatch, truncated_tail):
    first = "<table><tr><td>A</td><td>B</td></tr><tr><td>1</td><td>2</td></tr></table>"
    incomplete = (
        "<table><tr><td rowspan=\"2\">ratio</td><td colspan=\"6\">coefficients</td></tr>"
        "<tr><td>0.2</td><td>0.4</td><td>0.6</td><td>0.8</td><td>1.0</td><td>1.2</td></tr>"
        + truncated_tail
    )
    recovered = (
        "<table><tr><td rowspan=\"2\">ratio</td><td colspan=\"6\">coefficients</td></tr>"
        "<tr><td>0.2</td><td>0.4</td><td>0.6</td><td>0.8</td><td>1.0</td><td>1.2</td></tr>"
        "<tr><td>0.00</td><td>1.000</td><td>1.000</td><td>0.980</td><td>0.950</td><td>0.900</td><td>0.850</td></tr>"
        "</table>"
    )
    result = _run_layout_ledger_page(
        monkeypatch,
        _layout_raw(
            [
                {"index": 1, "label": "table", "bbox_2d": [8, 8, 92, 42], "content": first},
                {"index": 2, "label": "table", "bbox_2d": [8, 48, 92, 98], "content": incomplete},
            ]
        ),
        recovered={"tables": [{"layout_id": "p1-o002-table", "markdown": recovered}]},
    )

    assert [item['status'] for item in result['layout']] == ['EXTRACTED', 'FAILED']
    assert result['layout'][1]['content'] == incomplete
    assert result['layout'][1]['bbox'] == [0.08, 0.48, 0.92, 0.98]
    assert [t['markdown'] for t in result['elements']['tables']] == [first]
    assert result['_fixture_crop_calls'] == []
    assert LayoutLedgerVLMClient.calls == 0


def test_process_page_layout_isolates_incomplete_second_html_table(monkeypatch):
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

    assert LayoutLedgerVLMClient.calls == 0
    assert [item['status'] for item in result['layout']] == ['EXTRACTED', 'FAILED']
    assert [item['reading_order'] for item in result['layout']] == [1, 2]
    assert [item['bbox'] for item in result['layout']] == [first_bbox, second_bbox]
    assert result['layout'][1]['content'] == incomplete_second
    assert result['elements']['tables'][0]['markdown'] == first
    assert result['elements']['tables'][0]['source'] == 'glm_ocr_layout'
    assert len(result['elements']['tables']) == 1
    assert result['reconciliation']['complete'] is False


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

    assert LayoutLedgerVLMClient.calls == 0
    assert LayoutLedgerVLMClient.last_blocks == []
    assert [item["status"] for item in result["layout"]] == ["EXTRACTED", "FAILED"]
    assert result["layout"][1]["error"] == {
        "code": "layout_table_content_incomplete",
        "stage": "layout_content",
        "retryable": True,
    }
    assert result["layout"][1]["review_required"] is True
    assert result["layout"][1]["content"] == incomplete_second
    assert [item["markdown"] for item in result["elements"]["tables"]] == [first]
    assert result["reconciliation"]["accounted_for"] is True
    assert result["reconciliation"]["complete"] is False
    assert result["reconciliation"]["review_required_layout_ids"] == ["p1-o002-table"]
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
                    "layout_id": "p1-o002-figure",
                    "source_block_index": 2,
                    "caption": "Figure 1",
                    "description": "A local mocked schematic.",
                }
            ],
        },
    )

    assert [item["type"] for item in result["layout"]] == ["text", "figure", "table", "text"]
    assert [item["status"] for item in result["layout"]] == ["EXTRACTED", "FAILED", "EXTRACTED", "EXTRACTED"]
    assert result["elements"]["figures"][0]["description"] == ""
    assert LayoutLedgerVLMClient.calls == 0
    assert result["elements"]["figures"][0]["layout_id"] == result["layout"][1]["layout_id"]
    assert len(result["elements"]["tables"]) == 1
    assert result["reconciliation"]["complete"] is False


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
                    "layout_id": "p1-o002-figure",
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
    assert result["elements"]["figures"][0]["description"] == ""
    assert LayoutLedgerVLMClient.calls == 0
    assert result["reconciliation"]["complete"] is False


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
                    "layout_id": "p1-o003-figure",
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
        "FAILED",
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
    assert result["reconciliation"]["failed"] == 2


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
    assert len(result["elements"]["figures"]) == 1
    retained = result["elements"]["figures"][0]
    assert retained["layout_id"] == "p1-o002-figure"
    assert retained["content_status"] == "geometry_only"
    assert retained["description"] == ""
    assert "Wrong correlation" not in str(retained)
    assert result["reconciliation"]["unmatched_payload_layout_ids"] == []
    assert LayoutLedgerVLMClient.calls == 0
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


def test_full_html_table_semantics_use_title_instead_of_zero_dimensions():
    html = '<table><tr><td rowspan="2">气体</td><td>水</td></tr><tr><td>可用</td></tr></table>'
    assert page_processor._table_summary('', html, 'zh') == ''
    structured = page_processor._normalize_structured({'tables': [
        {'title': '表 1 灭火剂', 'markdown': html, 'description': '比较灭火剂适用性。'}]})
    table = page_processor._build_output_elements('', structured, 'full_glm_ocr', 'zh')['tables'][0]
    assert '表 1 灭火剂' in table['semantic_summary']
    assert '比较灭火剂适用性' in table['semantic_summary']
    assert table['markdown'] == html


def test_formula_context_placeholder_is_not_semantic_description():
    assert page_processor._formula_summary('', 'zh') == ''


@pytest.mark.parametrize('cell,expected,review', [
    ('150~475^{a}$', '$150~475^{a}$', False),
    ('≤475^{a}$', '$≤475^{a}$', False),
    ('$x_{i}^{2}', '$x_{i}^{2}$', False),
    ('$x_{i}^{2}$', '$x_{i}^{2}$', False),
    ('$$x_{i}^{2}$$', '$$x_{i}^{2}$$', False),
    (r'\(x_i\)', r'\(x_i\)', False),
    ('$5.00', '$5.00', False),
    (r'price \$5', r'price \$5', False),
    ('cost $5 and $10', 'cost $5 and $10', False),
    ('unreadable $', 'unreadable $', True),
    ('x_{i$','x_{i$', True),
    ('<b>x_i</b>$', '<b>x_i</b>$', True),
    ('$x_i$$', '$x_i$$', True),
])
def test_table_cell_math_boundary_contract(monkeypatch, cell, expected, review):
    table = f'<table><tr><th rowspan="2">{cell}</th><td>stable</td></tr><tr><td>2</td></tr></table>'
    raw = _layout_raw([
        {'label': 'table', 'bbox_2d': [10, 10, 90, 50], 'content': table},
        {'label': 'formula', 'bbox_2d': [10, 60, 90, 80], 'content': '$$E=mc^2$$'},
    ])
    raw['md_results'] = table + '\n\n$$E=mc^2$$'
    result = _run_layout_ledger_page(monkeypatch, raw)
    output = result['elements']['tables'][0]
    assert output['markdown'] == table.replace(cell, expected)
    assert table.replace(cell, expected) in result['render']['markdown']
    assert len(result['elements']['tables']) == 1
    assert [f['latex'] for f in result['elements']['formulas']] == ['$$E=mc^2$$']
    assert result['layout'][0]['review_required'] is review
    assert result['reconciliation']['complete'] is (not review)
    if cell != expected or review:
        assert output['original_content'] == table
    if review:
        assert output['manualReviewRequired'] is True
        assert result['reconciliation']['review_required_layout_ids'] == ['p1-o001-table']


def test_table_math_never_pairs_across_cells_or_tables(monkeypatch):
    tables = ['<table><tr><td>x_i$</td><td>$y_j</td></tr></table>',
              '<table><tr><td>unknown $</td><td>text</td></tr></table>']
    raw = _layout_raw([{'label': 'table', 'bbox_2d': [10, 10+i*40, 90, 40+i*40], 'content': t}
                       for i, t in enumerate(tables)])
    result = _run_layout_ledger_page(monkeypatch, raw)
    assert [t['markdown'] for t in result['elements']['tables']] == [
        '<table><tr><td>$x_i$</td><td>$y_j$</td></tr></table>', tables[1]]
    assert [t['layout_id'] for t in result['elements']['tables']] == ['p1-o001-table', 'p1-o002-table']
    assert result['elements']['formulas'] == []


@pytest.mark.parametrize('cell,review', [('x_i$', False), ('unknown $', True)])
def test_recovered_table_math_uses_same_boundary_and_quality_contract(monkeypatch, cell, review):
    table = f'<table><tr><td colspan="2">{cell}</td></tr></table>'
    outcome = page_processor.build_layout_outcome(_layout_raw([
        {'label': 'table', 'bbox_2d': [10,10,90,90], 'content': '<table><tr><td>'},
    ]), 1, 100, 100)
    page_processor.apply_recovered_payloads(outcome, {'tables': [{'layout_id': 'p1-o001-table', 'markdown': table}]})
    elements = page_processor._build_layout_output_elements('', outcome['payloads'], 'glm_ocr_layout')
    result = {'layout': outcome['layout'], 'elements': elements,
              'reconciliation': page_processor.reconcile_layout(outcome['layout_status'], outcome['layout'], elements)}
    output = result['elements']['tables'][0]
    assert output['markdown'] == (table if review else table.replace('x_i$', '$x_i$'))
    assert output['original_content'] == table
    assert result['layout'][0]['review_required'] is review
    assert result['reconciliation']['complete'] is (not review)
    assert result['elements']['formulas'] == []


def test_table_math_preserves_duplicate_identity_tags_and_entities(monkeypatch):
    table = '<TABLE data-note="$"><TR>\n<TD colspan="2"> x_i$ </TD><TD>&amp;<sup>a</sup></TD></TR></TABLE>'
    raw = _layout_raw([
        {'index': i, 'label': 'table', 'bbox_2d': [10, 10+i*40, 90, 40+i*40], 'content': table}
        for i in range(2)
    ], markdown=table + '\n\n' + table)
    result = _run_layout_ledger_page(monkeypatch, raw)
    assert [t['markdown'] for t in result['elements']['tables']] == [table.replace('x_i$', '$x_i$')] * 2
    assert [t['source_block_index'] for t in result['elements']['tables']] == [0, 1]
    assert result['reconciliation']['complete'] is True
    assert result['elements']['formulas'] == []
