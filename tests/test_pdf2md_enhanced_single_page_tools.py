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
normalize_text_response = sys.modules[f"{PACKAGE_NAME}.ocr_clients.ocr_normalizers"].normalize_text_response
OpenAICompatibleOcrClient = sys.modules[
    f"{PACKAGE_NAME}.ocr_clients.openai_compatible_ocr_client"
].OpenAICompatibleOcrClient


PNG_DATA = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode("ascii")


def test_glm_ocr_layout_file_payload_uses_data_uri():
    client = OpenAICompatibleOcrClient({})

    assert client._data_uri_for_file("/tmp/page.png", "abc") == "data:image/png;base64,abc"
    assert client._data_uri_for_file("/tmp/page.jpg", "abc") == "data:image/jpeg;base64,abc"
    assert client._data_uri_for_file("/tmp/page.pdf", "abc") == "data:application/pdf;base64,abc"


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

    def parse_layout(self, image_path, return_crop_images=False, need_layout_visualization=False):
        _ = image_path
        _ = return_crop_images
        _ = need_layout_visualization
        return {
            "md_results": "正文\n\n$$x=y+z$$",
            "layout_details": [
                [
                    {"index": 1, "label": "text", "bbox_2d": [0.1, 0.1, 0.8, 0.2], "content": "正文", "width": 100, "height": 20},
                    {
                        "index": 2,
                        "label": "formula",
                        "bbox_2d": [0.1, 0.3, 0.8, 0.4],
                        "content": "$$x=y+z$$",
                        "width": 100,
                        "height": 20,
                    },
                ]
            ],
            "data_info": {"num_pages": 1},
        }


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
        if "image blocks" in prompt:
            return json.dumps(
                {
                    "figures": [
                        {
                            "block_index": 3,
                            "bbox": [10, 10, 40, 40],
                            "caption": "图 1",
                            "type": "diagram",
                            "description": "A positioned technical diagram with D and R labels.",
                            "labels": ["D", "R"],
                            "context": "正文",
                        }
                    ],
                    "tables": [],
                    "formulas": [],
                }
            )
        if "含插图页面" in prompt:
            return json.dumps(
                {
                    "markdown": "正文段落。\n\n## 图 1\n\nA technical diagram with D and R labels.",
                    "figures": [
                        {
                            "caption": "图 1",
                            "type": "diagram",
                            "description": "A technical diagram with D and R labels.",
                            "labels": ["D", "R"],
                            "context": "正文段落。",
                        }
                    ],
                    "tables": [{"markdown": "| ignored |"}],
                    "formulas": [{"latex": "ignored"}],
                }
            )
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
    assert "空白单元格必须输出字符串" in FakeGLMOcrClient.prompts[0]


def test_extract_page_tables_recovers_localized_json_table(monkeypatch):
    _patch_clients(monkeypatch)
    FakeGLMOcrClient.result = normalize_text_response(
        json.dumps(
            {
                "表名": "表 B.9",
                "行标题": "泄放压力 MPa",
                "列分组标题": "过热蒸汽泄放温度/℃",
                "列标题": ["205", "225", "250", "275"],
                "数据": [
                    {"行标题值": "2.25", "205": "n/a", "225": "n/a", "250": "0.963", "275": "0.943"},
                    {"行标题值": "2.50", "205": "n/a", "225": "n/a", "250": "n/a", "275": "0.946"},
                ],
            },
            ensure_ascii=False,
        ),
        "glm_ocr",
    )

    result = json.loads(
        single_page_tools.extract_page_tables_direct(
            file_data=PNG_DATA,
            input_type="image",
            ocr_config={"glm_ocr": {"enabled": True, "model": "glm", "api_key": "x", "base_url": "http://x"}},
            vlm_config={"model": "vlm", "api_key": "x", "base_url": "http://x"},
        )
    )

    assert result["items"][0]["title"] == "表 B.9"
    assert "| 泄放压力 MPa | 205 | 225 | 250 | 275 |" in result["items"][0]["markdown"]
    assert "| 2.50 | n/a | n/a | n/a | 0.946 |" in result["items"][0]["markdown"]


def test_extract_page_tables_recovers_html_table_from_glm_markdown(monkeypatch):
    _patch_clients(monkeypatch)
    FakeGLMOcrClient.result = OcrResult(
        markdown=(
            "<table><tr><th>泄放压力 MPa</th><th>205</th><th>225</th><th>250</th><th>275</th></tr>"
            "<tr><td>2.50</td><td></td><td></td><td></td><td>0.946</td></tr></table>"
        )
    )

    result = json.loads(
        single_page_tools.extract_page_tables_direct(
            file_data=PNG_DATA,
            input_type="image",
            ocr_config={"glm_ocr": {"enabled": True, "model": "glm", "api_key": "x", "base_url": "http://x"}},
            vlm_config={"model": "vlm", "api_key": "x", "base_url": "http://x"},
        )
    )

    assert len(result["items"]) == 1
    assert "| 泄放压力 MPa | 205 | 225 | 250 | 275 |" in result["items"][0]["markdown"]
    assert "| 2.50 | n/a | n/a | n/a | 0.946 |" in result["items"][0]["markdown"]
    assert result["model_calls"] == {"glm_ocr": 1, "vlm_ocr": 0}


def test_extract_page_tables_recovers_html_table_from_raw_text(monkeypatch):
    _patch_clients(monkeypatch)
    FakeGLMOcrClient.result = OcrResult(
        markdown="",
        page_text="",
        raw={
            "text": (
                '<table class="table table-bordered"><thead><tr><th rowspan="2">泄放压力MPa</th>'
                '<th colspan="3">过热蒸汽泄放温度/℃</th></tr><tr><th>205</th><th>225</th><th>250</th></tr></thead>'
                '<tbody><tr><td>1.50</td><td></td><td></td><td>0.957</td></tr></tbody></table>'
            )
        },
    )

    result = json.loads(
        single_page_tools.extract_page_tables_direct(
            file_data=PNG_DATA,
            input_type="image",
            ocr_config={"glm_ocr": {"enabled": True, "model": "glm", "api_key": "x", "base_url": "http://x"}},
        )
    )

    assert len(result["items"]) == 1
    assert "| 泄放压力MPa | 过热蒸汽泄放温度/℃ | n/a | n/a |" in result["items"][0]["markdown"]
    assert "| 1.50 | n/a | n/a | 0.957 |" in result["items"][0]["markdown"]


def test_extract_page_tables_fills_empty_html_cells_from_glm_table(monkeypatch):
    _patch_clients(monkeypatch)
    FakeGLMOcrClient.result = OcrResult(
        tables=[
            OcrElement(
                kind="table",
                source="glm_ocr",
                markdown="<table><tr><td>A</td><td></td><td> C </td></tr></table>",
            )
        ]
    )

    result = json.loads(
        single_page_tools.extract_page_tables_direct(
            file_data=PNG_DATA,
            input_type="image",
            ocr_config={"glm_ocr": {"enabled": True, "model": "glm", "api_key": "x", "base_url": "http://x"}},
            vlm_config={"model": "vlm", "api_key": "x", "base_url": "http://x"},
        )
    )

    assert "<td>n/a</td>" in result["items"][0]["markdown"]
    assert "<td></td>" not in result["items"][0]["markdown"]


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
    assert result["items"][0]["latex"] == "$$\nx=y+z\n$$"
    assert "markdown" not in result["items"][0]
    assert result["model_calls"] == {"glm_ocr": 1, "vlm_ocr": 0}


def test_extract_page_formulas_includes_surrounding_explanation(monkeypatch):
    _patch_clients(monkeypatch)
    FakeGLMOcrClient.result = OcrResult(
        markdown=(
            "所需最小泄放面积按公式(B.13)计算：\n\n"
            "$$\nA = B + C\n$$\n\n"
            "式中：\n"
            "$A$ ——所需最小泄放面积，单位为平方毫米；\n"
            "$B$ ——第一变量。\n\n"
            "B.8.2.2 下一段说明"
        ),
        page_text=(
            "所需最小泄放面积按公式(B.13)计算：\n\n"
            "$$\nA = B + C\n$$\n\n"
            "式中：\n"
            "$A$ ——所需最小泄放面积，单位为平方毫米；\n"
            "$B$ ——第一变量。\n\n"
            "B.8.2.2 下一段说明"
        ),
        formulas=[OcrElement(kind="formula", source="glm_ocr", latex="$$\nA = B + C\n$$")],
    )

    result = json.loads(
        single_page_tools.extract_page_formulas_direct(
            file_data=PNG_DATA,
            input_type="image",
            ocr_config={"glm_ocr": {"enabled": True, "model": "glm", "api_key": "x", "base_url": "http://x"}},
            vlm_config={"model": "vlm", "api_key": "x", "base_url": "http://x"},
        )
    )

    assert len(result["items"]) == 1
    assert "公式(B.13)" in result["items"][0]["description"]
    assert "$A$" in result["items"][0]["variables"]
    assert "下一段说明" not in result["items"][0]["variables"]


def test_extract_page_formulas_returns_formula_page_markdown(monkeypatch):
    _patch_clients(monkeypatch)
    FakeGLMOcrClient.result = OcrResult(
        markdown=(
            "所需最小泄放面积按公式(B.13)计算：\n\n"
            "$$\nA = B + C\n$$\n\n"
            "式中：\n"
            "$A$ ——所需最小泄放面积。"
        ),
        page_text="",
        formulas=[OcrElement(kind="formula", source="glm_ocr", latex="$$\nA = B + C\n$$")],
    )

    result = json.loads(
        single_page_tools.extract_page_formulas_direct(
            file_data=PNG_DATA,
            input_type="image",
            ocr_config={"glm_ocr": {"enabled": True, "model": "glm", "api_key": "x", "base_url": "http://x"}},
            vlm_config={"model": "vlm", "api_key": "x", "base_url": "http://x"},
        )
    )

    assert result["markdown"].startswith("所需最小泄放面积按公式")
    assert "$$\nA = B + C\n$$" in result["markdown"]
    assert result["items"][0]["latex"] == "$$\nA = B + C\n$$"
    assert "$A$" in result["items"][0]["variables"]


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
    assert result["markdown"].startswith("正文段落。")
    assert len(result["items"]) == 1
    assert result["items"][0]["caption"] == "图 1"
    assert result["items"][0]["source"] == "vlm_ocr"
    assert result["model_calls"] == {"glm_ocr": 0, "vlm_ocr": 1}
    assert "含插图页面" in FakeVLMClient.prompts[0]


def test_analyze_page_layout_returns_blocks_and_recommendation(monkeypatch):
    _patch_clients(monkeypatch)

    result = json.loads(
        single_page_tools.analyze_page_layout_direct(
            file_data=PNG_DATA,
            input_type="image",
            ocr_config={"glm_ocr": {"enabled": True, "model": "glm", "api_key": "x", "base_url": "http://x"}},
        )
    )

    assert result["tool"] == "analyze_page_layout"
    assert result["markdown"].startswith("正文")
    assert len(result["blocks"]) == 2
    assert result["blocks"][1]["type"] == "formula"
    assert result["summary"]["recommended_tool"] == "extract_page_formulas"
    assert result["model_calls"] == {"glm_ocr": 1, "vlm_ocr": 0}


def test_extract_page_layout_enhanced_returns_markdown_blocks_and_derived_items(monkeypatch):
    _patch_clients(monkeypatch)

    def parse_mixed_layout(self, image_path, return_crop_images=False, need_layout_visualization=False):
        _ = self
        _ = image_path
        _ = return_crop_images
        _ = need_layout_visualization
        return {
            "md_results": "正文\n\n| A | B |\n| --- | --- |\n| 1 | n/a |\n\n![](page=0,bbox=[10, 10, 40, 40])",
            "layout_details": [
                [
                    {"index": 1, "label": "text", "bbox_2d": [0, 0, 100, 20], "content": "正文"},
                    {
                        "index": 2,
                        "label": "table",
                        "bbox_2d": [0, 25, 100, 70],
                        "content": "| A | B |\n| --- | --- |\n| 1 | n/a |",
                    },
                    {"index": 3, "label": "image", "bbox_2d": [10, 10, 40, 40], "content": ""},
                ]
            ],
        }

    monkeypatch.setattr(FakeGLMOcrClient, "parse_layout", parse_mixed_layout)

    result = json.loads(
        single_page_tools.extract_page_layout_enhanced_direct(
            file_data=PNG_DATA,
            input_type="image",
            ocr_config={"glm_ocr": {"enabled": True, "model": "glm", "api_key": "x", "base_url": "http://x"}},
            vlm_config={"model": "vlm", "api_key": "x", "base_url": "http://x"},
        )
    )

    assert result["tool"] == "extract_page_layout_enhanced"
    assert result["markdown"].startswith("正文")
    assert len(result["blocks"]) == 3
    assert result["summary"]["recommended_tool"] == "extract_page_structured"
    assert result["tables"][0]["bbox"] == [0, 25, 100, 70]
    assert result["figures"][0]["bbox"] == [10, 10, 40, 40]
    assert result["figures"][0]["source"] == "glm_ocr_layout+vlm_ocr"
    assert result["figures"][0]["description"] == "A positioned technical diagram with D and R labels."
    assert result["model_calls"] == {"glm_ocr": 1, "vlm_ocr": 1}
    assert "image blocks" in FakeVLMClient.prompts[0]


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
