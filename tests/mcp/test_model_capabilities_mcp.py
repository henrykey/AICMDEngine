import json
import asyncio
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.mcp.protocol_handler import MCPMessage, MCPProtocolHandler
from src.mcp.registry import MCPRegistry
from src.mcp_servers.model_capabilities_mcp import CapabilityExecutionContext, ModelCapabilitiesMCPServer, get_thinking_capabilities
from src.routers.mcp import execute_mcp_tool


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_unavailable_probe_returns_only_default():
    registry = MCPRegistry()
    registry.register_mcp(ModelCapabilitiesMCPServer())
    result = await registry.execute_command("model-capabilities", "get_thinking_capabilities", provider_id="provider-1")
    assert not result.is_error
    assert json.loads(result.content) == await get_thinking_capabilities("provider-1") == {
        "provider_id": "provider-1", "status": "indeterminate",
        "reason_code": "authenticated_context_missing", "modes": ["default"], "parameters": {},
    }


@pytest.mark.anyio
async def test_invalid_provider_is_rejected():
    with pytest.raises(ValueError):
        await get_thinking_capabilities(" ")


@pytest.mark.anyio
async def test_discovery_tool_defaults_when_extractor_unavailable():
    registry = MCPRegistry()
    registry.register_mcp(ModelCapabilitiesMCPServer())
    result = await registry.execute_command("model-capabilities", "discover_thinking_capabilities", provider_id="p")
    assert json.loads(result.content) == {
        "status": "indeterminate", "reason_code": "discovery_unavailable", "modes": ["default"]}


@pytest.mark.anyio
async def test_tools_call_with_authenticated_context_filters_extra_arguments():
    registry = MCPRegistry()
    server = ModelCapabilitiesMCPServer()
    server.execute_with_context = AsyncMock(wraps=server.execute_with_context)
    registry.register_mcp(server)
    message = MCPMessage(method="tools/call", params={
        "name": "model-capabilities.get_thinking_capabilities",
        "arguments": {"provider_id": "p", "tenant_id": 1, "auth_token": "session-token", "extra": "secret"},
    })
    result = await MCPProtocolHandler()._handle_tools_call(message, {
        "registry": registry, "jwt_token": "session-token", "client_info": {"tenant_id": 1},
    })
    assert result["isError"] is False
    assert json.loads(result["content"][0]["text"]) == {
        "provider_id": "p", "status": "indeterminate", "reason_code": "tenant_probe_unavailable",
        "modes": ["default"], "parameters": {},
    }
    call = server.execute_with_context.await_args
    assert call.args == ("get_thinking_capabilities", CapabilityExecutionContext("1", "session-token"))
    assert call.kwargs == {"provider_id": "p"}
    assert "session-token" not in json.dumps(result)
    assert "secret" not in json.dumps(result)


@pytest.mark.anyio
@pytest.mark.parametrize("token,tenant,arguments,error", [
    (None, 1, {}, "Authenticated token required"),
    ("session-token", None, {}, "Authenticated tenant required"),
    ("session-token", 1, {"tenant_id": 2}, "tenant_id conflicts"),
    ("session-token", 1, {"auth_token": "other-token"}, "auth_token conflicts"),
    ("session-token", 1, {"execution_context": {"tenant_id": 2}}, "execution_context is reserved"),
])
async def test_tools_call_rejects_missing_or_conflicting_identity(token, tenant, arguments, error):
    registry = MCPRegistry()
    server = ModelCapabilitiesMCPServer()
    server.execute_with_context = AsyncMock(wraps=server.execute_with_context)
    registry.register_mcp(server)
    message = MCPMessage(method="tools/call", params={
        "name": "model-capabilities.get_thinking_capabilities",
        "arguments": {"provider_id": "p", **arguments},
    })
    with pytest.raises(ValueError, match=error):
        await MCPProtocolHandler()._handle_tools_call(message, {
            "registry": registry, "jwt_token": token, "client_info": {"tenant_id": tenant},
        })
    server.execute_with_context.assert_not_awaited()


@pytest.mark.anyio
async def test_rest_uses_authenticated_tenant_not_tool_arguments(monkeypatch):
    registry = MCPRegistry()
    server = ModelCapabilitiesMCPServer()
    server.execute_with_context = AsyncMock(wraps=server.execute_with_context)
    registry.register_mcp(server)
    validate = AsyncMock(return_value={"tenant_id": 7})
    monkeypatch.setattr("src.routers.mcp.MCPJWTAuth.validate_token", validate)

    async def body():
        return {"provider_id": "p"}

    request = SimpleNamespace(app=SimpleNamespace(mcp_registry=registry),
                              headers={"authorization": "Bearer token-7"}, json=body)
    result = await execute_mcp_tool("model-capabilities", "get_thinking_capabilities", request)
    assert json.loads(result["result"]["content"][0]["text"])["reason_code"] == "tenant_probe_unavailable"
    assert server.execute_with_context.await_args.args[1] == CapabilityExecutionContext("7", "token-7")
    validate.assert_awaited_once_with("token-7")

    for forged in ({"tenant_id": 8}, {"auth_token": "other-token"},
                   {"execution_context": {"tenant_id": 8}}):
        async def forged_body():
            return {"provider_id": "p", **forged}

        request.json = forged_body
        with pytest.raises(HTTPException) as error:
            await execute_mcp_tool("model-capabilities", "get_thinking_capabilities", request)
        assert error.value.status_code == 403
    assert server.execute_with_context.await_count == 1


@pytest.mark.anyio
async def test_concurrent_sessions_keep_tenants_separate():
    registry = MCPRegistry()
    server = ModelCapabilitiesMCPServer()
    server.execute_with_context = AsyncMock(wraps=server.execute_with_context)
    registry.register_mcp(server)
    message = MCPMessage(method="tools/call", params={
        "name": "model-capabilities.get_thinking_capabilities", "arguments": {"provider_id": "p"},
    })
    handler = MCPProtocolHandler()
    results = await asyncio.gather(*[
        handler._handle_tools_call(message, {"registry": registry, "jwt_token": f"token-{tenant}",
                                             "client_info": {"tenant_id": tenant}})
        for tenant in (1, 2)
    ])
    assert all(json.loads(result["content"][0]["text"])["status"] == "indeterminate" for result in results)
    assert {call.args[1] for call in server.execute_with_context.await_args_list} == {
        CapabilityExecutionContext("1", "token-1"), CapabilityExecutionContext("2", "token-2")}


@pytest.mark.anyio
async def test_read_requires_authorized_current_context_and_matching_record():
    client = SimpleNamespace(context=AsyncMock(return_value={"provider_id": "p", "model": "m",
        "base_url": "https://api.deepseek.com/v1", "provider_fingerprint": "fp"}))
    record = {"schema_version": 2, "status": "http_accepted", "model": "m", "base_url": "https://api.deepseek.com/v1", "modes": ["default", "low"],
              "parameters": {"low": {"reasoning_effort": "low"}},
              "sources": [{"url": "https://api-docs.deepseek.com/guides/thinking_mode/", "sha256": "a" * 64}],
              "capabilities": {"thinking": {"enabled": {"status": "unknown"}, "disabled": {"status": "unknown"}},
                  "reasoning_effort": {"low": {"status": "http_accepted", "evidence": [{"scope": "exact", "series": None, "evidence_level": "model_explicit",
                      "evidence": {"url": "https://api-docs.deepseek.com/guides/thinking_mode/", "quote": "m reasoning_effort low"},
                      "relation_evidence": None}]}, "high": {"status": "unknown"}, "max": {"status": "unknown"}}},
              "probes": {"low": {"status": "accepted", "probed_at": "2026-11-07T00:00:00Z"}},
              "evidence": {"low": "m reasoning_effort low"},
              "expires_at": datetime.now(timezone.utc) + timedelta(hours=1)}
    store = SimpleNamespace(read=AsyncMock(return_value=record))
    context = CapabilityExecutionContext("7", "token-7")
    result = await get_thinking_capabilities("p", context, client, store)
    assert result["status"] == "http_accepted"
    client.context.assert_awaited_once_with("p", "token-7")
    store.read.assert_awaited_once_with("7", "p", "fp")
    record["model"] = "other"
    assert (await get_thinking_capabilities("p", context, client, store))["reason_code"] == "invalid_capability_record"
    client.context.return_value = None
    assert (await get_thinking_capabilities("p", context, client, store))["modes"] == ["default"]
