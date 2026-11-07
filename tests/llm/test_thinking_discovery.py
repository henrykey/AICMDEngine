from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import httpx

from src.llm.thinking_discovery import discover_thinking, discover_from_sources
from src.llm.thinking_probe_client import ThinkingProbeClient, ThinkingSourceExtractor
from src.llm.thinking_capability_store import ThinkingCapabilityStore
from src.mcp_servers.model_capabilities_mcp import get_thinking_capabilities, resolve_thinking_parameters


@pytest.fixture
def anyio_backend():
    return "asyncio"


def setup():
    context = SimpleNamespace(tenant_id="7", token="user-token")
    current = {"provider_id": "p", "model": "model-test", "base_url": "https://api.deepseek.com/v1", "provider_fingerprint": "fp"}
    client = SimpleNamespace(context=AsyncMock(return_value=current), probe=AsyncMock(return_value={"status": "accepted"}))
    store = SimpleNamespace(save=AsyncMock(return_value=True), begin=AsyncMock())
    excerpt = "model-test supports reasoning_effort low"
    extractor = SimpleNamespace(extract=AsyncMock(return_value={"low": {"parameters": {"reasoning_effort": "low"}, "evidence": excerpt}}))
    source = AsyncMock(return_value={"url": "https://api-docs.deepseek.com/guides/thinking_mode/", "document": excerpt})
    return context, current, client, store, extractor, source


@pytest.mark.anyio
async def test_saves_only_after_probe_and_current_fingerprint_rechecked():
    context, current, client, store, extractor, source = setup()
    result = await discover_thinking("p", context, client, store, extractor, source)
    assert result["status"] == "http_accepted"
    assert client.context.await_count == 2
    store.save.assert_awaited_once()
    assert store.begin.await_args.args[:3] == ("7", "p", "fp")
    assert store.save.await_args.args[:3] == ("7", "p", "fp")
    assert store.save.await_args.args[4]["source"] == source.return_value["url"]


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["source", "candidate", "missing_value", "negative", "probe", "changed", "identity"])
async def test_failure_never_persists(failure):
    context, current, client, store, extractor, source = setup()
    if failure == "source": source.return_value = None
    if failure == "candidate": extractor.extract.return_value = {"high": {"model": "other"}}
    if failure == "missing_value": extractor.extract.return_value = {"high": {"parameters": {"reasoning_effort": "high"}, "evidence": source.return_value["document"]}}
    if failure == "negative":
        excerpt = "model-test does not support reasoning_effort low"
        source.return_value["document"] = excerpt
        extractor.extract.return_value = {"low": {"parameters": {"reasoning_effort": "low"}, "evidence": excerpt}}
    if failure == "probe": client.probe.return_value = {"status": "indeterminate"}
    if failure == "changed": client.context.side_effect = [current, {**current, "provider_fingerprint": "other"}]
    if failure == "identity": context = None
    result = await discover_thinking("p", context, client, store, extractor, source)
    assert result["status"] == "indeterminate" and result["modes"] == ["default"]
    store.save.assert_not_awaited()


@pytest.mark.anyio
async def test_mocked_membership_contract_discovery_and_tenant_scoped_read():
    context, current, _, _, _, source = setup()
    class Collection:
        document = None
        async def replace_one(self, query, document, upsert):
            matched = bool(self.document and all(self.document.get(k) == v for k, v in query.items()))
            if matched or upsert:
                self.document = {"_id": query["_id"], **document}
            return SimpleNamespace(matched_count=int(matched))
        async def find_one(self, query):
            return self.document if self.document and all(self.document.get(k) == v for k, v in query.items()) else None
    def handle(request):
        if request.url.path.endswith("thinking-context"):
            return httpx.Response(200, json=current)
        if request.url.path.endswith("thinking-source-extractions"):
            return httpx.Response(200, json={"provider_fingerprint": "fp", "status": "candidates", "claims": [{
                "dimension": "reasoning_effort", "option": "low", "support": "supported", "scope": "exact",
                "series": None, "parameters": {"reasoning_effort": "low"}, "relation_evidence": None,
                "evidence": {"url": source.return_value["url"], "quote": source.return_value["document"]}}]})
        return httpx.Response(200, json={"status": "accepted", "provider_fingerprint": "fp",
                                         "probed_at": "2026-11-07T00:00:00Z", "reason_code": "http_2xx"})
    client = ThinkingProbeClient("https://membership.example", httpx.MockTransport(handle))
    store = ThinkingCapabilityStore(Collection())
    async def sources(*_):
        return [{**source.return_value, "sha256": "a" * 64}]
    result = await discover_from_sources("p", context, client, store, ThinkingSourceExtractor(client), sources)
    assert result["status"] == "http_accepted"
    read = await get_thinking_capabilities("p", context, client, store)
    assert read["status"] == "http_accepted" and read["modes"] == ["default", "low"]
    assert (await resolve_thinking_parameters("p", "low", current["model"], current["base_url"],
                                              context, client, store))["mode"] == "low"
    other = SimpleNamespace(tenant_id="8", token="other-token")
    assert (await get_thinking_capabilities("p", other, client, store))["modes"] == ["default"]
    assert (await resolve_thinking_parameters("p", "low", current["model"], current["base_url"],
                                              other, client, store))["mode"] == "default"
    for model, base_url in (("other-model", current["base_url"]), (current["model"], "https://other.example/v1")):
        resolution = await resolve_thinking_parameters("p", "low", model, base_url, context, client, store)
        assert resolution["mode"] == "default" and resolution["reason_code"] == "runtime_provider_mismatch"
    current["provider_fingerprint"] = "new-fingerprint"
    assert (await resolve_thinking_parameters("p", "low", current["model"], current["base_url"],
                                              context, client, store))["mode"] == "default"
