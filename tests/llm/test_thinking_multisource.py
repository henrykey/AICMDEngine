from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.llm.thinking_discovery import discover_from_sources
from src.mcp_servers.model_capabilities_mcp import get_thinking_capabilities


@pytest.fixture
def anyio_backend():
    return "asyncio"


def sample():
    model = "glm-4.6v-flashx"
    family_quote = "GLM-4.6V series includes GLM-4.6V-FlashX"
    fact_quote = "GLM-4.6V thinking type enabled supported"
    sources = [{"url": "https://docs.bigmodel.cn/cn/guide/capabilities/thinking", "document": fact_quote, "sha256": "a" * 64},
               {"url": "https://raw.githubusercontent.com/zai-org/GLM-V/main/skills/glmv-prompt-gen/scripts/prompt_gen.py", "document": family_quote, "sha256": "b" * 64}]
    claim = {"dimension": "thinking", "option": "enabled", "support": "supported", "scope": "series", "series": "GLM-4.6V",
        "parameters": {"thinking": {"type": "enabled"}}, "evidence": {"url": sources[0]["url"], "quote": fact_quote},
        "relation_evidence": {"url": sources[1]["url"], "quote": family_quote}}
    context = SimpleNamespace(tenant_id="33", token="token")
    current = {"provider_id": "p", "model": model, "base_url": "https://open.bigmodel.cn/api/paas/v4", "provider_fingerprint": "fp"}
    client = SimpleNamespace(context=AsyncMock(return_value=current), probe=AsyncMock(return_value={"status": "accepted", "probed_at": "now", "reason_code": "http_2xx"}))
    store = SimpleNamespace(begin=AsyncMock(), save=AsyncMock(return_value=True))
    return context, client, store, sources, claim


@pytest.mark.anyio
async def test_switch_is_separate_from_unknown_effort_and_sources_are_retained():
    context, client, store, sources, claim = sample()
    result = await discover_from_sources("p", context, client, store,
        SimpleNamespace(extract_sources=AsyncMock(return_value=[claim])), AsyncMock(return_value=sources))
    assert result["modes"] == ["default", "enabled"]
    assert result["capabilities"]["thinking"]["enabled"]["status"] == "http_accepted"
    assert result["capabilities"]["reasoning_effort"]["high"]["status"] == "unknown"
    record = store.save.await_args.args[4]
    assert (record["expires_at"] - record["observed_at"]).total_seconds() == 3600
    assert record["sources"] == [{"url": s["url"], "sha256": s["sha256"]} for s in sources]
    assert record["capabilities"]["thinking"]["enabled"]["evidence"][0]["scope"] == "series"
    assert record["capabilities"]["thinking"]["enabled"]["evidence"][0]["evidence_level"] == "family_inference"
    assert store.save.await_args.args[0] == "33"
    store.read = AsyncMock(return_value=record)
    read = await get_thinking_capabilities("p", context, client, store)
    assert read["status"] == "http_accepted" and read["modes"] == ["default", "enabled"]
    assert read["capabilities"]["reasoning_effort"]["high"]["status"] == "unknown"


@pytest.mark.anyio
async def test_source_conflict_defaults_without_probe():
    context, client, store, sources, claim = sample()
    negative = "GLM-4.6V thinking enabled not supported"
    sources[0]["document"] += " " + negative
    conflicting = {**claim, "support": "unsupported", "parameters": {},
                   "evidence": {"url": sources[0]["url"], "quote": negative}}
    result = await discover_from_sources("p", context, client, store,
        SimpleNamespace(extract_sources=AsyncMock(return_value=[claim, conflicting])), AsyncMock(return_value=sources))
    assert result["status"] == "indeterminate" and result["modes"] == ["default"]
    assert result["capabilities"]["thinking"]["enabled"]["status"] == "conflict"
    client.probe.assert_not_awaited()
    store.read = AsyncMock(return_value=store.save.await_args.args[4])
    read = await get_thinking_capabilities("p", context, client, store)
    assert read["capabilities"]["thinking"]["enabled"]["status"] == "conflict"


@pytest.mark.anyio
async def test_probe_failure_is_indeterminate_not_unsupported():
    context, client, store, sources, claim = sample()
    client.probe.return_value = None
    result = await discover_from_sources("p", context, client, store,
        SimpleNamespace(extract_sources=AsyncMock(return_value=[claim])), AsyncMock(return_value=sources))
    assert result["capabilities"]["thinking"]["enabled"]["status"] == "indeterminate"
    assert result["modes"] == ["default"]


@pytest.mark.anyio
async def test_explicit_documented_unsupported_does_not_imply_other_options():
    context, client, store, sources, claim = sample()
    quote = "GLM-4.6V thinking disabled is not supported"
    sources[0]["document"] = quote
    claim.update(option="disabled", support="unsupported", parameters={},
                 evidence={"url": sources[0]["url"], "quote": quote})
    result = await discover_from_sources("p", context, client, store,
        SimpleNamespace(extract_sources=AsyncMock(return_value=[claim])), AsyncMock(return_value=sources))
    assert result["capabilities"]["thinking"]["disabled"]["status"] == "documented_unsupported"
    assert result["capabilities"]["thinking"]["enabled"]["status"] == "unknown"
    assert result["capabilities"]["reasoning_effort"]["high"]["status"] == "unknown"
    client.probe.assert_not_awaited()
