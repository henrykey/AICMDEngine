from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.anyio

@pytest.fixture(autouse=True)
def block_real_http(monkeypatch):
    import httpx
    monkeypatch.setattr(httpx.AsyncClient, "request", AsyncMock(side_effect=AssertionError("Offline tests prohibit HTTP")))


@pytest.fixture
def anyio_backend():
    return "asyncio"

from src.mcp.protocol_handler import MCPProtocolHandler
from src.mcp_servers.membership_mcp import MembershipMCPServer


@pytest.mark.parametrize('arguments', [
    {'auth_token': 'other'}, {'auth_token': None}, {'auth_token': ''},
    {'tenant_id': 7}, {'tenant_id': None}, {'tenant_id': 0},
    {'_tenant_id': 7, 'system_service_token': 'audit'},
])
async def test_protocol_rejects_conflicting_identity(arguments):
    registry = SimpleNamespace(execute_command=AsyncMock(return_value=SimpleNamespace(content="ok")), get_mcp=lambda _: None)
    response = await MCPProtocolHandler().handle_message(
        {'id': 1, 'method': 'tools/call', 'params': {'name': 'membership.list_members', 'arguments': arguments}},
        {'registry': registry, 'jwt_token': 'session', 'client_info': {'tenant_id': 6}},
    )
    assert 'error' in response
    registry.execute_command.assert_not_awaited()


@pytest.mark.parametrize('token,tenant', [(None, 6), ('', 6), ('session', None)])
async def test_protocol_requires_session_identity(token, tenant):
    registry = SimpleNamespace(execute_command=AsyncMock(return_value=SimpleNamespace(content="ok")), get_mcp=lambda _: None)
    response = await MCPProtocolHandler().handle_message(
        {'id': 1, 'method': 'tools/call', 'params': {'name': 'membership.list_members'}},
        {'registry': registry, 'jwt_token': token, 'client_info': {'tenant_id': tenant}},
    )
    assert 'error' in response
    registry.execute_command.assert_not_awaited()


@pytest.mark.parametrize('arguments', [{'auth_token': None}, {'auth_token': ''}, {'tenant_id': None}, {'tenant_id': 0}])
async def test_membership_explicit_empty_identity_never_falls_back(arguments):
    server = MembershipMCPServer(tenant_id=9, auth_token='configured')
    server.http_client.execute = AsyncMock(return_value={'members': []})
    result = await server.list_members(**arguments)
    assert result.is_error
    server.http_client.execute.assert_not_awaited()
    await server.http_client.client.aclose()


async def test_matching_identity_and_audit_metadata_stay_separate(monkeypatch):
    from src.mcp.auth_jwt import MCPJWTAuth
    validate = AsyncMock(return_value={'tenant_id': 6, 'sub': 'system-service-t6'})
    monkeypatch.setattr(MCPJWTAuth, 'validate_token', validate)
    membership = SimpleNamespace(_audit_system_tokens={})
    registry = SimpleNamespace(execute_command=AsyncMock(return_value=SimpleNamespace(content='ok')), get_mcp=lambda _: membership)
    arguments = {'auth_token': 'session', 'tenant_id': '6', '_tenant_id': 6, 'system_service_token': 'audit'}
    response = await MCPProtocolHandler().handle_message(
        {'id': 1, 'method': 'tools/call', 'params': {'name': 'membership.list_members', 'arguments': arguments}},
        {'registry': registry, 'jwt_token': 'session', 'client_info': {'tenant_id': 6}},
    )
    assert 'result' in response
    assert registry.execute_command.call_args.kwargs == {'mcp_name': 'membership', 'tool_name': 'list_members', 'auth_token': 'session', 'tenant_id': 6}
    assert membership._audit_system_tokens == {6: 'audit'}
    assert arguments['system_service_token'] == 'audit'
    validate.assert_awaited_once_with('audit')


@pytest.mark.parametrize('claims', [{'tenant_id': 7, 'sub': 'system-service-t7'}, {'tenant_id': 6, 'sub': 'user'}, {}])
async def test_bad_audit_identity_cannot_poison_cache(monkeypatch, claims):
    from src.mcp.auth_jwt import MCPJWTAuth
    monkeypatch.setattr(MCPJWTAuth, 'validate_token', AsyncMock(return_value=claims))
    membership = SimpleNamespace(_audit_system_tokens={})
    registry = SimpleNamespace(get_mcp=lambda _: membership)
    with pytest.raises(ValueError):
        await MCPProtocolHandler().bind_authenticated_arguments(
            {'system_service_token': 'audit'},
            {'registry': registry, 'jwt_token': 'session', 'client_info': {'tenant_id': 6}},
            'membership', 'list_members',
        )
    assert not membership._audit_system_tokens


async def test_batch_audit_cannot_use_another_tenants_cached_identity():
    with pytest.raises(ValueError):
        await MCPProtocolHandler().bind_authenticated_arguments(
            {'events': [{'tenant_id': 7}]},
            {'jwt_token': 'session', 'client_info': {'tenant_id': 6}},
            'membership', 'submit_audit_events_batch',
        )


async def test_explicit_constructor_identity_remains_available():
    server = MembershipMCPServer(tenant_id=6, auth_token='service')
    server.http_client.execute = AsyncMock(return_value={'members': []})
    result = await server.list_members()
    assert not result.is_error
    assert server.http_client.execute.call_args.kwargs['auth_token'] == 'service'
    assert server.http_client.execute.call_args.kwargs['tenant_id'] == 6
    await server.http_client.client.aclose()


async def test_missing_tenant_is_not_inferred_from_configuration():
    server = MembershipMCPServer(auth_token='service')
    server.http_client.execute = AsyncMock()
    result = await server.list_members()
    assert result.is_error
    server.http_client.execute.assert_not_awaited()
    await server.http_client.client.aclose()


@pytest.mark.parametrize('header,body,status', [('', {}, 401), ('Bearer session', {'auth_token': 'other'}, 403), ('Bearer session', {'tenant_id': None}, 403)])
async def test_rest_rejects_untrusted_identity(monkeypatch, header, body, status):
    from src.routers import mcp
    from fastapi import HTTPException
    monkeypatch.setattr(mcp.MCPJWTAuth, 'validate_token', AsyncMock(return_value={'tenant_id': 6}))
    registry = SimpleNamespace(execute_command=AsyncMock())
    request = SimpleNamespace(headers={'authorization': header}, app=SimpleNamespace(mcp_registry=registry), json=AsyncMock(return_value=body))
    with pytest.raises(HTTPException) as error:
        await mcp.execute_mcp_tool('membership', 'list_members', request)
    assert error.value.status_code == status
    registry.execute_command.assert_not_awaited()


async def test_audit_validation_outage_stops_execution_without_replacing_cache(monkeypatch):
    from fastapi import HTTPException
    from src.mcp.auth_jwt import MCPJWTAuth
    monkeypatch.setattr(MCPJWTAuth, 'validate_token', AsyncMock(side_effect=HTTPException(503, 'unavailable')))
    membership = SimpleNamespace(_audit_system_tokens={6: 'old-audit'})
    registry = SimpleNamespace(execute_command=AsyncMock(), get_mcp=lambda _: membership)
    response = await MCPProtocolHandler().handle_message(
        {'id': 1, 'method': 'tools/call', 'params': {'name': 'membership.list_members', 'arguments': {'system_service_token': 'new-audit', '_tenant_id': 6}}},
        {'registry': registry, 'jwt_token': 'session', 'client_info': {'tenant_id': 6}},
    )
    assert 'error' in response
    assert membership._audit_system_tokens == {6: 'old-audit'}
    registry.execute_command.assert_not_awaited()


async def test_plain_call_does_not_validate_auxiliary_token(monkeypatch):
    from src.mcp.auth_jwt import MCPJWTAuth
    validate = AsyncMock(side_effect=AssertionError('unexpected network authentication'))
    monkeypatch.setattr(MCPJWTAuth, 'validate_token', validate)
    result = await MCPProtocolHandler().bind_authenticated_arguments(
        {}, {'jwt_token': 'session', 'client_info': {'tenant_id': 6}}, 'membership', 'list_members',
    )
    assert result == {'auth_token': 'session', 'tenant_id': 6}
    validate.assert_not_awaited()


async def test_internal_audit_retains_explicit_service_identity():
    server = MembershipMCPServer(tenant_id=6, auth_token='configured')
    server._audit_system_tokens[6] = 'audit-service'
    server.http_client._is_token_expired = lambda _: False
    server.http_client.execute = AsyncMock(return_value={})
    result = await server.submit_audit_event('ACCESS', 'TEST', 6, {'memberId': 2}, auth_token='session')
    assert not result.is_error
    assert server.http_client.execute.call_args.kwargs['auth_token'] == 'audit-service'
    assert server.http_client.execute.call_args.kwargs['tenant_id'] == 6
    await server.http_client.client.aclose()


@pytest.mark.parametrize('query,header,expected', [('query-token', 'Bearer header-token', 'query-token'), (None, 'Bearer header-token', 'header-token')])
async def test_websocket_authentication_and_execution_use_same_token(monkeypatch, query, header, expected):
    import asyncio
    from fastapi import WebSocketDisconnect
    from src.routers import mcp_ws
    validated = AsyncMock(return_value={'sub': 'user', 'tenant_id': 6})
    monkeypatch.setattr(mcp_ws.MCPJWTAuth, 'validate_token', validated)
    captured = {}
    processed = asyncio.Event()

    async def handle(message, context):
        captured.update(context)
        processed.set()
        return None

    monkeypatch.setattr(mcp_ws.protocol_handler, 'handle_message', handle)
    monkeypatch.setattr(mcp_ws.connection_manager, 'connect', AsyncMock())
    monkeypatch.setattr(mcp_ws.connection_manager, 'disconnect', lambda *args: None)
    calls = 0

    async def receive():
        nonlocal calls
        calls += 1
        if calls == 1:
            return '{"id":1,"method":"tools/list"}'
        await processed.wait()
        raise WebSocketDisconnect()

    websocket = SimpleNamespace(query_params={'token': query}, headers={'authorization': header}, app=SimpleNamespace(), receive_text=receive, close=AsyncMock())
    await mcp_ws.mcp_websocket_endpoint(websocket, registry=SimpleNamespace())
    validated.assert_awaited_once_with(expected)
    assert captured['jwt_token'] == expected
    assert captured['client_info']['tenant_id'] == 6


async def test_dispatch_logs_do_not_expose_credentials(caplog):
    import logging
    from src.mcp.registry import MCPRegistry
    server = MembershipMCPServer()
    server.http_client.execute = AsyncMock(return_value={'members': []})
    registry = MCPRegistry()
    registry.register_mcp(server)
    with caplog.at_level(logging.DEBUG):
        result = await registry.execute_command('membership', 'list_members', auth_token='sensitive-credential-123456789', tenant_id=6)
    assert not result.is_error
    assert 'sensitive-credential' not in caplog.text
    await server.http_client.client.aclose()


@pytest.mark.parametrize('body', [{'service_token': 'business-service'}, {'scope': {'tenantId': 6}}])
async def test_basin_graph_body_token_is_not_router_authentication(body):
    from src.routers import mcp
    from fastapi import HTTPException
    registry = SimpleNamespace(execute_command=AsyncMock())
    request = SimpleNamespace(headers={}, app=SimpleNamespace(mcp_registry=registry), json=AsyncMock(return_value=body))
    with pytest.raises(HTTPException) as error:
        await mcp.execute_mcp_tool('k-graph-mcp', 'query_basin_graph', request)
    assert error.value.status_code == 401
    registry.execute_command.assert_not_awaited()
