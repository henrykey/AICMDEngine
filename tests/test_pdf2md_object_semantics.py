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


def test_table_semantics_accepts_fenced_json_without_weakening_object_validation():
    provider = Provider('```json\n{"tables":[{"element_id":"o1","semantic_desc":"本表用于根据焊接形式和检测范围选择系数。"}]}\n```')
    result = enhance_object_semantics(request('table'), {}, provider_factory=lambda cfg: provider)
    assert result['status'] == 'complete'
    assert result['repairs']['tables'][0]['element_id'] == 'o1'
    invalid = Provider('```json\n{"tables":[{"element_id":"other","semantic_desc":"表格说明"}]}\n```')
    assert enhance_object_semantics(request('table'), {}, provider_factory=lambda cfg: invalid)['status'] == 'failed'


def test_page_table_mapping_uses_unique_layout_identity_not_order():
    originals = [{'layout_id': 'layout-a', 'markdown': 'A'}, {'layout_id': 'layout-b', 'markdown': 'B'}]
    targets = [{'table_id': 'p11_t2', 'layout_id': 'layout-b'}, {'table_id': 'p11_t1', 'layout_id': 'layout-a'}]
    mapped = single_page_tools._map_semantic_table_targets(targets, originals)
    assert mapped['p11_t1']['markdown'] == 'A'
    assert mapped['p11_t2']['markdown'] == 'B'


@pytest.mark.parametrize('targets,originals', [
    ([{'table_id': 'a', 'layout_id': 'l'}], []),
    ([{'table_id': 'a', 'layout_id': 'l'}], [{'layout_id': 'l'}, {'layout_id': 'l'}]),
    ([{'table_id': 'a', 'layout_id': 'l'}, {'table_id': 'b', 'layout_id': 'l'}], [{'layout_id': 'l'}]),
    ([{'table_id': 'a', 'layout_id': 'l'}, {'table_id': 'a', 'layout_id': 'm'}], [{'layout_id': 'l'}, {'layout_id': 'm'}]),
    ([{'table_id': 'a'}], [{'layout_id': 'l'}]),
])
def test_page_table_mapping_fails_closed_for_missing_or_ambiguous_identity(targets, originals):
    with pytest.raises(ValueError):
        single_page_tools._map_semantic_table_targets(targets, originals)


def test_original_page_requires_exact_identity_and_matching_image_hash(tmp_path):
    import hashlib
    import json
    from tests.test_pdf2md_enhanced_task_manager import TaskManager
    root = tmp_path / 'output'; uploads = root / 'uploads'; uploads.mkdir(parents=True)
    image = uploads / 'page.png'; image.write_bytes(b'original page')
    task_id = 'task_1234567890abcdef'; task_dir = root / 'tasks' / task_id; task_dir.mkdir(parents=True)
    identity = {'tenant_id': '33', 'doc_id': 'doc', 'run_id': 'run', 'version': 1,
                'source_page_no': 11, 'source_file_sha256': 'a' * 64, 'render_dpi': 150}
    record = {'task_id': task_id, 'source_identity': identity, 'source_path': str(image),
              'input_image': {'sha256': hashlib.sha256(image.read_bytes()).hexdigest()}}
    (task_dir / 'task.json').write_text(json.dumps(record))
    (task_dir / 'page_1.json').write_text(json.dumps({'source_identity': identity, 'elements': {'tables': []}}))
    manager = TaskManager(str(root))
    content, result = manager.read_original_page(identity)
    assert content == b'original page'
    assert result['source_identity'] == identity
    for field, wrong in [('tenant_id', '34'), ('doc_id', 'other'), ('version', 2), ('source_page_no', 12)]:
        with pytest.raises(ValueError):
            manager.read_original_page({**identity, field: wrong})
    image.write_bytes(b'tampered')
    with pytest.raises(ValueError, match='identity_mismatch'):
        manager.read_original_page(identity)


def test_saved_page_table_semantics_maps_results_by_original_identity(monkeypatch):
    class Manager:
        def read_original_page(self, identity):
            assert identity == {'run_id': 'verified'}
            return b'page', {'elements': {'tables': [
                {'layout_id': 'a', 'markdown': '|a|'}, {'layout_id': 'b', 'markdown': '|b|'}]},
                'rag': {'page_text': 'page context'}}
    class Model:
        enabled = True
        max_tokens = 4096
        last_call_info = {}
        def __init__(self, config): pass
        def _call_image_prompt(self, path, prompt, **kwargs):
            assert 'page context' in prompt
            return '{"tables":[{"index":1,"semanticDesc":"表格二的用途"},{"index":0,"semanticDesc":"表格一的用途"}]}'
    monkeypatch.setattr(single_page_tools, 'DynamicVLMClient', Model)
    targets = [{'table_id': 'first', 'layout_id': 'a'}, {'table_id': 'second', 'layout_id': 'b'}]
    result = single_page_tools.enhance_saved_page_table_semantics(Manager(), {'run_id': 'verified'}, targets, {}, 'zh')
    assert result == {'tables': [{'table_id': 'first', 'semantic_desc': '表格一的用途'},
                                 {'table_id': 'second', 'semantic_desc': '表格二的用途'}], 'model_calls': 1}


def test_page_semantic_tool_routes_table_and_rejects_other_types(monkeypatch):
    import asyncio
    import json
    server = importlib.import_module(single_page_tools.__package__ + ".server")
    calls = []
    def describe(manager, identity, targets, config, language, fallback_page=None):
        calls.append((identity, targets, language))
        return {'tables': [{'table_id': 't1', 'semantic_desc': '表的用途'}], 'model_calls': 1}
    monkeypatch.setattr(single_page_tools, 'enhance_saved_page_table_semantics', describe)
    async def check():
        tools = await server.mcp.list_tools()
        assert 'enhance_page_object_semantics' in [tool.name for tool in tools]
        # Call the registered tool so validation and routing follow the public contract.
        tool = next(tool for tool in tools if tool.name == 'enhance_page_object_semantics')
        result = await tool.run({'object_type': 'table', 'source_identity': {'tenant_id': '33'},
                                 'targets': [{'table_id': 't1', 'layout_id': 'a'}],
                                 'description_language': 'zh'})
        assert '表的用途' in str(result)
        with pytest.raises(Exception, match='unsupported_page_object_type'):
            await tool.run({'object_type': 'figure', 'source_identity': {}, 'targets': []})
    asyncio.run(check())
    assert len(calls) == 1


def test_page_table_semantics_falls_back_only_when_original_missing(monkeypatch):
    class Manager:
        def __init__(self, reason): self.reason = reason
        def read_original_page(self, identity): raise ValueError(self.reason)
    class Model:
        enabled = True
        max_tokens = 4096
        last_call_info = {}
        def __init__(self, config): pass
        def _call_text_prompt(self, prompt, **kwargs):
            assert "full page context" in prompt and "table evidence" in prompt
            return '{"tables":[{"index":0,"semanticDesc":"说明表格用途"}]}'
    monkeypatch.setattr(single_page_tools, "DynamicVLMClient", Model)
    targets = [{"table_id": "t", "layout_id": "l"}]
    fallback = {"page_text": "full page context", "tables": [{"layout_id": "l", "markdown": "table evidence"}]}
    result = single_page_tools.enhance_saved_page_table_semantics(
        Manager("original_page_unavailable"), {"tenant_id": "33"}, targets, {}, "zh", fallback)
    assert result["tables"] == [{"table_id": "t", "semantic_desc": "说明表格用途"}]
    with pytest.raises(ValueError, match="original_page_identity_mismatch"):
        single_page_tools.enhance_saved_page_table_semantics(
            Manager("original_page_identity_mismatch"), {"tenant_id": "33"}, targets, {}, "zh", fallback)


def test_page_formula_semantics_original_and_text_fallback(monkeypatch):
    class Manager:
        def read_original_page(self, identity):
            if identity.get('missing'):
                raise ValueError('original_page_unavailable')
            return b'page', {'elements': {'formulas': [
                {'layout_id': 'a', 'latex': 'C=C1+C2'}, {'layout_id': 'b', 'latex': 'P=F/A'}]},
                'rag': {'page_text': '厚度与压力'}}
    class Model:
        enabled = True
        max_tokens = 4096
        last_call_info = {}
        def __init__(self, config): pass
        def _call_image_prompt(self, path, prompt, **kwargs):
            assert 'C=C1+C2' in prompt and '厚度与压力' in prompt
            assert kwargs['max_tokens'] == 4096
            assert '公式的用途' in prompt and '不能只重复公式名称' in prompt and '说明应简洁' in prompt
            return '{"formulas":[{"index":1,"description":"计算压力"},{"index":0,"description":"计算厚度"}]}'
        def _call_text_prompt(self, prompt, **kwargs):
            assert 'C=C1+C2' in prompt
            assert kwargs['max_tokens'] == 4096
            return '{"formulas":[{"index":0,"description":"计算厚度"},{"index":1,"description":"计算压力"}]}'
    monkeypatch.setattr(single_page_tools, 'DynamicVLMClient', Model)
    targets = [{'formula_id': 'f1', 'layout_id': 'a'}, {'formula_id': 'f2', 'layout_id': 'b'}]
    expected = {'formulas': [{'formula_id': 'f1', 'semantic_desc': '计算厚度'},
                             {'formula_id': 'f2', 'semantic_desc': '计算压力'}], 'model_calls': 1}
    assert single_page_tools.enhance_saved_page_formula_semantics(Manager(), {'run_id': 'ok'}, targets, {}, 'zh') == expected
    fallback = {'page_text': '厚度与压力', 'formulas': [{'layout_id': 'a', 'latex': 'C=C1+C2'}, {'layout_id': 'b', 'latex': 'P=F/A'}]}
    assert single_page_tools.enhance_saved_page_formula_semantics(Manager(), {'missing': True}, targets, {}, 'zh', fallback) == expected
    with pytest.raises(ValueError):
        single_page_tools.enhance_saved_page_formula_semantics(Manager(), {'missing': True}, targets, {}, 'zh')


def test_page_formula_semantics_rejects_ambiguous_mapping():
    class Manager:
        def read_original_page(self, identity):
            return b'page', {'elements': {'formulas': [{'layout_id': 'a'}, {'layout_id': 'a'}]}}
    with pytest.raises(ValueError, match='ambiguous'):
        single_page_tools.enhance_saved_page_formula_semantics(Manager(), {'run_id': 'ok'}, [{'formula_id': 'f', 'layout_id': 'a'}], {}, 'zh')


def test_registered_page_tool_routes_formula(monkeypatch):
    import asyncio
    server = importlib.import_module(single_page_tools.__package__ + ".server")
    calls = []
    def describe(manager, identity, targets, config, language, fallback_page=None):
        calls.append(targets)
        return {'formulas': [{'formula_id': 'f1', 'semantic_desc': '计算厚度'}], 'model_calls': 1}
    monkeypatch.setattr(single_page_tools, 'enhance_saved_page_formula_semantics', describe)
    async def check():
        tool = next(tool for tool in await server.mcp.list_tools() if tool.name == 'enhance_page_object_semantics')
        result = await tool.run({'object_type': 'formula', 'source_identity': {'tenant_id': '33'},
                                 'targets': [{'formula_id': 'f1', 'layout_id': 'a'}], 'description_language': 'zh'})
        assert '计算厚度' in str(result)
    asyncio.run(check())
    assert len(calls) == 1


def test_single_formula_prompt_requires_relationships_not_just_title():
    class FormulaProvider(Provider):
        def _call_text_prompt(self, prompt, **kwargs):
            assert 'how its terms determine the result' in prompt and 'Be concise' in prompt
            assert 'title or name alone is not a description' in prompt
            return super()._call_text_prompt(prompt, **kwargs)
    provider = FormulaProvider('{"formulas":[{"element_id":"o1","semantic_desc":"说明变量间的计算关系"}]}')
    assert enhance_object_semantics(request(), {}, provider_factory=lambda cfg: provider)['status'] == 'complete'
