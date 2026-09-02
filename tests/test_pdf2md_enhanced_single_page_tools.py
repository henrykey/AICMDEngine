import base64
import asyncio
import importlib.util
import io
import json
import sys
import types
import urllib.error
from pathlib import Path

import fitz
import pytest


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
_load_module(f"{PACKAGE_NAME}.models", ROOT / "mcp/servers/PDF2MDEnhanced/models.py")
_load_module(f"{PACKAGE_NAME}.source_resolver", ROOT / "mcp/servers/PDF2MDEnhanced/source_resolver.py")
_load_module(f"{PACKAGE_NAME}.task_manager", ROOT / "mcp/servers/PDF2MDEnhanced/task_manager.py")
page_processor = _load_module(f"{PACKAGE_NAME}.page_processor", ROOT / "mcp/servers/PDF2MDEnhanced/page_processor.py")
single_page_tools = _load_module(f"{PACKAGE_NAME}.single_page_tools", ROOT / "mcp/servers/PDF2MDEnhanced/single_page_tools.py")
server = _load_module(f"{PACKAGE_NAME}.server", ROOT / "mcp/servers/PDF2MDEnhanced/server.py")

OcrElement = sys.modules[f"{PACKAGE_NAME}.ocr_clients.ocr_models"].OcrElement
OcrResult = sys.modules[f"{PACKAGE_NAME}.ocr_clients.ocr_models"].OcrResult
normalize_text_response = sys.modules[f"{PACKAGE_NAME}.ocr_clients.ocr_normalizers"].normalize_text_response
OpenAICompatibleOcrClient = sys.modules[
    f"{PACKAGE_NAME}.ocr_clients.openai_compatible_ocr_client"
].OpenAICompatibleOcrClient
DynamicVLMClient = sys.modules[f"{PACKAGE_NAME}.vlm_client"].DynamicVLMClient


PNG_DATA = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode("ascii")
GBT16749_PAGE12_QWEN_RESPONSE = (
    ROOT / "tests/fixtures/gbt16749_page12_qwen_table_response.md"
).read_text(encoding="utf-8")


def test_full_page_dual_output_uses_configured_bounded_budget(monkeypatch):
    observed = []
    client = DynamicVLMClient(
        {
            "model": "fixture-vlm",
            "api_key": "unused",
            "base_url": "https://example.test/v1",
            "max_tokens": 20480,
            "context_window": 128000,
            "dual_output_max_tokens": 8192,
        }
    )
    monkeypatch.setattr(
        client,
        "_call_image_prompt",
        lambda image_path, prompt, max_tokens: observed.append(max_tokens)
        or '{"render":"ok","rag":{"page_text":"","elements":{}}}',
    )

    client.full_page_dual_output("/tmp/unused.png")

    assert observed == [8192]
    assert client.last_dual_output_budget == {
        "provider_max_tokens": 20480,
        "context_window": 128000,
        "configured_max_tokens": 8192,
        "effective_max_tokens": 8192,
        "cap_reason": "dual_output_max_tokens",
    }


def test_full_page_dual_output_budget_supports_three_controlled_tiers(monkeypatch):
    for configured in (4096, 8192, 16384):
        observed = []
        client = DynamicVLMClient(
            {
                "model": "fixture-vlm",
                "api_key": "unused",
                "base_url": "https://example.test/v1",
                "max_tokens": 20480,
                "context_window": 128000,
                "dual_output_max_tokens": configured,
            }
        )
        monkeypatch.setattr(
            client,
            "_call_image_prompt",
            lambda image_path, prompt, max_tokens: observed.append(max_tokens)
            or '{"render":"ok","rag":{"page_text":"","elements":{}}}',
        )

        client.full_page_dual_output("/tmp/unused.png")

        assert observed == [configured]


def test_full_page_dual_output_budget_reserves_context_space(monkeypatch):
    observed = []
    client = DynamicVLMClient(
        {
            "model": "fixture-vlm",
            "api_key": "unused",
            "base_url": "https://example.test/v1",
            "max_tokens": 20480,
            "context_window": 6000,
            "dual_output_max_tokens": 8192,
            "context_window_safety_margin": 2000,
        }
    )
    monkeypatch.setattr(
        client,
        "_call_image_prompt",
        lambda image_path, prompt, max_tokens: observed.append(max_tokens)
        or '{"render":"ok","rag":{"page_text":"","elements":{}}}',
    )

    client.full_page_dual_output("/tmp/unused.png")

    assert observed == [4000]
    assert client.last_dual_output_budget["cap_reason"] == "context_window"


def test_full_page_dual_output_preserves_object_shaped_geometry():
    client = DynamicVLMClient.__new__(DynamicVLMClient)
    table = {
        "markdown": "| A | B |\n| --- | --- |\n| 1 | 2 |",
        "bbox": [0.1, 0.1, 0.9, 0.8],
        "bbox_space": "normalized_page",
        "source_cell_row_offset": 1,
        "source_cells": [{
            "row": 1,
            "col": 1,
            "bbox": [0.5, 0.3, 0.9, 0.6],
            "bbox_space": "normalized_page",
            "confidence": 0.98,
        }],
    }

    normalized = client._normalize_dual_payload({
        "render": table["markdown"],
        "rag": {
            "page_text": "",
            "elements": {
                "tables": [table],
                "formulas": [{"latex": "x=y", "bbox": [0.6, 0.4, 0.7, 0.5]}],
                "figures": [],
            },
        },
    })

    assert normalized["rag"]["elements"]["tables"][0] == table
    assert normalized["rag"]["elements"]["formulas"][0]["latex"] == "x=y"


def test_single_page_table_vlm_uses_provider_output_budget(monkeypatch):
    observed = []
    client = DynamicVLMClient.__new__(DynamicVLMClient)
    client.max_tokens = 16384
    client.last_call_info = {}
    monkeypatch.setattr(
        client,
        "_call_image_prompt",
        lambda image_path, prompt, max_tokens: observed.append(max_tokens)
        or '{"tables":[{"title":"T","markdown":"| A | B |\\n| --- | --- |\\n| 1 | 2 |"}]}',
    )

    result = single_page_tools._call_vlm_structured(
        client,
        "/tmp/unused.png",
        "extract tables",
        max_tokens=client.max_tokens,
    )

    assert observed == [16384]
    assert len(result.tables) == 1


def test_layout_recovery_prompt_keeps_authoritative_ids_and_parses_only_typed_arrays(monkeypatch):
    observed = {}
    client = DynamicVLMClient.__new__(DynamicVLMClient)
    client.max_tokens = 4096

    def fake_call(image_path, prompt, max_tokens):
        observed.update({"image_path": image_path, "prompt": prompt, "max_tokens": max_tokens})
        return json.dumps(
            {
                "tables": [],
                "formulas": [],
                "figures": [
                    {
                        "layout_id": "p1-o002-figure",
                        "source_block_index": 7,
                        "description": "mocked figure",
                    }
                ],
                "ignored": ["must not leak"],
            }
        )

    monkeypatch.setattr(client, "_call_image_prompt", fake_call)
    result = client.extract_layout_structured(
        "/tmp/unused.png",
        [
            {
                "layout_id": "p1-o002-figure",
                "source_block_index": 7,
                "type": "figure",
                "reading_order": 2,
                "bbox": [0.1, 0.2, 0.5, 0.6],
                "content": "",
            }
        ],
    )

    assert observed["image_path"] == "/tmp/unused.png"
    assert observed["max_tokens"] == 4096
    assert "p1-o002-figure" in observed["prompt"]
    assert result == {
        "tables": [],
        "formulas": [],
        "figures": [
            {
                "layout_id": "p1-o002-figure",
                "source_block_index": 7,
                "description": "mocked figure",
            }
        ],
    }


def test_vlm_stream_response_preserves_finish_reason():
    class Delta:
        content = '{"tables":['

    class Choice:
        delta = Delta()
        finish_reason = "length"

    class Chunk:
        choices = [Choice()]

    class Completions:
        def create(self, stream, **kwargs):
            assert stream is True
            return iter([Chunk()])

    client = DynamicVLMClient.__new__(DynamicVLMClient)
    client._client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=Completions()))

    content, mode, finish_reason = client._chat_completion_with_stream_fallback(model="fixture", messages=[])

    assert content == '{"tables":['
    assert mode == "stream"
    assert finish_reason == "length"


def test_glm_ocr_layout_file_payload_uses_data_uri():
    client = OpenAICompatibleOcrClient({})

    assert client._data_uri_for_file("/tmp/page.png", "abc") == "data:image/png;base64,abc"
    assert client._data_uri_for_file("/tmp/page.jpg", "abc") == "data:image/jpeg;base64,abc"
    assert client._data_uri_for_file("/tmp/page.pdf", "abc") == "data:application/pdf;base64,abc"


def _layout_http_error(status, payload):
    return urllib.error.HTTPError(
        "http://ocr.example.test/layout_parsing",
        status,
        "fixture error",
        {},
        io.BytesIO(json.dumps(payload).encode("utf-8")),
    )


def test_glm_ocr_layout_429_1305_retries_then_succeeds(monkeypatch, tmp_path, caplog):
    client = OpenAICompatibleOcrClient(
        {
            "enabled": True,
            "model": "glm-ocr",
            "base_url": "http://ocr.example.test/v1",
            "max_retries": 2,
        }
    )
    page = tmp_path / "page.png"
    page.write_bytes(base64.b64decode(PNG_DATA))
    responses = [
        _layout_http_error(429, {"error": {"code": 1305, "message": "当前访问量过大"}}),
        io.BytesIO(b'{"md_results": "OCR text"}'),
    ]
    sleeps = []

    def fake_urlopen(request, timeout):
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("time.sleep", sleeps.append)

    with caplog.at_level("WARNING"):
        result = client.extract_page(str(page))

    assert result.page_text == "OCR text"
    assert sleeps == [3.0]
    assert "waiting 3.0s before retry=1/2" in caplog.text


def test_glm_ocr_layout_regular_400_does_not_retry(monkeypatch, tmp_path):
    client = OpenAICompatibleOcrClient(
        {
            "enabled": True,
            "model": "glm-ocr",
            "base_url": "http://ocr.example.test/v1",
            "max_retries": 2,
        }
    )
    page = tmp_path / "page.png"
    page.write_bytes(base64.b64decode(PNG_DATA))
    calls = []
    sleeps = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        raise _layout_http_error(400, {"error": {"code": 1000, "message": "bad request"}})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("time.sleep", sleeps.append)

    with pytest.raises(RuntimeError, match="HTTP 400"):
        client.extract_page(str(page))

    assert len(calls) == 1
    assert sleeps == []


def test_glm_ocr_layout_429_1305_fails_after_retries_exhausted(monkeypatch, tmp_path):
    client = OpenAICompatibleOcrClient(
        {
            "enabled": True,
            "model": "glm-ocr",
            "base_url": "http://ocr.example.test/v1",
            "max_retries": 2,
        }
    )
    page = tmp_path / "page.png"
    page.write_bytes(base64.b64decode(PNG_DATA))
    calls = []
    sleeps = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        raise _layout_http_error(429, {"code": "1305", "message": "当前访问量过大"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("time.sleep", sleeps.append)

    with pytest.raises(RuntimeError, match="HTTP 429"):
        client.extract_page(str(page))

    assert len(calls) == 3
    assert sleeps == [3.0, 6.0]


@pytest.mark.parametrize("api_key", [None, "", "secret-key"])
@pytest.mark.parametrize("mode", ["layout_parsing", "chat"])
def test_ocr_optional_api_key_request_headers(monkeypatch, tmp_path, api_key, mode):
    import httpx
    import io

    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    config = {
        "enabled": True,
        "model": "self-hosted-ocr",
        "base_url": "http://ocr.example.test/v1",
        "mode": mode,
        "max_retries": 0,
    }
    if api_key is not None:
        config["api_key"] = api_key
    client = OpenAICompatibleOcrClient(config)
    client.ensure_enabled()
    page = tmp_path / "page.png"
    page.write_bytes(base64.b64decode(PNG_DATA))
    observed = []

    def fake_urlopen(request, timeout):
        observed.append({key.lower(): value for key, value in request.header_items()})
        return io.BytesIO(b'{"md_results": "OCR text"}')

    def fake_send(self, request, **kwargs):
        observed.append(dict(request.headers))
        return httpx.Response(
            200,
            request=request,
            json={"choices": [{"message": {"content": "OCR text"}}]},
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(httpx.Client, "send", fake_send)
    try:
        result = client.extract_page(str(page))
    finally:
        if client._client is not None:
            client._client.close()

    assert result.page_text == "OCR text"
    assert len(observed) == 1
    assert observed[0]["content-type"] == "application/json"
    if api_key:
        assert observed[0]["authorization"] == f"Bearer {api_key}"
    else:
        assert "authorization" not in observed[0]


@pytest.mark.parametrize("missing_field", ["enabled", "model", "base_url"])
def test_ocr_still_requires_enabled_model_and_base_url(missing_field):
    config = {"enabled": True, "model": "glm-ocr", "base_url": "http://ocr.example.test/v1"}
    config.pop(missing_field)
    client = OpenAICompatibleOcrClient(config)

    assert client.enabled is False
    with pytest.raises(ValueError, match="config is required"):
        client.ensure_enabled()


def test_glm_ocr_layout_table_title_is_preserved():
    client = OpenAICompatibleOcrClient({})

    result = client._normalize_layout_parsing_response(
        {
            "md_results": "",
            "layout_details": [
                [
                    {
                        "label": "table",
                        "table_title": "表 2 材料参数",
                        "content": "| A | B |\n| --- | --- |\n| 1 | 2 |",
                    }
                ]
            ],
        }
    )

    assert result.tables[0].title == "表 2 材料参数"


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
            figures=[OcrElement(kind="figure", source="glm_ocr", caption="图 1", description="ignored figure")],
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
    result_text = None

    def __init__(self, cfg):
        self.enabled = bool(cfg is not None)
        self.max_tokens = 4096

    def _call_image_prompt(self, image_path, prompt, max_tokens):
        _ = image_path
        _ = max_tokens
        self.__class__.prompts.append(prompt)
        if self.__class__.result_text is not None:
            return self.__class__.result_text
        if "补全表名和语义描述" in prompt:
            return json.dumps(
                {
                    "tables": [
                        {"index": 0, "title": "表 1 参数", "semanticDesc": "表 1 参数，包含 A 和 B 两列。"},
                        {"index": 1, "title": "表 2 指标", "semanticDesc": "表 2 指标，包含 C 和 D 两列。"},
                    ]
                },
                ensure_ascii=False,
            )
        if "image blocks" in prompt:
            return json.dumps(
                {
                    "figures": [
                        {
                            "block_index": 3,
                            "bbox": [10, 10, 40, 40],
                            "caption": "图 1",
                            "capture": "图 1",
                            "name": "图 1",
                            "figureName": "图 1",
                            "type": "diagram",
                            "description": "带有 D 和 R 标注的定位技术示意图。",
                            "semanticDesc": "带有 D 和 R 标注的定位技术示意图。",
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
                    "markdown": "正文段落。\n\n## 图 1\n\n带有 D 和 R 标注的技术示意图。",
                    "figures": [
                        {
                            "caption": "图 1",
                            "capture": "图 1",
                            "name": "图 1",
                            "figureName": "图 1",
                            "type": "diagram",
                            "description": "带有 D 和 R 标注的技术示意图。",
                            "semanticDesc": "带有 D 和 R 标注的技术示意图。",
                            "labels": ["D", "R"],
                            "context": "正文段落。",
                        }
                    ],
                    "tables": [{"markdown": "| ignored |"}],
                    "formulas": [{"latex": "ignored"}],
                }
            )
        if "插图、示意图、结构图" in prompt:
            return json.dumps(
                {
                    "figures": [
                        {
                            "caption": "图 1",
                            "capture": "图 1",
                            "name": "图 1",
                            "figureName": "图 1",
                            "type": "diagram",
                            "description": "带有 D 和 R 标注的技术示意图。",
                            "semanticDesc": "带有 D 和 R 标注的技术示意图。",
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
    FakeVLMClient.result_text = None


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
    assert result["tables"] == result["items"]
    assert result["columns"] == result["items"][0]["columns"]
    assert result["normalized_rows"] == result["items"][0]["normalized_rows"]
    assert result["source_cells"] == result["items"][0]["source_cells"]
    assert result["cell_status"] == result["items"][0]["cell_status"]
    assert result["orientation"] == result["items"][0]["orientation"]
    assert result["tableRowsFormat"] == "structured_json"
    assert isinstance(result["tableRowsContent"], str)
    assert json.loads(result["tableRowsContent"])["normalized_rows"] == result["normalized_rows"]
    assert result["model_calls"] == {"glm_ocr": 1, "vlm_ocr": 1}
    assert "目标是可查询的标准矩阵" in FakeGLMOcrClient.prompts[0]


def test_extract_page_tables_recovers_gbt16749_qwen_mixed_markdown_with_bounded_notes(monkeypatch):
    _patch_clients(monkeypatch)
    FakeVLMClient.result_text = GBT16749_PAGE12_QWEN_RESPONSE

    result = json.loads(
        single_page_tools.extract_page_tables_direct(
            file_data=PNG_DATA,
            input_type="image",
            description_language="zh",
            table_rows_format="structured_json",
            vlm_config={"model": "qwen-vl", "api_key": "x", "base_url": "http://x"},
        )
    )

    assert "vlm_ocr_returned_no_tables" not in result["warnings"]
    assert len(result["tables"]) == len(result["items"]) == 1
    table = result["tables"][0]
    assert table["title"] == "表 3 焊接接头高温强度降低系数 $w$"
    assert table["columns"] == [
        "材料", "427", "454", "482", "510", "538", "566", "593",
        "621", "649", "677", "704", "732", "760", "788", "816",
    ]
    assert len(table["normalized_rows"]) == 5
    assert all(len(row) == 16 for row in table["normalized_rows"])
    assert table["normalized_rows"][0][:4] == ["CrMo 钢$^{a \\sim e}$", "1", "0.95", "0.91"]
    assert table["normalized_rows"][-1][-3:] == ["0.59", "0.55", "0.5"]
    assert table["notes"] == [
        "本表所列温度仅用于相应材料焊接接头高温强度降低系数 $w$，材料的使用温度上限按 GB/T 150.2—2011 相应材料标准的规定。"
    ]
    assert len(table["footnotes"]) == 6
    metadata_text = "\n".join([*table["notes"], *table["footnotes"]])
    assert "4.4 厚度附加量" not in metadata_text
    assert "C=C_1+C_2" not in metadata_text
    assert result["columns"] == table["columns"]
    assert result["normalized_rows"] == table["normalized_rows"]
    assert json.loads(result["tableRowsContent"])["normalized_rows"] == table["normalized_rows"]
    assert any('"tables"' in prompt and '"footnotes"' in prompt for prompt in FakeVLMClient.prompts)


def test_extract_page_tables_retries_truncated_detailed_json_with_compact_contract(monkeypatch):
    class TruncatedThenCompactVLM:
        calls = []

        def __init__(self, cfg):
            self.enabled = bool(cfg)
            self.max_tokens = 16384
            self.last_call_info = {}

        def _call_image_prompt(self, image_path, prompt, max_tokens):
            _ = image_path
            self.__class__.calls.append((prompt, max_tokens))
            if len(self.__class__.calls) == 1:
                self.last_call_info = {
                    "finish_reason": "length",
                    "response_chars": 12000,
                    "truncated": True,
                }
                return '{"tables":[{"title":"表 8（续）","normalized_rows":[["0.35","1.480"]]'
            self.last_call_info = {
                "finish_reason": "stop",
                "response_chars": 120,
                "truncated": False,
            }
            return json.dumps(
                {
                    "tables": [
                        {
                            "title": "表 8（续）",
                            "markdown": "| x | y |\n| --- | --- |\n| 0.35 | 1.480 |",
                            "notes": ["中间值采用差值法计算。"],
                        }
                    ]
                },
                ensure_ascii=False,
            )

    monkeypatch.setattr(single_page_tools, "OpenAICompatibleOcrClient", FakeGLMOcrClient)
    monkeypatch.setattr(single_page_tools, "DynamicVLMClient", TruncatedThenCompactVLM)
    FakeGLMOcrClient.result = None
    FakeGLMOcrClient.error = None
    FakeGLMOcrClient.prompts = []
    TruncatedThenCompactVLM.calls = []

    result = json.loads(
        single_page_tools.extract_page_tables_direct(
            file_data=PNG_DATA,
            input_type="image",
            description_language="zh",
            vlm_config={"model": "qwen3.7-flash", "api_key": "x", "base_url": "http://x", "max_tokens": 16384},
        )
    )

    assert [max_tokens for _, max_tokens in TruncatedThenCompactVLM.calls] == [16384, 16384]
    assert "只返回紧凑 JSON" in TruncatedThenCompactVLM.calls[1][0]
    assert result["model_calls"] == {"glm_ocr": 0, "vlm_ocr": 2}
    assert result["tables"][0]["title"] == "表 8（续）"
    assert result["tables"][0]["normalized_rows"] == [["0.35", "1.480"]]
    assert result["tables"][0]["notes"] == ["中间值采用差值法计算。"]
    assert "vlm_ocr_detailed_response_truncated" in result["warnings"]
    assert "vlm_ocr_compact_table_retry_used" in result["warnings"]


def test_extract_page_tables_accepts_top_level_rows_json_and_preserves_table_notes(monkeypatch):
    _patch_clients(monkeypatch)
    FakeVLMClient.result_text = json.dumps(
        {
            "title": "表 3 焊接接头高温强度降低系数 w",
            "columns": ["材料", "427", "454"],
            "rows": [["CrMo 钢", "1", "0.95"]],
            "description": "不同材料在高温下的焊接接头强度降低系数。",
            "notes": ["本表温度仅用于对应材料。"],
            "footnotes": ["a CrMo 钢包括若干铬钼钢。"],
        },
        ensure_ascii=False,
    )

    result = json.loads(
        single_page_tools.extract_page_tables_direct(
            file_data=PNG_DATA,
            input_type="image",
            table_rows_format="structured_json",
            vlm_config={"model": "qwen-vl", "api_key": "x", "base_url": "http://x"},
        )
    )

    assert len(result["tables"]) == 1
    assert result["tables"][0]["columns"] == ["材料", "427", "454"]
    assert result["tables"][0]["normalized_rows"] == [["CrMo 钢", "1", "0.95"]]
    assert result["tables"][0]["notes"] == ["本表温度仅用于对应材料。"]
    assert result["tables"][0]["footnotes"] == ["a CrMo 钢包括若干铬钼钢。"]


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
    assert result["items"][0]["normalized_rows"][1] == ["2.50", "n/a", "n/a", "n/a", "0.946"]
    assert any(cell["status"] == "unreadable" for cell in result["items"][0]["cell_status"])


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
    assert "| 2.50 |  |  |  | 0.946 |" in result["items"][0]["markdown"]
    assert result["items"][0]["tableRowsFormat"] == "structured_json"
    assert "<table" not in result["items"][0]["tableRowsContent"].lower()
    assert json.loads(result["items"][0]["tableRowsContent"])["normalized_rows"] == [["2.50", "", "", "", "0.946"]]
    assert result["items"][0]["sourceHtml"].startswith("<table>")
    assert result["model_calls"] == {"glm_ocr": 1, "vlm_ocr": 1}


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
    assert "| 泄放压力MPa | 过热蒸汽泄放温度/℃ | 过热蒸汽泄放温度/℃ | 过热蒸汽泄放温度/℃ |" in result["items"][0]["markdown"]
    assert "| 泄放压力MPa | 205 | 225 | 250 |" in result["items"][0]["markdown"]
    assert "| 1.50 |  |  | 0.957 |" in result["items"][0]["markdown"]
    assert result["items"][0]["cell_status"][4]["status"] == "merged_fill"
    assert "<table" not in result["items"][0]["tableRowsContent"].lower()
    assert result["items"][0]["sourceHtml"].startswith('<table class="table table-bordered"')
    assert result["items"][0]["degraded"] is True
    assert result["items"][0]["manualReviewRequired"] is True


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

    assert "| A |  | C |" in result["items"][0]["markdown"]
    assert result["items"][0]["cell_status"][1]["status"] == "blank_in_source"
    assert "<table" not in result["items"][0]["tableRowsContent"].lower()
    assert "<td></td>" in result["items"][0]["sourceHtml"]


def test_extract_page_tables_structured_json_contract_for_html(monkeypatch):
    _patch_clients(monkeypatch)
    FakeGLMOcrClient.result = OcrResult(
        markdown="<table><tr><th>A</th><th>B</th></tr><tr><td></td><td>2</td></tr></table>"
    )

    result = json.loads(
        single_page_tools.extract_page_tables_direct(
            file_data=PNG_DATA,
            input_type="image",
            table_rows_format="structured_json",
            ocr_config={"glm_ocr": {"enabled": True, "model": "glm", "api_key": "x", "base_url": "http://x"}},
        )
    )

    content = result["items"][0]["tableRowsContent"]
    assert isinstance(content, str)
    assert "<table" not in content.lower()
    content = json.loads(content)
    assert content["columns"] == ["A", "B"]
    assert content["normalized_rows"] == [["", "2"]]
    assert content["cell_status"][2]["status"] == "blank_in_source"
    assert "raw_html" not in content
    assert result["items"][0]["raw_html"].startswith("<table>")
    assert result["items"][0]["sourceHtml"].startswith("<table>")


def test_extract_page_tables_markdown_blank_stays_blank_not_unreadable(monkeypatch):
    _patch_clients(monkeypatch)
    FakeGLMOcrClient.result = OcrResult(
        tables=[
            OcrElement(
                kind="table",
                source="glm_ocr",
                markdown="| A | B |\n| --- | --- |\n|  | 2 |",
            )
        ]
    )

    result = json.loads(
        single_page_tools.extract_page_tables_direct(
            file_data=PNG_DATA,
            input_type="image",
            table_rows_format="structured_json",
            ocr_config={"glm_ocr": {"enabled": True, "model": "glm", "api_key": "x", "base_url": "http://x"}},
        )
    )

    item = result["items"][0]
    assert item["normalized_rows"] == [["", "2"]]
    assert item["cell_status"][2]["status"] == "blank_in_source"
    assert "n/a" not in item["tableRowsContent"]
    assert json.loads(item["tableRowsContent"])["normalized_rows"] == [["", "2"]]


def test_extract_page_tables_distinguishes_blank_and_unreadable_status(monkeypatch):
    _patch_clients(monkeypatch)
    FakeGLMOcrClient.result = OcrResult(
        tables=[
            OcrElement(
                kind="table",
                source="glm_ocr",
                markdown="| A | B | C |\n| --- | --- | --- |\n|  | n/a | 3 |",
            )
        ]
    )

    result = json.loads(
        single_page_tools.extract_page_tables_direct(
            file_data=PNG_DATA,
            input_type="image",
            ocr_config={"glm_ocr": {"enabled": True, "model": "glm", "api_key": "x", "base_url": "http://x"}},
        )
    )

    statuses = {(cell["row"], cell["col"]): cell["status"] for cell in result["items"][0]["cell_status"]}
    assert statuses[(1, 0)] == "blank_in_source"
    assert statuses[(1, 1)] == "unreadable"


def test_extract_page_tables_accepts_model_normalized_json_schema(monkeypatch):
    _patch_clients(monkeypatch)
    FakeGLMOcrClient.result = normalize_text_response(
        json.dumps(
            {
                "table_title": "表 1",
                "orientation": 90,
                "columns": ["牌号", "状态", "规格"],
                "normalized_rows": [["20", "正火", "≤M22"], ["20", "正火", "M24~M48"]],
                "source_cells": [{"row": 1, "col": 0, "text": "20", "rowspan": 2, "colspan": 1, "confidence": 0.98}],
                "cell_status": [{"row": 2, "col": 0, "status": "merged_fill", "source_row": 1, "source_col": 0}],
                "degraded": False,
                "manualReviewRequired": False,
                "warnings": [],
            },
            ensure_ascii=False,
        ),
        "glm_ocr",
    )

    result = json.loads(
        single_page_tools.extract_page_tables_direct(
            file_data=PNG_DATA,
            input_type="image",
            table_rows_format="structured_json",
            ocr_config={"glm_ocr": {"enabled": True, "model": "glm", "api_key": "x", "base_url": "http://x"}},
        )
    )

    item = result["items"][0]
    assert item["title"] == "表 1"
    assert item["orientation"] == 90
    assert item["columns"] == ["牌号", "状态", "规格"]
    assert item["normalized_rows"] == [["20", "正火", "≤M22"], ["20", "正火", "M24~M48"]]
    assert item["source_cells"][0]["rowspan"] == 2
    assert json.loads(item["tableRowsContent"])["normalized_rows"] == item["normalized_rows"]


def test_extract_page_tables_enriches_glm_rows_with_vlm_metadata(monkeypatch):
    _patch_clients(monkeypatch)
    FakeGLMOcrClient.result = OcrResult(
        tables=[
            OcrElement(kind="table", source="glm_ocr", markdown="| A | B |\n| --- | --- |\n| 1 | 2 |"),
            OcrElement(kind="table", source="glm_ocr", markdown="| C | D |\n| --- | --- |\n| 3 | 4 |"),
        ]
    )

    result = json.loads(
        single_page_tools.extract_page_tables_direct(
            file_data=PNG_DATA,
            input_type="image",
            table_rows_format="structured_json",
            ocr_config={"glm_ocr": {"enabled": True, "model": "glm", "api_key": "x", "base_url": "http://x"}},
            vlm_config={"model": "vlm", "api_key": "x", "base_url": "http://x"},
        )
    )

    assert result["model_calls"] == {"glm_ocr": 1, "vlm_ocr": 1}
    assert result["items"][0]["title"] == "表 1 参数"
    assert result["items"][0]["semanticDesc"] == "表 1 参数，包含 A 和 B 两列。"
    assert result["items"][0]["columns"] == ["A", "B"]
    assert result["items"][0]["normalized_rows"] == [["1", "2"]]
    assert result["items"][1]["title"] == "表 2 指标"
    assert result["items"][1]["semanticDesc"] == "表 2 指标，包含 C 和 D 两列。"
    assert result["items"][1]["columns"] == ["C", "D"]
    assert result["items"][1]["normalized_rows"] == [["3", "4"]]
    assert any("补全表名和语义描述" in prompt for prompt in FakeVLMClient.prompts)


def test_extract_page_tables_skips_vlm_metadata_when_glm_title_is_reliable(monkeypatch):
    _patch_clients(monkeypatch)
    FakeGLMOcrClient.result = OcrResult(
        tables=[
            OcrElement(
                kind="table",
                source="glm_ocr",
                title="表 7-35 铜换热管的折流板和支撑板管孔直径及允许偏差",
                markdown="| 换热管外径 | 10 | 12 |\n| --- | --- | --- |\n| 管孔直径 | 10,30 | 12,30 |",
            )
        ]
    )

    result = json.loads(
        single_page_tools.extract_page_tables_direct(
            file_data=PNG_DATA,
            input_type="image",
            table_rows_format="structured_json",
            ocr_config={"glm_ocr": {"enabled": True, "model": "glm", "api_key": "x", "base_url": "http://x"}},
            vlm_config={"model": "vlm", "api_key": "x", "base_url": "http://x"},
        )
    )

    assert result["model_calls"] == {"glm_ocr": 1, "vlm_ocr": 0}
    assert result["items"][0]["title"] == "表 7-35 铜换热管的折流板和支撑板管孔直径及允许偏差"
    assert result["items"][0]["semanticDesc"].startswith("表 7-35 铜换热管")
    assert "Fields include: 换热管外径, 10, 12" in result["items"][0]["semanticDesc"]
    assert not FakeVLMClient.prompts


def test_extract_page_tables_model_rows_wider_than_columns_degraded(monkeypatch):
    _patch_clients(monkeypatch)
    FakeGLMOcrClient.result = normalize_text_response(
        json.dumps(
            {
                "columns": ["A", "B"],
                "normalized_rows": [["1", "2", "extra"]],
                "source_cells": [],
                "cell_status": [],
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
        )
    )

    item = result["items"][0]
    assert item["columns"] == ["A", "B"]
    assert item["normalized_rows"] == [["1", "2", "extra"]]
    assert item["degraded"] is True
    assert item["manualReviewRequired"] is True
    assert "inconsistent_row_width" in item["warnings"]
    assert "inconsistent_row_width" in item["reason"]
    assert json.loads(item["tableRowsContent"])["normalized_rows"] == [["1", "2", "extra"]]


def test_extract_page_tables_preserves_zero_values_in_model_schema(monkeypatch):
    _patch_clients(monkeypatch)
    FakeGLMOcrClient.result = normalize_text_response(
        json.dumps(
            {
                "columns": ["A", 0, False],
                "normalized_rows": [[0, False, ""]],
                "source_cells": [],
                "cell_status": [],
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
        )
    )

    item = result["items"][0]
    assert item["columns"] == ["A", "0", "False"]
    assert item["normalized_rows"] == [["0", "False", ""]]
    payload = json.loads(item["tableRowsContent"])
    assert payload["columns"] == ["A", "0", "False"]
    assert payload["normalized_rows"] == [["0", "False", ""]]
    assert result["columns"] == ["A", "0", "False"]
    assert result["normalized_rows"] == [["0", "False", ""]]


def test_extract_page_tables_model_html_markdown_not_publishable_structured_json(monkeypatch):
    _patch_clients(monkeypatch)
    FakeGLMOcrClient.result = normalize_text_response(
        json.dumps(
            {
                "columns": ["A", "B"],
                "normalized_rows": [["1", "2"]],
                "markdown": "<table><tr><td>A</td><td>B</td></tr></table>",
                "source_cells": [],
                "cell_status": [],
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
        )
    )

    item = result["items"][0]
    assert item["degraded"] is True
    assert item["manualReviewRequired"] is True
    assert "html_removed_from_tableRowsContent" in item["warnings"]
    assert item["tableRowsContent"] == ""
    assert result["tableRowsContent"] == ""
    assert item["raw_html"].startswith("<table>")


def test_extract_page_tables_repairs_markdown_left_group_rowspan_by_profile(monkeypatch):
    _patch_clients(monkeypatch)
    FakeGLMOcrClient.result = OcrResult(
        markdown=(
            "| 材料 | 热处理状态 | 直径mm | Rm MPa |\n"
            "| --- | --- | --- | --- |\n"
            "| 合金钢 | 调质 | ≤22 | 800 |\n"
            "| 22~48 | 780 |"
        )
    )

    result = json.loads(
        single_page_tools.extract_page_tables_direct(
            file_data=PNG_DATA,
            input_type="image",
            ocr_config={"glm_ocr": {"enabled": True, "model": "glm", "api_key": "x", "base_url": "http://x"}},
        )
    )

    item = result["items"][0]
    assert item["normalized_rows"] == [["合金钢", "调质", "≤22", "800"], ["合金钢", "调质", "22~48", "780"]]
    assert any(cell["status"] == "merged_fill" and cell["row"] == 2 and cell["col"] == 0 for cell in item["cell_status"])
    assert any(cell["status"] == "merged_fill" and cell["row"] == 2 and cell["col"] == 1 for cell in item["cell_status"])
    assert "markdown_merged_cell_repaired" in item["warnings"]
    assert item["manualReviewRequired"] is False


def test_extract_page_tables_repairs_markdown_right_metric_rowspan_by_profile(monkeypatch):
    _patch_clients(monkeypatch)
    FakeGLMOcrClient.result = OcrResult(
        markdown=(
            "| 压力 MPa | 温度℃ | 系数A | 系数B |\n"
            "| --- | --- | --- | --- |\n"
            "| 1.0 | 100 | 0.95 | 0.88 |\n"
            "| 1.5 | 120 |"
        )
    )

    result = json.loads(
        single_page_tools.extract_page_tables_direct(
            file_data=PNG_DATA,
            input_type="image",
            ocr_config={"glm_ocr": {"enabled": True, "model": "glm", "api_key": "x", "base_url": "http://x"}},
        )
    )

    item = result["items"][0]
    assert item["normalized_rows"] == [["1.0", "100", "0.95", "0.88"], ["1.5", "120", "0.95", "0.88"]]
    assert any(cell["status"] == "merged_fill" and cell["row"] == 2 and cell["col"] == 2 for cell in item["cell_status"])
    assert any(cell["status"] == "merged_fill" and cell["row"] == 2 and cell["col"] == 3 for cell in item["cell_status"])
    assert "markdown_merged_cell_repaired" in item["warnings"]
    assert item["manualReviewRequired"] is False


def test_extract_page_tables_repairs_markdown_without_grade_or_mxx(monkeypatch):
    _patch_clients(monkeypatch)
    FakeGLMOcrClient.result = OcrResult(
        markdown=(
            "| 试样 | 处理条件 | 厚度mm | 硬度HV |\n"
            "| --- | --- | --- | --- |\n"
            "| S1 | 固溶 | 5~8 | 210 |\n"
            "| 8~12 | 215 |"
        )
    )

    result = json.loads(
        single_page_tools.extract_page_tables_direct(
            file_data=PNG_DATA,
            input_type="image",
            ocr_config={"glm_ocr": {"enabled": True, "model": "glm", "api_key": "x", "base_url": "http://x"}},
        )
    )

    item = result["items"][0]
    assert item["normalized_rows"] == [["S1", "固溶", "5~8", "210"], ["S1", "固溶", "8~12", "215"]]
    assert "markdown_merged_cell_repaired" in item["warnings"]
    assert item["manualReviewRequired"] is False


def test_extract_page_tables_ambiguous_markdown_repair_requires_review(monkeypatch):
    _patch_clients(monkeypatch)
    FakeGLMOcrClient.result = OcrResult(
        markdown="| A | B | C |\n| --- | --- | --- |\n| x | y | z |\n| m | n |"
    )

    result = json.loads(
        single_page_tools.extract_page_tables_direct(
            file_data=PNG_DATA,
            input_type="image",
            ocr_config={"glm_ocr": {"enabled": True, "model": "glm", "api_key": "x", "base_url": "http://x"}},
        )
    )

    item = result["items"][0]
    assert item["normalized_rows"] == [["x", "y", "z"], ["m", "n", ""]]
    assert item["degraded"] is True
    assert item["manualReviewRequired"] is True
    assert "ambiguous_markdown_merged_cell_repair" in item["warnings"]


def test_extract_page_tables_html_structured_source_bypasses_markdown_repair(monkeypatch):
    _patch_clients(monkeypatch)
    FakeGLMOcrClient.result = OcrResult(
        markdown=(
            '<table><tr><th>材料</th><th>状态</th><th>规格</th></tr>'
            '<tr><td rowspan="2">合金钢</td><td rowspan="2">调质</td><td>≤22</td></tr>'
            '<tr><td>22~48</td></tr></table>'
        )
    )

    result = json.loads(
        single_page_tools.extract_page_tables_direct(
            file_data=PNG_DATA,
            input_type="image",
            ocr_config={"glm_ocr": {"enabled": True, "model": "glm", "api_key": "x", "base_url": "http://x"}},
        )
    )

    item = result["items"][0]
    assert item["normalized_rows"] == [["合金钢", "调质", "≤22"], ["合金钢", "调质", "22~48"]]
    assert any(cell.get("rowspan") == 2 for cell in item["source_cells"])
    assert "markdown_merged_cell_repaired" not in item["warnings"]


def test_extract_page_tables_top_level_warnings_merge_without_overwrite(monkeypatch):
    _patch_clients(monkeypatch)
    monkeypatch.setattr(
        single_page_tools,
        "_prepare_context",
        lambda *args, **kwargs: single_page_tools.SinglePageContext(
            input_type="image",
            source_path=__file__,
            image_path=__file__,
            page_no=1,
            page_text="",
            native_tables=[],
        ),
    )

    def fake_extract_tables(ctx, glm, vlm, describe, model_calls, warnings, allow_native=True, table_rows_format="structured_json"):
        _ = ctx, glm, vlm, describe, allow_native, table_rows_format
        model_calls["glm_ocr"] = 1
        warnings.append("outer_warning")
        return [
            {
                "source": "glm_ocr",
                "title": "",
                "markdown": "| A |\n| --- |\n| 1 |",
                "tableRowsFormat": "structured_json",
                "tableRowsContent": "{}",
                "columns": ["A"],
                "normalized_rows": [["1"]],
                "source_cells": [],
                "cell_status": [],
                "orientation": 0,
                "raw_html": "",
                "sourceHtml": "",
                "warnings": ["item_warning"],
                "degraded": False,
                "manualReviewRequired": False,
                "reason": "",
                "context": "",
            }
        ]

    monkeypatch.setattr(single_page_tools, "_extract_tables", fake_extract_tables)

    result = json.loads(
        single_page_tools.extract_page_tables_direct(
            file_data=PNG_DATA,
            input_type="image",
            ocr_config={"glm_ocr": {"enabled": False}},
        )
    )

    assert result["warnings"] == ["outer_warning", "item_warning"]


def test_extract_page_tables_normalizes_rowspan_without_na_or_pseudo_columns(monkeypatch):
    _patch_clients(monkeypatch)
    FakeGLMOcrClient.result = OcrResult(
        markdown=(
            '<table><tr><th>牌号</th><th>热处理状态/调质状态的回火温度℃</th><th>规格mm</th>'
            '<th>Rm MPa</th><th>Rel(Rp0.2) MPa</th><th>A %</th><th>0℃冲击吸收能量平均值(KV2) J</th></tr>'
            '<tr><td rowspan="2">20</td><td rowspan="2">正火</td><td>≤M22</td>'
            '<td>≥410</td><td>≥245</td><td rowspan="2">≥25</td><td rowspan="2">≥41</td></tr>'
            '<tr><td>M24~M48</td><td>≥410</td><td>≥245</td></tr></table>'
        )
    )

    result = json.loads(
        single_page_tools.extract_page_tables_direct(
            file_data=PNG_DATA,
            input_type="image",
            table_rows_format="structured_json",
            ocr_config={"glm_ocr": {"enabled": True, "model": "glm", "api_key": "x", "base_url": "http://x"}},
        )
    )

    item = result["items"][0]
    assert item["columns"] == [
        "牌号",
        "热处理状态/调质状态的回火温度℃",
        "规格mm",
        "Rm MPa",
        "Rel(Rp0.2) MPa",
        "A %",
        "0℃冲击吸收能量平均值(KV2) J",
    ]
    assert item["normalized_rows"] == [
        ["20", "正火", "≤M22", "≥410", "≥245", "≥25", "≥41"],
        ["20", "正火", "M24~M48", "≥410", "≥245", "≥25", "≥41"],
    ]
    assert all(len(row) == 7 for row in item["normalized_rows"])
    assert any(cell["row"] == 2 and cell["col"] == 2 and cell["text"] == "M24~M48" for cell in item["source_cells"])
    assert "n/a" not in json.dumps(item["normalized_rows"], ensure_ascii=False)
    assert any(cell["status"] == "merged_fill" and cell["row"] == 2 and cell["col"] == 0 for cell in item["cell_status"])
    assert item["degraded"] is False
    assert item["manualReviewRequired"] is False
    assert result["columns"] == item["columns"]
    assert result["normalized_rows"] == item["normalized_rows"]
    assert json.loads(result["tableRowsContent"])["normalized_rows"] == item["normalized_rows"]


def test_extract_page_tables_vlm_html_contract_when_glm_unavailable(monkeypatch):
    _patch_clients(monkeypatch)

    result = json.loads(
        single_page_tools.extract_page_tables_direct(
            file_data=PNG_DATA,
            input_type="image",
            ocr_config={"glm_ocr": {"enabled": False}},
            vlm_config={"model": "vlm", "api_key": "x", "base_url": "http://x"},
        )
    )

    item = result["items"][0]
    assert item["source"] == "vlm_ocr"
    assert item["tableRowsFormat"] == "structured_json"
    assert "<table" not in item["tableRowsContent"].lower()
    assert json.loads(item["tableRowsContent"])["columns"] == ["C", "D"]


def test_extract_page_tables_docintel_complex_html_contract(monkeypatch):
    _patch_clients(monkeypatch)
    html = (
        '<table border="1"><tr><td>材料</td><td>螺栓直径/mm</td><td>热处理状态</td>'
        '<td colspan="2">许用应力/MPa\n取下列各值中的最小值</td></tr>'
        '<tr><td rowspan="2">非合金钢</td><td>≤M22</td><td rowspan="2">热轧、正火</td>'
        '<td>$\\frac{R_{\\mathrm{eL}}^{\\prime}}{2.7}$</td>'
        '<td rowspan="8">$\\frac{R_{\\mathrm{d}}^{\\prime}}{1.5}$</td></tr></table>'
    )
    FakeGLMOcrClient.result = OcrResult(markdown=html)

    result = json.loads(
        single_page_tools.extract_page_tables_direct(
            file_data=PNG_DATA,
            input_type="image",
            ocr_config={"glm_ocr": {"enabled": True, "model": "glm", "api_key": "x", "base_url": "http://x"}},
        )
    )

    item = result["items"][0]
    assert "<table" not in item["tableRowsContent"].lower()
    content = json.loads(item["tableRowsContent"])
    assert content["columns"] == ["材料", "螺栓直径/mm", "热处理状态", "许用应力/MPa 取下列各值中的最小值", "许用应力/MPa 取下列各值中的最小值"]
    assert "n/a" not in item["tableRowsContent"]
    assert item["sourceHtml"] == html
    assert item["degraded"] is True
    assert item["manualReviewRequired"] is True
    assert "colspan" in item["reason"]
    assert "complex_header" in item["warnings"]


def test_process_task_page_does_not_promote_single_page_table_schema(monkeypatch):
    class FakeTask:
        source_path = "/tmp/demo.pdf"
        planned_pages = [1]

    class FakeManager:
        def update_page_running(self, task_id, page_no):
            self.running = (task_id, page_no)

        def get_task(self, task_id):
            _ = task_id
            return FakeTask()

        def update_page_result(self, task_id, page_no, result):
            self.saved = (task_id, page_no, result)

        def update_page_failed(self, task_id, page_no, error):
            self.failed = (task_id, page_no, error)

    page_result = {
        "task_page_id": "page1",
        "page_no": 1,
        "route_selected": "text_only",
        "layout_version": "pdf2md-layout-ledger-v1",
        "layout_status": "EXTRACTED",
        "bbox_space": "normalized_page",
        "layout": [
            {
                "layout_id": "p1-o001-table",
                "type": "table",
                "reading_order": 1,
                "bbox": [0.1, 0.1, 0.9, 0.9],
                "status": "EXTRACTED",
            }
        ],
        "reconciliation": {"identified": 1, "extracted": 1, "failed": 0, "complete": True},
        "render": {"markdown": "| A | B |\n| --- | --- |\n| 1 | 2 |"},
        "rag": {
            "content": "page text",
            "page_text": "page text",
            "elements": {
                "tables": [
                    {
                        "source": "pymupdf",
                        "title": "A / B",
                        "markdown": "| A | B |\n| --- | --- |\n| 1 | 2 |",
                        "semantic_summary": "table",
                        "context": "",
                    }
                ],
                "formulas": [],
                "figures": [],
            },
        },
        "elements": {
            "tables": [
                {
                    "source": "pymupdf",
                    "title": "A / B",
                    "markdown": "| A | B |\n| --- | --- |\n| 1 | 2 |",
                    "semantic_summary": "table",
                    "context": "",
                }
            ],
            "formulas": [],
            "figures": [],
        },
        "next_context": {},
    }

    monkeypatch.setattr(server, "manager", FakeManager())
    monkeypatch.setattr(server, "process_page", lambda *args, **kwargs: page_result)

    process_task_page_fn = getattr(server.process_task_page, "fn", server.process_task_page)
    result = json.loads(asyncio.run(process_task_page_fn(task_id="task1", page_no=1, policy="force_direct")))

    assert result["page_result"] == page_result
    top_level_forbidden = {
        "columns",
        "normalized_rows",
        "rows",
        "source_cells",
        "cell_status",
        "tableRowsContent",
        "tableRowsFormat",
        "raw_html",
        "tables",
    }
    table_item_forbidden = top_level_forbidden - {"tables"}
    assert top_level_forbidden.isdisjoint(result.keys())
    assert top_level_forbidden.isdisjoint(result["page_result"].keys())
    assert table_item_forbidden.isdisjoint(result["page_result"]["elements"]["tables"][0].keys())
    assert table_item_forbidden.isdisjoint(result["page_result"]["rag"]["elements"]["tables"][0].keys())


def test_local_task_chain_persists_layout_and_finalizes_legacy_rag(monkeypatch, tmp_path):
    pdf_path = tmp_path / "mixed-page-fixture.pdf"
    document = fitz.open()
    document.new_page().insert_text((72, 72), "local mixed-page fixture")
    document.save(pdf_path)
    document.close()

    manager = server.TaskManager(str(tmp_path / "output"))
    monkeypatch.setattr(server, "manager", manager)
    start_task_fn = getattr(server.start_task, "fn", server.start_task)
    started = json.loads(
        asyncio.run(start_task_fn(task_name="layout-local-chain", file_path=str(pdf_path), pages=[1]))
    )

    page_result = {
        "task_page_id": "page1",
        "page_no": 1,
        "route_selected": "full_glm_ocr",
        "layout_version": "pdf2md-layout-ledger-v1",
        "layout_status": "EXTRACTED",
        "bbox_space": "normalized_page",
        "page_width": 1.0,
        "page_height": 1.0,
        "layout": [
            {
                "layout_id": "p1-o001-table",
                "source_block_index": 4,
                "type": "table",
                "reading_order": 1,
                "bbox": [0.1, 0.2, 0.9, 0.6],
                "bbox_space": "normalized_page",
                "status": "EXTRACTED",
                "payload_ref": {"collection": "tables", "index": 0},
                "error": None,
            }
        ],
        "reconciliation": {
            "identified": 1,
            "extracted": 1,
            "failed": 0,
            "accounted_for": True,
            "complete": True,
        },
        "render": {"markdown": "| A | B |\n| --- | --- |\n| 1 | 2 |"},
        "rag": {
            "content": "page text",
            "page_text": "page text",
            "elements": {
                "tables": [
                    {
                        "layout_id": "p1-o001-table",
                        "source": "glm_ocr_layout",
                        "title": "",
                        "markdown": "| A | B |\n| --- | --- |\n| 1 | 2 |",
                        "semantic_summary": "table",
                        "context": "",
                        "reading_order": 1,
                        "bbox": [0.1, 0.2, 0.9, 0.6],
                        "bbox_space": "normalized_page",
                    }
                ],
                "formulas": [],
                "figures": [],
            },
        },
        "elements": {"tables": [], "formulas": [], "figures": []},
        "next_context": {},
    }
    monkeypatch.setattr(server, "process_page", lambda *args, **kwargs: page_result)

    process_task_page_fn = getattr(server.process_task_page, "fn", server.process_task_page)
    processed = json.loads(
        asyncio.run(process_task_page_fn(task_id=started["task_id"], page_no=1, policy="force_direct"))
    )

    assert processed["page_result"] == page_result
    assert manager.get_task(started["task_id"]).pages[1].result["layout"] == page_result["layout"]
    persisted = json.loads(
        (tmp_path / "output" / "tasks" / started["task_id"] / "page_1.json").read_text(encoding="utf-8")
    )
    assert persisted["reconciliation"]["complete"] is True
    finalized = manager.finalize_task(started["task_id"], merge_mode="both")
    assert finalized["summary"]["completed_pages"] == [1]
    assert finalized["merged_rag"][0]["rag"]["elements"] == page_result["rag"]["elements"]


def test_single_page_table_schema_is_not_used_by_task_output_elements():
    markdown = "| A | B |\n| --- | --- |\n| 1 | 2 |"
    elements = page_processor._build_output_elements(markdown, {"tables": [markdown], "formulas": [], "figures": []}, "text_only")

    assert elements["tables"] == [
        {
            "source": "pymupdf",
            "title": "",
            "markdown": markdown,
            "semantic_summary": "表格：包含 3 行、2 列。",
            "context": "",
        }
    ]
    forbidden = {"columns", "normalized_rows", "rows", "source_cells", "cell_status", "tableRowsContent", "tableRowsFormat", "raw_html"}
    assert forbidden.isdisjoint(elements["tables"][0].keys())


def test_task_ocr_table_elements_preserve_source_cell_geometry_additively():
    result = normalize_text_response(
        json.dumps(
            {
                "columns": ["牌号", "状态", "规格"],
                "normalized_rows": [["20", "正火", "≤M22"], ["20", "正火", "M24~M48"]],
                "source_cells": [{
                    "row": 1,
                    "col": 0,
                    "text": "20",
                    "rowspan": 2,
                    "colspan": 1,
                    "bbox": [0.10, 0.20, 0.30, 0.60],
                    "bbox_space": "normalized_page",
                    "source_cell_index": 3,
                    "confidence": 0.98,
                }],
                "cell_status": [{"row": 2, "col": 0, "status": "merged_fill", "source_row": 1, "source_col": 0}],
                "bbox": [0.05, 0.10, 0.95, 0.80],
                "bbox_space": "normalized_page",
                "source_cell_row_offset": 1,
            },
            ensure_ascii=False,
        ),
        "glm_ocr",
    )

    structured = page_processor._structured_from_ocr_result(result, include_figures=False)

    assert structured == {
        "tables": ["| 牌号 | 状态 | 规格 |\n| --- | --- | --- |\n| 20 | 正火 | ≤M22 |\n| 20 | 正火 | M24~M48 |"],
        "formulas": [],
        "figures": [],
        "table_metadata": {
            "| 牌号 | 状态 | 规格 |\n| --- | --- | --- |\n| 20 | 正火 | ≤M22 |\n| 20 | 正火 | M24~M48 |": {
                "bbox": [0.05, 0.10, 0.95, 0.80],
                "bbox_space": "normalized_page",
                "columns": ["牌号", "状态", "规格"],
                "normalized_rows": [["20", "正火", "≤M22"], ["20", "正火", "M24~M48"]],
                "source_cells": [{
                    "row": 1,
                    "col": 0,
                    "text": "20",
                    "rowspan": 2,
                    "colspan": 1,
                    "bbox": [0.10, 0.20, 0.30, 0.60],
                    "bbox_space": "normalized_page",
                    "source_cell_index": 3,
                    "confidence": 0.98,
                }],
                "cell_status": [{"row": 2, "col": 0, "status": "merged_fill", "source_row": 1, "source_col": 0}],
                "source_cell_row_offset": 1,
            }
        },
    }

    elements = page_processor._build_output_elements("", structured, "hybrid_glm_ocr")
    table = elements["tables"][0]
    assert table["markdown"] == structured["tables"][0]
    assert table["source_cells"][0]["bbox"] == [0.10, 0.20, 0.30, 0.60]
    assert table["source_cells"][0]["source_cell_index"] == 3
    assert table["bbox_space"] == "normalized_page"
    assert table["source_cell_row_offset"] == 1


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


def test_extract_page_figures_uses_glm_ocr_when_configured(monkeypatch):
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
    assert result["items"][0]["description"] == "ignored figure"
    assert result["items"][0]["semanticDesc"] == "ignored figure"
    assert result["items"][0]["source"] == "glm_ocr"
    assert result["model_calls"] == {"glm_ocr": 1, "vlm_ocr": 0}


def test_extract_page_figures_falls_back_to_vlm_without_glm_ocr(monkeypatch):
    _patch_clients(monkeypatch)

    result = json.loads(
        single_page_tools.extract_page_figures_direct(
            file_data=PNG_DATA,
            input_type="image",
            vlm_config={"model": "vlm", "api_key": "x", "base_url": "http://x"},
        )
    )

    assert result["tool"] == "extract_page_figures"
    assert result["markdown"].startswith("正文段落。")
    assert len(result["items"]) == 1
    assert result["items"][0]["caption"] == "图 1"
    assert result["items"][0]["capture"] == "图 1"
    assert result["items"][0]["name"] == "图 1"
    assert result["items"][0]["figureName"] == "图 1"
    assert result["items"][0]["description"] == "带有 D 和 R 标注的技术示意图。"
    assert result["items"][0]["semanticDesc"] == "带有 D 和 R 标注的技术示意图。"
    assert result["items"][0]["source"] == "vlm_ocr"
    assert result["model_calls"] == {"glm_ocr": 0, "vlm_ocr": 1}
    assert "含插图页面" in FakeVLMClient.prompts[0]
    assert "MUST be written in English" in FakeVLMClient.prompts[0]


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
    assert result["figures"][0]["capture"] == "图 1"
    assert result["figures"][0]["name"] == "图 1"
    assert result["figures"][0]["figureName"] == "图 1"
    assert result["figures"][0]["description"] == "带有 D 和 R 标注的定位技术示意图。"
    assert result["figures"][0]["semanticDesc"] == "带有 D 和 R 标注的定位技术示意图。"
    assert result["model_calls"] == {"glm_ocr": 1, "vlm_ocr": 1}
    assert "image blocks" in FakeVLMClient.prompts[0]
    assert "中文页面请用中文描述" in FakeVLMClient.prompts[0]


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
    assert result["figures"][0]["source"] == "glm_ocr"
    assert result["figures"][0]["capture"] == "图 1"
    assert result["figures"][0]["name"] == "图 1"
    assert result["figures"][0]["figureName"] == "图 1"
    assert result["figures"][0]["description"] == "ignored figure"
    assert result["figures"][0]["semanticDesc"] == "ignored figure"
    assert result["semantic_status"]["complete"] is True


def test_extract_page_figures_accepts_capture_alias_from_vlm(monkeypatch):
    _patch_clients(monkeypatch)
    FakeVLMClient.result_text = json.dumps(
        {
            "markdown": "",
            "figures": [
                {
                    "capture": "图 2 管口结构",
                    "name": "图 2 管口结构",
                    "type": "diagram",
                    "description": "显示管口、壳体和补强圈的连接关系。",
                    "labels": ["A", "B"],
                }
            ],
            "tables": [],
            "formulas": [],
        }
    )

    result = json.loads(
        single_page_tools.extract_page_figures_direct(
            file_data=PNG_DATA,
            input_type="image",
            vlm_config={"model": "vlm", "api_key": "x", "base_url": "http://x"},
        )
    )

    assert result["items"][0]["caption"] == "图 2 管口结构"
    assert result["items"][0]["capture"] == "图 2 管口结构"
    assert result["items"][0]["name"] == "图 2 管口结构"
    assert result["items"][0]["figureName"] == "图 2 管口结构"
    assert result["items"][0]["description"] == "显示管口、壳体和补强圈的连接关系。"
    assert result["items"][0]["semanticDesc"] == "显示管口、壳体和补强圈的连接关系。"
    assert "## 图 2 管口结构" in result["markdown"]
    assert "类型:" in result["markdown"]
    assert "标注: A, B" in result["markdown"]


def test_revise_page_markdown_file_data_custom_prompt_calls_vlm_and_returns_page_text(monkeypatch):
    _patch_clients(monkeypatch)
    FakeVLMClient.result_text = "```markdown\n# Revised\n\n正文\n```"

    result = json.loads(
        single_page_tools.revise_page_markdown_direct(
            file_data=PNG_DATA,
            page_no=27,
            prompt="只按图片重写这一页",
            context={"tenant_id": "t1", "doc_id": "d1", "page_text": "BAD_NORMALIZED_TEXT"},
            vlm_config={"model": "vlm", "api_key": "x", "base_url": "http://x"},
        )
    )

    assert result["pageText"] == "# Revised\n\n正文"
    assert result["page_no"] == 27
    assert result["output_format"] == "markdown"
    assert result["warnings"] == []
    assert result["vlm"]["enabled"] is True
    assert FakeVLMClient.prompts == ["只按图片重写这一页"]


def test_revise_page_markdown_empty_prompt_uses_default_prompt(monkeypatch):
    _patch_clients(monkeypatch)
    FakeVLMClient.result_text = "修订后的正文"

    result = json.loads(
        single_page_tools.revise_page_markdown_direct(
            file_data=PNG_DATA,
            prompt="",
            vlm_config={"model": "vlm", "api_key": "x", "base_url": "http://x"},
        )
    )

    assert result["pageText"] == "修订后的正文"
    assert "请根据这张单页渲染图片" in FakeVLMClient.prompts[0]
    assert "删除页眉、页脚、页码" in FakeVLMClient.prompts[0]
    assert "只输出修订后的页面 Markdown" in FakeVLMClient.prompts[0]


def test_revise_page_markdown_accepts_vlm_config_from_routing_config(monkeypatch):
    _patch_clients(monkeypatch)
    FakeVLMClient.result_text = "通过 routing_config 修订"

    result = json.loads(
        single_page_tools.revise_page_markdown_direct(
            file_data=PNG_DATA,
            routing_config={"vlm_ocr": {"model": "vlm", "api_key": "x", "base_url": "http://x"}},
        )
    )

    assert result["pageText"] == "通过 routing_config 修订"
    assert result["warnings"] == []
    assert result["vlm"]["enabled"] is True


def test_revise_page_markdown_does_not_send_current_page_text_to_vlm(monkeypatch, tmp_path):
    _patch_clients(monkeypatch)
    pdf = tmp_path / "demo.pdf"
    pdf.write_bytes(b"%PDF fake")
    rendered = tmp_path / "page.png"
    rendered.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    monkeypatch.setattr(single_page_tools.fitz, "open", lambda path: FakeDoc())
    monkeypatch.setattr(single_page_tools, "_render_page_image", lambda *args, **kwargs: rendered)
    FakeVLMClient.result_text = "从图片修订"

    result = json.loads(
        single_page_tools.revise_page_markdown_direct(
            file_path=str(pdf),
            page_no=1,
            prompt="重写页面，不要参考旧文本",
            context={"page_text": "BAD_NORMALIZED_TEXT"},
            vlm_config={"model": "vlm", "api_key": "x", "base_url": "http://x"},
        )
    )

    assert result["pageText"] == "从图片修订"
    assert "BAD_NORMALIZED_TEXT" not in FakeVLMClient.prompts[0]
    assert "表 1 参数表" not in FakeVLMClient.prompts[0]


def test_revise_page_markdown_requires_exactly_one_source(monkeypatch):
    _patch_clients(monkeypatch)

    for kwargs in [{}, {"file_data": PNG_DATA, "file_url": "https://example.com/page.png"}]:
        try:
            single_page_tools.revise_page_markdown_direct(
                **kwargs,
                vlm_config={"model": "vlm", "api_key": "x", "base_url": "http://x"},
            )
        except ValueError as exc:
            assert "exactly one source is required" in str(exc)
        else:
            raise AssertionError("expected ValueError")


def test_revise_page_markdown_tool_schema_exposed():
    tool = server.mcp.get_tool("revise_page_markdown")
    if asyncio.iscoroutine(tool):
        tool = asyncio.run(tool)
    schema = tool.parameters
    properties = schema["properties"]

    assert "prompt" in properties
    assert "file_data" in properties
    assert "file_path" in properties
    assert "file_url" in properties


def test_semantic_description_language_defaults_to_english():
    assert single_page_tools._normalize_description_language(None) == "en"
    assert single_page_tools._normalize_description_language("unknown") == "en"
    prompt = single_page_tools._prompt_table_metadata([], "", "unknown")
    assert "MUST be written in English" in prompt
    assert "Do not translate them into Chinese" in prompt


def test_semantic_description_language_supports_chinese():
    assert single_page_tools._normalize_description_language("zh-CN") == "zh"
    prompt = single_page_tools._prompt_table_metadata([], "", "zh-CN")
    assert "必须使用中文" in prompt


def test_completion_tool_schemas_expose_description_language():
    for tool_name in (
        "extract_page_tables",
        "extract_page_formulas",
        "extract_page_figures",
        "extract_page_structured",
    ):
        tool = server.mcp.get_tool(tool_name)
        if asyncio.iscoroutine(tool):
            tool = asyncio.run(tool)
        assert tool.parameters["properties"]["description_language"]["default"] == "en"
