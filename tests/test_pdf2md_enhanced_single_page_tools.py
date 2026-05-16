import base64
import importlib.util
import json
import sys
import types
from pathlib import Path

import fitz


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "pdf2md_enhanced_single_page_testpkg"


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
page_processor = _load_module(f"{PACKAGE_NAME}.page_processor", ROOT / "mcp/servers/PDF2MDEnhanced/page_processor.py")
single_page_tools = _load_module(f"{PACKAGE_NAME}.single_page_tools", ROOT / "mcp/servers/PDF2MDEnhanced/single_page_tools.py")

OcrElement = sys.modules[f"{PACKAGE_NAME}.ocr_clients.ocr_models"].OcrElement
OcrResult = sys.modules[f"{PACKAGE_NAME}.ocr_clients.ocr_models"].OcrResult


PNG_DATA = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode("ascii")


class FakeGLMOcrClient:
    result = None
    error = None
    prompts = []

    def __init__(self, cfg, source="glm_ocr"):
        self.enabled = bool((cfg or {}).get("enabled"))
        self.source = source

    def extract_page(self, image_path, prompt=None):
        _ = image_path
        self.__class__.prompts.append(prompt or "")
        if self.error:
            raise RuntimeError(self.error)
        if self.result is not None:
            return self.result
        return OcrResult(
            tables=[OcrElement(kind="table", source="glm_ocr", markdown="| A | B |\n| --- | --- |\n| 1 | 2 |")],
            formulas=[OcrElement(kind="formula", source="glm_ocr", latex="x=y+z")],
            figures=[OcrElement(kind="figure", source="glm_ocr", description="ignored figure")],
        )


class FakeVLMClient:
    enabled = True
    prompts = []

    def __init__(self, cfg):
        self.enabled = bool(cfg is not None)
        self.max_tokens = 4096

    def _call_image_prompt(self, image_path, prompt, max_tokens):
        _ = image_path
        _ = max_tokens
        self.__class__.prompts.append(prompt)
        if "Extract figures" in prompt:
            return json.dumps(
                {
                    "figures": [
                        {
                            "caption": "图 1",
                            "type": "diagram",
                            "description": "A technical diagram with D and R labels.",
                            "labels": ["D", "R"],
                        }
                    ],
                    "tables": [{"markdown": "| ignored |"}],
                    "formulas": [{"latex": "ignored"}],
                }
            )
        if "Extract formulas" in prompt:
            return json.dumps({"formulas": [{"latex": "a=b", "description": "formula desc"}], "tables": [], "figures": []})
        return json.dumps(
            {
                "tables": [{"title": "Table V", "markdown": "| C | D |\n| --- | --- |\n| 3 | 4 |"}],
                "formulas": [],
                "figures": [],
            }
        )


class FakeTable:
    def extract(self):
        return [["Name", "Value"], ["A", "1"]]


class FakeTableFinder:
    tables = [FakeTable()]


class FakePage:
    rect = fitz.Rect(0, 0, 100, 100)

    def get_text(self, mode):
        if mode == "text":
            return "表 1 参数表\n按下式计算。式中 x 为变量。"
        return []

    def find_tables(self):
        return FakeTableFinder()


class FakeDoc:
    def __len__(self):
        return 1

    def __getitem__(self, idx):
        assert idx == 0
        return FakePage()

    def close(self):
        return None


def _patch_clients(monkeypatch):
    monkeypatch.setattr(single_page_tools, "OpenAICompatibleOcrClient", FakeGLMOcrClient)
    monkeypatch.setattr(single_page_tools, "DynamicVLMClient", FakeVLMClient)
    FakeGLMOcrClient.result = None
    FakeGLMOcrClient.error = None
    FakeGLMOcrClient.prompts = []
    FakeVLMClient.prompts = []


def test_extract_page_tables_only_uses_table_items(monkeypatch):
    _patch_clients(monkeypatch)

    result = json.loads(
        single_page_tools.extract_page_tables_direct(
            file_data=PNG_DATA,
            input_type="image",
            ocr_config={"glm_ocr": {"enabled": True, "model": "glm", "api_key": "x", "base_url": "http://x"}},
            vlm_config={"model": "vlm", "api_key": "x", "base_url": "http://x"},
        )
    )

    assert result["tool"] == "extract_page_tables"
    assert len(result["items"]) == 1
    assert result["items"][0]["markdown"].startswith("| A | B |")
    assert result["model_calls"] == {"glm_ocr": 1, "vlm_ocr": 0}
    assert "Extract tables only" in FakeGLMOcrClient.prompts[0]


def test_extract_page_formulas_only_uses_formula_items(monkeypatch):
    _patch_clients(monkeypatch)

    result = json.loads(
        single_page_tools.extract_page_formulas_direct(
            file_data=PNG_DATA,
            input_type="image",
            ocr_config={"glm_ocr": {"enabled": True, "model": "glm", "api_key": "x", "base_url": "http://x"}},
            vlm_config={"model": "vlm", "api_key": "x", "base_url": "http://x"},
        )
    )

    assert result["tool"] == "extract_page_formulas"
    assert len(result["items"]) == 1
    assert result["items"][0]["latex"] == "x=y+z"
    assert "markdown" not in result["items"][0]
    assert result["model_calls"] == {"glm_ocr": 1, "vlm_ocr": 0}


def test_extract_page_figures_requires_vlm_and_ignores_other_items(monkeypatch):
    _patch_clients(monkeypatch)

    result = json.loads(
        single_page_tools.extract_page_figures_direct(
            file_data=PNG_DATA,
            input_type="image",
            ocr_config={"glm_ocr": {"enabled": True, "model": "glm", "api_key": "x", "base_url": "http://x"}},
            vlm_config={"model": "vlm", "api_key": "x", "base_url": "http://x"},
        )
    )

    assert result["tool"] == "extract_page_figures"
    assert len(result["items"]) == 1
    assert result["items"][0]["caption"] == "图 1"
    assert result["items"][0]["source"] == "vlm_ocr"
    assert result["model_calls"] == {"glm_ocr": 0, "vlm_ocr": 1}
    assert "Extract figures" in FakeVLMClient.prompts[0]


def test_extract_page_tables_pdf_uses_native_table_without_model(monkeypatch, tmp_path):
    _patch_clients(monkeypatch)
    pdf = tmp_path / "demo.pdf"
    pdf.write_bytes(b"%PDF fake")
    monkeypatch.setattr(single_page_tools.fitz, "open", lambda path: FakeDoc())
    monkeypatch.setattr(single_page_tools, "_render_page_image", lambda *args, **kwargs: tmp_path / "page.png")

    result = json.loads(single_page_tools.extract_page_tables_direct(file_path=str(pdf), page_no=1, input_type="pdf"))

    assert result["items"][0]["source"] == "pymupdf"
    assert "| Name | Value |" in result["items"][0]["markdown"]
    assert result["model_calls"] == {"glm_ocr": 0, "vlm_ocr": 0}


def test_extract_page_markdown_formats_same_result(monkeypatch):
    _patch_clients(monkeypatch)

    markdown = single_page_tools.extract_page_formulas_direct(
        file_data=PNG_DATA,
        input_type="image",
        output_format="markdown",
        ocr_config={"glm_ocr": {"enabled": True, "model": "glm", "api_key": "x", "base_url": "http://x"}},
    )

    assert "# Page 1 Formulas" in markdown
    assert "$$" in markdown
    assert "x=y+z" in markdown


def test_extract_page_structured_returns_separate_arrays(monkeypatch):
    _patch_clients(monkeypatch)

    result = json.loads(
        single_page_tools.extract_page_structured_direct(
            file_data=PNG_DATA,
            input_type="image",
            ocr_config={"glm_ocr": {"enabled": True, "model": "glm", "api_key": "x", "base_url": "http://x"}},
            vlm_config={"model": "vlm", "api_key": "x", "base_url": "http://x"},
        )
    )

    assert result["tool"] == "extract_page_structured"
    assert len(result["tables"]) == 1
    assert len(result["formulas"]) == 1
    assert len(result["figures"]) == 1
    assert result["semantic_status"]["complete"] is True
