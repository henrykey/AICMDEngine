import copy
import pytest
import importlib
from tests.test_pdf2md_enhanced_single_page_tools import single_page_tools
enhance_object_semantics = importlib.import_module(single_page_tools.__package__ + ".object_semantics").enhance_object_semantics


def request(kind="formula"):
    return {"element_type": kind, "element_id": "o1", "document_language": "zh",
            "missing_fields": ["semantic_desc"], "candidate_object": {"latex": "Q=KA"}, "local_context": ""}


class Provider:
    def __init__(self, response):
        self.response = response
        self.calls = 0
    def _call_text_prompt(self, prompt, **kwargs):
        self.calls += 1
        assert "Chinese" in prompt
        assert "untrusted" in prompt
        return self.response


@pytest.mark.parametrize("kind,group", [("formula", "formulas"), ("table", "tables"), ("figure", "figures")])
def test_exact_object_and_source_preserved(kind, group):
    import json
    source = request(kind); before = copy.deepcopy(source)
    p = Provider(json.dumps({group: [{"element_id": "o1", "semantic_desc": "有依据的对象说明"}]}))
    result = enhance_object_semantics(source, {}, provider_factory=lambda cfg: p)
    assert result["status"] == "complete"
    assert result["model_calls"] == 1
    assert result["quality"]["evidence_basis"] == "supplied_text_not_image_verified"
    assert source == before


@pytest.mark.parametrize("response", ['{"formulas":[{"element_id":"other","semantic_desc":"x"}]}',
    '{"formulas":[]}', '{"formulas":[{"element_id":"o1","latex":"changed"}]}'])
def test_invalid_proposals_never_applied(response):
    result = enhance_object_semantics(request(), {}, provider_factory=lambda cfg: Provider(response))
    assert result["status"] == "failed"
    assert "repairs" not in result


def test_invalid_input_blocks_before_provider():
    def forbidden(cfg):
        pytest.fail("provider created")
    result = enhance_object_semantics({**request(), "element_id": ""}, {}, provider_factory=forbidden)
    assert result["model_calls"] == 0
    assert result["status"] == "failed"


def test_initialization_failure_is_sanitized():
    def fail(cfg):
        raise ValueError("secret")
    result = enhance_object_semantics(request(), {}, provider_factory=fail)
    assert result["reason"] == "model_initialization_failed"
    assert result["model_calls"] == 0
    assert "secret" not in str(result)


@pytest.mark.parametrize("change", [{"element_type": []}, {"missing_fields": [[]]}, {"missing_fields": []},
    {"missing_fields": ["latex"]}, {"document_language": "unknown"}])
def test_invalid_contract_never_creates_provider(change):
    def forbidden(cfg):
        pytest.fail("provider created")
    assert enhance_object_semantics({**request(), **change}, {}, provider_factory=forbidden)["model_calls"] == 0


def test_english_and_request_binding():
    class EnglishProvider:
        def _call_text_prompt(self, prompt, **kwargs):
            assert "MUST be written in English" in prompt
            return '{"formulas":[{"element_id":"o1","semantic_desc":"Calculates heat transfer."}]}'
    result = enhance_object_semantics({**request(), "document_language": "en", "request_id": "request-1"},
        {}, provider_factory=lambda cfg: EnglishProvider())
    assert result["request_id"] == "request-1"


def test_provider_failure_has_no_hidden_second_call():
    class FailingProvider:
        calls = 0
        def _call_text_prompt(self, prompt, **kwargs):
            self.calls += 1
            raise RuntimeError("private source payload")
    provider = FailingProvider()
    result = enhance_object_semantics(request(), {}, provider_factory=lambda cfg: provider)
    assert result["reason"] == "provider_call_failed"
    assert provider.calls == 1
    assert "private" not in str(result)


@pytest.mark.parametrize("extra", ['"semantic_confidence":true', '"semantic_confidence":2', '"latex":"replacement"'])
def test_invalid_quality_or_source_mutation_is_rejected(extra):
    provider = Provider('{"formulas":[{"element_id":"o1","semantic_desc":"说明",' + extra + '}]}')
    assert enhance_object_semantics(request(), {}, provider_factory=lambda cfg: provider)["status"] == "failed"


def test_registered_tool_exposes_router_provider_config(monkeypatch):
    import asyncio
    import json
    from tests.test_pdf2md_enhanced_single_page_tools import server
    module = importlib.import_module(single_page_tools.__package__ + ".object_semantics")
    provider = Provider('{"formulas":[{"element_id":"o1","semantic_desc":"对象说明"}]}')
    monkeypatch.setattr(module, "DynamicVLMClient", lambda cfg: provider)
    async def invoke():
        tool = await server.mcp.get_tool("enhance_object_semantics")
        assert "vlm_config" in tool.parameters["properties"]
        assert "request" in tool.parameters["properties"]
        return await tool.run({"request": request()})
    result = asyncio.run(invoke())
    assert json.loads(result.content[0].text)["status"] == "complete"


@pytest.mark.parametrize("dockerfile", ["Dockerfile", "Dockerfile.cn"])
def test_packaged_semantic_module_imports_without_source_checkout(tmp_path, dockerfile):
    """Reproduce the explicit Docker COPY payload in an isolated Python process."""
    from pathlib import Path
    import shlex
    import shutil
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[1] / "mcp/servers/PDF2MDEnhanced"
    package = tmp_path / "PDF2MDEnhanced"
    package.mkdir()
    for line in (root / dockerfile).read_text().splitlines():
        if line.startswith("COPY ") and line.endswith(" /app/PDF2MDEnhanced/"):
            for source in shlex.split(line)[1:-1]:
                shutil.copy2(root / source, package / source)
    result = subprocess.run([sys.executable, "-I", "-c",
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "from PDF2MDEnhanced.object_semantics import enhance_object_semantics; "
        "assert enhance_object_semantics({})['model_calls'] == 0", str(tmp_path)],
        cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_object_semantics_uses_existing_physical_request_guard():
    configs = []
    provider = Provider('{"formulas":[{"element_id":"o1","semantic_desc":"对象说明"}]}')
    def factory(config):
        configs.append(config)
        return provider
    enhance_object_semantics(request(), {"max_retries": 4}, provider_factory=factory)
    assert configs[0]["max_retries"] == 0
    assert configs[0]["table_analysis_max_physical_requests"] == 1
    assert configs[0]["_calculation_processing"]


@pytest.mark.parametrize("tool", ["semantics", "query"])
def test_single_tool_http_failure_never_sends_a_hidden_retry(monkeypatch, tool):
    import httpx
    import openai
    from tests.test_pdf2md_enhanced_table_query import request as query_request, run
    sent, clients = [], []
    def handle(request):
        sent.append(request)
        return httpx.Response(503)
    def factory(**kwargs):
        client = httpx.Client(transport=httpx.MockTransport(handle), **kwargs)
        clients.append(client)
        return client
    monkeypatch.setattr(openai, "DefaultHttpxClient", factory)
    config = {"model": "fixture", "api_key": "fixture", "base_url": "https://fixture.invalid/v1", "max_retries": 9, "context_window": 32768}
    try:
        if tool == "semantics":
            out = enhance_object_semantics(request(), config)
        else:
            req = query_request(); req.update(max_model_calls=1, query_strategy="semantic_review")
            out = run(req, vlm_config=config)["query_enhancement"]
        assert len(sent) == out["physical_requests"] == out["model_calls"] == 1
    finally:
        for client in clients:
            client.close()

@pytest.mark.parametrize("fails", [False, True])
def test_single_object_image_uses_one_call_and_cleans_transport(fails):
    import base64
    import io
    from pathlib import Path
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buffer, format="PNG")
    encoded = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
    paths = []
    class ImageProvider:
        def _call_image_prompt(self, path, prompt, **kwargs):
            assert Path(path).is_file()
            assert "attached object image" in prompt
            assert encoded not in prompt
            paths.append(path)
            if fails:
                raise RuntimeError("private provider data")
            return '{"figures":[{"element_id":"o1","semantic_desc":"示意图展示装置连接关系。"}]}'
        def _call_text_prompt(self, *args, **kwargs):
            pytest.fail("image must not be replaced by text")
    result = enhance_object_semantics(request("figure"), image_data=encoded,
                                     provider_factory=lambda cfg: ImageProvider())
    assert result["model_calls"] == 1
    assert len(paths) == 1 and not Path(paths[0]).exists()
    assert result["status"] == ("failed" if fails else "complete")
    if not fails:
        assert result["quality"]["evidence_basis"] == "supplied_object_image"


def test_invalid_object_image_never_calls_provider():
    def forbidden(cfg):
        pytest.fail("provider created for invalid image")
    result = enhance_object_semantics(request("figure"), image_data="not-an-image", provider_factory=forbidden)
    assert result["model_calls"] == 0
    assert result["reason"] == "invalid_object_image"


@pytest.mark.parametrize("kind", ["figure", "formula", "table"])
def test_generic_figure_guidance_only_applies_to_figures(kind):
    import json
    observed = []
    class Capture(Provider):
        def _call_text_prompt(self, prompt, **kwargs):
            observed.append(prompt)
            return self.response
    group = {"figure": "figures", "formula": "formulas", "table": "tables"}[kind]
    provider = Capture(json.dumps({group: [{"element_id": "o1", "semantic_desc": "图片展示主要内容及相关信息。"}]}))
    enhance_object_semantics(request(kind), provider_factory=lambda cfg: provider)
    assert ("1000 characters" in observed[0]) == (kind == "figure")
    if kind == "figure":
        assert "Do not guess when uncertain" in observed[0]
        assert "do not assume a particular image type" in observed[0]


def test_figure_entry_prompts_share_generic_guidance():
    for prompt in [single_page_tools._prompt_figures(""), single_page_tools._prompt_figure_page(""),
                   single_page_tools._prompt_layout_figures([], "")]:
        assert "1000 characters" in prompt
        assert "key information needed to understand" in prompt
        assert "Avoid repetition and irrelevant details" in prompt
        assert "Do not guess when uncertain" in prompt
