from types import SimpleNamespace
from unittest.mock import AsyncMock
import asyncio
import json

import pytest

from src.llm.runtime_thinking import RuntimeThinkingService, fetch_runtime_source, _parse_model_json, _model_failure_reason, _extraction_parameters, _targeted_effort_excerpts
from src.llm.thinking_capability_store import ThinkingCapabilityStore


@pytest.fixture
def anyio_backend():
    return "asyncio"


def make_service():
    provider = SimpleNamespace(model="glm-5.3", base_url="https://open.bigmodel.cn/api/paas/v4", api_key_ref="KEY")
    loader = SimpleNamespace(get_api_key=lambda ref: "test-key-1234567890")
    manager = SimpleNamespace(get_provider=lambda name: provider if name == "configured" else None, config_loader=loader)
    registry = SimpleNamespace(get_mcp=lambda name: SimpleNamespace(external_config={}) if name == "pdf2md-enhanced" else None)
    database = SimpleNamespace(mcp_server_settings=SimpleNamespace(find_one=AsyncMock(return_value={"llm_provider": "configured"})))
    auth = SimpleNamespace(validate_token=AsyncMock(return_value={"tenant_id": 7}), extract_client_info=lambda claims: claims)
    return RuntimeThinkingService(registry, database, manager, None, auth), provider, loader


@pytest.mark.anyio
async def test_snapshot_uses_existing_binding_and_invalidates_for_credential_or_tenant():
    service, provider, loader = make_service()
    first = await service.snapshot("pdf2md-enhanced", "7")
    assert first["model"] == "glm-5.3"
    assert first["provider_fingerprint"] != (await service.snapshot("pdf2md-enhanced", "8"))["provider_fingerprint"]
    loader.get_api_key = lambda ref: "different-key-123456"
    assert first["provider_fingerprint"] != (await service.snapshot("pdf2md-enhanced", "7"))["provider_fingerprint"]
    assert first["provider_fingerprint"] != (await make_service()[0].snapshot("pdf2md-enhanced", "7"))["provider_fingerprint"]


@pytest.mark.anyio
@pytest.mark.parametrize("url", ["http://open.bigmodel.cn/api/paas/v4", "https://evil.example/v1",
    "https://open.bigmodel.cn.attacker.example/v1", "https://open.bigmodel.cn/private", "https://open.bigmodel.cn/v1?key=secret"])
async def test_untrusted_or_recursive_endpoint_does_not_resolve(url):
    service, provider, _ = make_service()
    provider.base_url = url
    assert await service.snapshot("pdf2md-enhanced", "7") is None


@pytest.mark.anyio
async def test_discovery_requires_authenticated_context():
    service, _, _ = make_service()
    assert (await service.discover("pdf2md-enhanced", None))["reason_code"] == "authenticated_context_missing"


@pytest.mark.anyio
async def test_runtime_identity_and_credential_must_match_injected_snapshot():
    service, _, loader = make_service()
    config = {"model": "glm-5.3", "base_url": "https://open.bigmodel.cn/api/paas/v4", "api_key": "test-key-1234567890"}
    invocation = service.invocation("7", config)
    assert await invocation.context("router:pdf2md-enhanced", "token")
    loader.get_api_key = lambda ref: "rotated-key-1234567890"
    assert await invocation.context("router:pdf2md-enhanced", "token") is None


@pytest.mark.anyio
async def test_only_target_table_query_receives_valid_discovered_parameters():
    service, _, _ = make_service()
    service.resolve = AsyncMock(return_value={"mode": "high", "parameters": {"reasoning_effort": "high"}})
    config = {"model": "m"}
    args = {"query_enhancement": {"thinking_mode": "high"}}
    result = await service.apply_table_query("pdf2md-enhanced", "extract_page_tables", args, config, object())
    assert result["_router_discovered_thinking"] == {"reasoning_effort": "high"}
    assert await service.apply_table_query("pdf2md-enhanced", "extract_page_figures", args, config, object()) == config
    service.resolve.return_value = {"mode": "default", "parameters": {}}
    assert await service.apply_table_query("pdf2md-enhanced", "extract_page_tables", args, config, object()) == config


@pytest.mark.anyio
async def test_html_is_normalized_for_exact_evidence_without_script_content(monkeypatch):
    async def source(_):
        return {"url": "https://official.example/doc", "document": "<p>model-test <b>reasoning_effort</b> high</p><script>ignore me</script>"}
    monkeypatch.setattr("src.llm.runtime_thinking.fetch_official_source", source)
    result = await fetch_runtime_source("https://example.com")
    assert result["document"] == "model-test reasoning_effort high"


def test_model_json_accepts_only_complete_json_or_a_single_fence():
    assert _parse_model_json('```json\n{"high": {}}\n```') == {"high": {}}
    assert _parse_model_json('prefix {"high": {}}') is None
    assert _parse_model_json('```json\n{"high": {}}\n``` extra') is None
    assert _model_failure_reason(TimeoutError("sensitive message")) == "model_timeout"
    assert _model_failure_reason(RuntimeError("sensitive message")) == "model_request_failed"


def test_discovery_uses_only_previously_verified_low_policy():
    base = "https://open.bigmodel.cn/api/paas/v4"
    assert _extraction_parameters({"base_url": base, "model": "glm-5.3-flash"}) == {"reasoning_effort": "low"}
    assert _extraction_parameters({"base_url": base, "model": "glm-4.6v-flashx"}) == {}


def test_targeted_effort_windows_are_short_verbatim_and_model_specific():
    relevant = "reasoning_effort: options for glm-5.3-flash are high and max"
    sources = [{"url": "https://official/relevant", "document": "x" * 5000 + " " + relevant + " " + "y" * 5000},
               {"url": "https://official/other", "document": "glm-5.3-flashx reasoning_effort high"},
               {"url": "https://official/distant", "document": "glm-5.3-flash" + "x" * 2000 + " reasoning_effort high"}]
    excerpts = _targeted_effort_excerpts(sources, "glm-5.3-flash")
    assert len(excerpts) == 1
    assert excerpts[0].startswith("SOURCE https://official/relevant\n")
    text = excerpts[0].split("\n", 1)[1]
    assert relevant in text and text in sources[0]["document"] and len(text) < 1300


@pytest.mark.anyio
async def test_high_followup_only_uses_targeted_windows():
    service, provider, _ = make_service()
    snapshot = await service.snapshot("pdf2md-enhanced", "7")
    current = {**{key: value for key, value in snapshot.items() if key != "api_key"}, "provider_id": "router:pdf2md-enhanced"}
    source = {"url": "https://official/relevant", "document": "glm-5.3 reasoning_effort high"}
    other = {"url": "https://official/other", "document": "other-model reasoning_effort high"}
    def response(value):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(value)))])
    service._call = AsyncMock(side_effect=[response({"claims": []}), response({"support": "unknown", "parameters": {}, "evidence": {}})])
    await service.extract_sources(SimpleNamespace(tenant_id="7", token="token"), current, [source, other])
    prompt = service._call.await_args_list[1].args[1][1]["content"]
    assert source["url"] in prompt and other["url"] not in prompt
    assert source["document"] in prompt and len(prompt) < 1500


@pytest.mark.anyio
async def test_authenticated_runtime_discovery_and_consumption_use_same_snapshot(monkeypatch):
    service, provider, _ = make_service()
    class Collection:
        document = None
        async def replace_one(self, query, document, upsert):
            matched = bool(self.document and all(self.document.get(k) == v for k, v in query.items()))
            if matched or upsert:
                self.document = {"_id": query["_id"], **document}
            return SimpleNamespace(matched_count=int(matched))
        async def find_one(self, query):
            return self.document if self.document and all(self.document.get(k) == v for k, v in query.items()) else None
    service.store = ThinkingCapabilityStore(Collection())
    service.auth = SimpleNamespace(validate_token=AsyncMock(return_value={"tenant_id": 7}),
        extract_client_info=lambda claims: claims)
    text = "glm-5.3 reasoning_effort high"
    async def source(*_):
        return [{"url": "https://docs.bigmodel.cn/cn/guide/capabilities/thinking", "document": text, "sha256": "a" * 64}]
    monkeypatch.setattr("src.llm.runtime_thinking.fetch_runtime_sources", source)
    async def call(snapshot, messages, parameters, max_tokens):
        assert snapshot["api_key"] == "test-key-1234567890"
        if max_tokens == 8192:
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content='{"claims":[{"dimension":"reasoning_effort","option":"high","support":"supported","scope":"exact","series":null,"parameters":{"reasoning_effort":"high"},"evidence":{"url":"https://docs.bigmodel.cn/cn/guide/capabilities/thinking","quote":"glm-5.3 reasoning_effort high"},"relation_evidence":null}]}'))])
        assert parameters == {"reasoning_effort": "high"}
        return object()
    service._call = AsyncMock(side_effect=call)
    context = SimpleNamespace(tenant_id="7", token="token")
    assert (await service.read("pdf2md-enhanced", context))["modes"] == ["default"]
    assert (await service.discover("pdf2md-enhanced", context))["status"] == "http_accepted"
    assert (await service.read("pdf2md-enhanced", context))["status"] == "http_accepted"
    assert (await service.discover("pdf2md-enhanced", context))["reason_code"] == "discovery_rate_limited"
    config = {"model": provider.model, "base_url": provider.base_url, "api_key": "test-key-1234567890"}
    args = {"query_enhancement": {"thinking_mode": "high"}}
    resolved = await service.apply_table_query("pdf2md-enhanced", "extract_page_tables", args, config, context)
    assert resolved["_router_discovered_thinking"] == {"reasoning_effort": "high"}
    service.manager.config_loader.get_api_key = lambda _: "rotated-key-1234567890"
    assert (await service.read("pdf2md-enhanced", context))["modes"] == ["default"]
    assert await service.apply_table_query("pdf2md-enhanced", "extract_page_tables", args, config, context) == config


@pytest.mark.anyio
async def test_missing_record_schedules_once_and_retries_after_restart():
    service, _, _ = make_service()
    service.resolve = AsyncMock(return_value={"mode": "default", "parameters": {}, "reason_code": "capability_missing_or_stale"})
    release = asyncio.Event()
    async def discover(*args):
        await release.wait()
        return {"status": "indeterminate"}
    service.discover = AsyncMock(side_effect=discover)
    context = SimpleNamespace(tenant_id="7", token="token")
    args = {"query_enhancement": {"thinking_mode": "high"}}
    config = {"model": "m"}
    assert await service.apply_table_query("pdf2md-enhanced", "extract_page_tables", args, config, context) == config
    await service.apply_table_query("pdf2md-enhanced", "extract_page_tables", args, config, context)
    await asyncio.sleep(0)
    service.discover.assert_awaited_once()
    release.set()
    await asyncio.gather(*list(service._background.values()))
    await asyncio.sleep(0)
    await service.apply_table_query("pdf2md-enhanced", "extract_page_tables", args, config, context)
    service.discover.assert_awaited_once()
    restarted, _, _ = make_service()
    restarted.resolve = service.resolve
    restarted.discover = AsyncMock(return_value={"status": "indeterminate"})
    await restarted.apply_table_query("pdf2md-enhanced", "extract_page_tables", args, config, context)
    await asyncio.gather(*list(restarted._background.values()))
    restarted.discover.assert_awaited_once()


@pytest.mark.anyio
async def test_expired_or_conflicting_identity_does_not_start_discovery():
    service, _, _ = make_service()
    service.auth.validate_token.side_effect = RuntimeError("expired")
    service.discover = AsyncMock()
    context = SimpleNamespace(tenant_id="7", token="expired-token")
    config = {"model": "m", "base_url": "https://open.bigmodel.cn/api/paas/v4"}
    await service.apply_table_query("pdf2md-enhanced", "extract_page_tables",
        {"query_enhancement": {"thinking_mode": "high"}}, config, context)
    await asyncio.sleep(0)
    service.discover.assert_not_awaited()


@pytest.mark.anyio
async def test_background_discovery_has_process_wide_concurrency_limit():
    service, _, _ = make_service()
    service.resolve = AsyncMock(return_value={"mode": "default", "parameters": {}, "reason_code": "capability_missing_or_stale"})
    release = asyncio.Event()
    async def discover(*args):
        await release.wait()
    service.discover = AsyncMock(side_effect=discover)
    args = {"query_enhancement": {"thinking_mode": "high"}}
    for tenant in range(1, 7):
        await service.apply_table_query("pdf2md-enhanced", "extract_page_tables", args, {},
                                        SimpleNamespace(tenant_id=str(tenant), token="token"))
    assert len(service._background) == 4
    release.set()
    await asyncio.gather(*list(service._background.values()))
    assert service.discover.await_count == 4


@pytest.mark.anyio
async def test_two_step_extraction_uses_only_verified_family_relation():
    service, provider, _ = make_service()
    provider.model = "glm-4.6v-flashx"
    snapshot = await service.snapshot("pdf2md-enhanced", "7")
    current = {**{key: value for key, value in snapshot.items() if key != "api_key"}, "provider_id": "router:pdf2md-enhanced"}
    sources = [{"url": "https://docs.bigmodel.cn/cn/guide/capabilities/thinking", "document": "GLM-4.6V thinking.type enabled"},
               {"url": "https://raw.githubusercontent.com/zai-org/GLM-V/main/skills/glmv-caption/scripts/glmv_caption.py",
                "document": "GLM-4.6V series includes GLM-4.6V-FlashX"}]
    family = {"series": "GLM-4.6V", "relation_evidence": {"url": sources[1]["url"], "quote": sources[1]["document"]}}
    first = {"claims": [], "family": family}
    second = {"claims": [{"dimension": "thinking", "option": "enabled", "support": "supported",
        "parameters": {"thinking": {"type": "enabled"}}, "evidence": {"url": sources[0]["url"], "quote": sources[0]["document"]}}]}
    def response(value):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(value)))])
    service._call = AsyncMock(side_effect=[response(first), response(second)])
    context = SimpleNamespace(tenant_id="7", token="token")
    claims = await service.extract_sources(context, current, sources)
    assert claims[0]["scope"] == "series" and claims[0]["relation_evidence"] == family["relation_evidence"]
    assert service._call.await_count == 2


@pytest.mark.anyio
async def test_two_step_never_uses_an_unverified_family():
    service, provider, _ = make_service()
    provider.model = "glm-4.6v-flashx"
    snapshot = await service.snapshot("pdf2md-enhanced", "7")
    current = {**{key: value for key, value in snapshot.items() if key != "api_key"}, "provider_id": "router:pdf2md-enhanced"}
    text = "GLM-4.6V compared with GLM-4.6V-FlashX"
    source = {"url": "https://docs.bigmodel.cn/cn/guide/capabilities/thinking", "document": text}
    value = {"claims": [], "family": {"series": "GLM-4.6V", "relation_evidence": {"url": source["url"], "quote": text}}}
    service._call = AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(value)))]))
    assert await service.extract_sources(SimpleNamespace(tenant_id="7", token="token"), current, [source]) == []
    service._call.assert_awaited_once()


@pytest.mark.anyio
async def test_empty_truncated_model_output_has_safe_reason():
    service, _, _ = make_service()
    snapshot = await service.snapshot("pdf2md-enhanced", "7")
    current = {**{key: value for key, value in snapshot.items() if key != "api_key"}, "provider_id": "router:pdf2md-enhanced"}
    source = {"url": "https://docs.bigmodel.cn/cn/guide/capabilities/thinking", "document": "glm-5.3 thinking enabled"}
    service._call = AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None), finish_reason="length")]))
    result = await service.extract_sources(SimpleNamespace(tenant_id="7", token="token"), current, [source])
    assert result == {"reason_code": "model_output_truncated"}


@pytest.mark.anyio
async def test_extraction_prompt_is_bounded_across_sources():
    service, _, _ = make_service()
    snapshot = await service.snapshot("pdf2md-enhanced", "7")
    current = {**{key: value for key, value in snapshot.items() if key != "api_key"}, "provider_id": "router:pdf2md-enhanced"}
    sources = [{"url": f"https://docs.bigmodel.cn/cn/guide/source-{i}",
                "document": "x" * 5000 + " glm-5.3 " + "y" * 5000 + " reasoning_effort " + "z" * 5000}
               for i in range(5)]
    service._call = AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"claims":[]}'))]))
    assert await service.extract_sources(SimpleNamespace(tenant_id="7", token="token"), current, sources) == []
    messages = service._call.await_args.args[1]
    assert len(messages[1]["content"]) < 20000
    assert all(source["url"] in messages[1]["content"] for source in sources)


@pytest.mark.anyio
@pytest.mark.parametrize("supplied_relation,expect_repair", [(None, True), ({"url": "bad", "quote": "wrong"}, False)])
async def test_only_missing_model_provided_family_reference_is_completed(supplied_relation, expect_repair):
    service, provider, _ = make_service()
    provider.model = "glm-4.6v-flashx"
    snapshot = await service.snapshot("pdf2md-enhanced", "7")
    current = {**{key: value for key, value in snapshot.items() if key != "api_key"}, "provider_id": "router:pdf2md-enhanced"}
    fact = "GLM-4.6V thinking.type enabled"
    relation = "GLM-4.6V/GLM-4.6V-Flash/GLM-4.6V-FlashX series"
    sources = [{"url": "https://docs.bigmodel.cn/cn/guide/capabilities/thinking", "document": fact},
               {"url": "https://raw.githubusercontent.com/zai-org/GLM-V/main/skills/glmv-caption/scripts/glmv_caption.py", "document": relation}]
    claim = {"dimension": "thinking", "option": "enabled", "support": "supported", "scope": "series", "series": "GLM-4.6V",
             "parameters": {"thinking": {"type": "enabled"}}, "evidence": {"url": sources[0]["url"], "quote": fact}, "relation_evidence": supplied_relation}
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"claims": [claim]})))])
    service._call = AsyncMock(return_value=response)
    result = await service.extract_sources(SimpleNamespace(tenant_id="7", token="token"), current, sources)
    if expect_repair:
        assert result[0]["relation_evidence"]["quote"] == relation
    else:
        assert result[0]["relation_evidence"] == supplied_relation


@pytest.mark.anyio
async def test_existing_switch_does_not_skip_missing_effort():
    service, provider, _ = make_service()
    snapshot = await service.snapshot("pdf2md-enhanced", "7")
    current = {**{key: value for key, value in snapshot.items() if key != "api_key"}, "provider_id": "router:pdf2md-enhanced"}
    text = "glm-5.3 thinking.type enabled; glm-5.3 reasoning_effort high"
    source = {"url": "https://docs.bigmodel.cn/cn/guide/capabilities/thinking", "document": text}
    switch = {"dimension": "thinking", "option": "enabled", "support": "supported", "scope": "exact", "series": None,
              "parameters": {"thinking": {"type": "enabled"}}, "evidence": {"url": source["url"], "quote": "glm-5.3 thinking.type enabled"}, "relation_evidence": None}
    effort = {"dimension": "reasoning_effort", "option": "high", "support": "supported", "parameters": {"reasoning_effort": "high"},
              "evidence": {"url": source["url"], "quote": "glm-5.3 reasoning_effort high"}}
    def response(value):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(value)))])
    service._call = AsyncMock(side_effect=[response({"claims": [switch]}), response({
        "support": "supported", "parameters": effort["parameters"], "evidence": effort["evidence"]})])
    claims = await service.extract_sources(SimpleNamespace(tenant_id="7", token="token"), current, [source])
    from src.llm.thinking_evidence import validate_claims
    accepted, _ = validate_claims(provider.model, {source["url"]: text}, claims)
    assert set(accepted) == {("thinking", "enabled"), ("reasoning_effort", "high")}
    assert service._call.await_count == 2


@pytest.mark.anyio
async def test_unverified_first_claim_can_trigger_but_not_authorize_high_followup():
    service, provider, _ = make_service()
    snapshot = await service.snapshot("pdf2md-enhanced", "7")
    current = {**{key: value for key, value in snapshot.items() if key != "api_key"}, "provider_id": "router:pdf2md-enhanced"}
    text = "glm-5.3 reasoning_effort high"
    source = {"url": "https://docs.bigmodel.cn/cn/guide/capabilities/thinking", "document": text}
    def response(value):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(value)))])
    second = {"support": "supported", "parameters": {"reasoning_effort": "high"},
              "evidence": {"url": source["url"], "quote": text}}
    service._call = AsyncMock(side_effect=[response({"claims": [{}]}), response(second)])
    claims = await service.extract_sources(SimpleNamespace(tenant_id="7", token="token"), current, [source])
    from src.llm.thinking_evidence import validate_claims
    accepted, _ = validate_claims(provider.model, {source["url"]: text}, claims)
    assert set(accepted) == {("reasoning_effort", "high")}
    assert service._call.await_count == 2
