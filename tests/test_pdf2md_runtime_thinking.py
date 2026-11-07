from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.mcp.protocol_handler import MCPProtocolHandler
from tests.test_pdf2md_enhanced_single_page_tools import DynamicVLMClient
from tests.test_mcp_model_config_injection import FakeProviderManager, FakeMongo
from tests.test_pdf2md_enhanced_table_query import query, request, single_page_tools


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("field", ["vlm_config", "vlm_defaults"])
async def test_callers_cannot_supply_router_reserved_thinking(field):
    with pytest.raises(ValueError, match="Reserved Router"):
        await MCPProtocolHandler().bind_authenticated_arguments(
            {field: {"_router_discovered_thinking": {"reasoning_effort": "high"}}},
            {"jwt_token": "token", "client_info": {"tenant_id": 7}}, "pdf2md-enhanced", "extract_page_tables")


@pytest.mark.anyio
async def test_explicit_vlm_config_does_not_use_runtime_discovery():
    runtime = SimpleNamespace(apply_table_query=AsyncMock())
    registry = SimpleNamespace(get_tool_info=lambda *args: {"inputSchema": {"properties": {"vlm_config": {}}}},
        get_mcp=lambda name: SimpleNamespace(runtime=runtime))
    explicit = {"model": "manual", "api_key": "own-key"}
    arguments = {"vlm_config": explicit, "query_enhancement": {"thinking_mode": "high"}}
    result = await MCPProtocolHandler()._inject_external_model_configs("pdf2md-enhanced", "extract_page_tables",
        arguments, {"registry": registry, "provider_manager": object(), "jwt_token": "token", "client_info": {"tenant_id": 7}})
    assert result["vlm_config"] is explicit
    runtime.apply_table_query.assert_not_awaited()


@pytest.mark.anyio
async def test_router_injection_passes_only_authenticated_tenant_and_discovered_parameters():
    params = {"reasoning_effort": "high"}
    async def apply(server, tool, args, config, identity):
        assert identity.tenant_id == "7" and identity.token == "token"
        return {**config, "_router_discovered_thinking": params}
    runtime = SimpleNamespace(apply_table_query=AsyncMock(side_effect=apply))
    registry = SimpleNamespace(get_tool_info=lambda *args: {"inputSchema": {"properties": {"vlm_config": {}}}},
        get_mcp=lambda name: SimpleNamespace(runtime=runtime) if name == "model-capabilities" else object())
    args = {"query_enhancement": {"thinking_mode": "high"}}
    result = await MCPProtocolHandler()._inject_external_model_configs("pdf2md-enhanced", "extract_page_tables", args,
        {"registry": registry, "provider_manager": FakeProviderManager(), "mongodb": FakeMongo(),
         "jwt_token": "token", "client_info": {"tenant_id": 7}})
    assert result["vlm_config"]["_router_discovered_thinking"] == params
    assert DynamicVLMClient(result["vlm_config"]).thinking_parameters == params


def test_pdf2md_accepts_only_bounded_runtime_parameters():
    config = {"base_url": "https://example.com/v1", "model": "m", "api_key": "own-key"}
    client = DynamicVLMClient({**config, "_router_discovered_thinking": {"reasoning_effort": "high"}})
    assert client.thinking_parameters == {"reasoning_effort": "high"}
    client = DynamicVLMClient({**config, "_router_discovered_thinking": {"model": "other"}})
    assert client.thinking_parameters == {}


def test_discovered_parameter_is_reported_as_unverified_thinking():
    req = request()
    req.update(query_strategy="model_required", max_model_calls=1, thinking_mode="high")
    class Client:
        last_call_info = {}
        physical_requests = 1
        def explain_table_query(self, *args, **kwargs):
            return {}
    result = query.enhance_table(req, single_page_tools._html_table_to_grid, lambda config: Client(),
        {"base_url": "https://example.com/v1", "model": "m",
         "_router_discovered_thinking": {"reasoning_effort": "high"}}, "zh")
    assert result["query_enhancement"]["thinking"] == {
        "requested": "high", "actual": "unverified", "probe_status": "http_accepted"}
