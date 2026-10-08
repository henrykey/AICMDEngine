"""Image task identity must agree with the Router's authenticated tenant."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from src.mcp.protocol_handler import MCPMessage, MCPProtocolHandler


@pytest.mark.parametrize('tenant,identity', [
    ('6', {'tenant_id': '7'}), (None, {'tenant_id': '6'}),
    ('6', {}), ('6', '6'), ('6', None),
])
def test_image_identity_rejected_before_provider_injection_or_execution(tenant, identity):
    handler = MCPProtocolHandler()
    handler._inject_external_model_configs = AsyncMock()
    registry = SimpleNamespace(execute_command=AsyncMock())
    message = MCPMessage(method='tools/call', params={
        'name': 'pdf2md-enhanced.start_task', 'arguments': {'source_identity': identity}})
    with pytest.raises(ValueError, match='source_identity_tenant_mismatch'):
        asyncio.run(handler._handle_tools_call(message, {
            'registry': registry, 'client_info': {'tenant_id': tenant}}))
    handler._inject_external_model_configs.assert_not_awaited()
    registry.execute_command.assert_not_awaited()


def test_image_identity_uses_authenticated_tenant():
    handler = MCPProtocolHandler()
    args = {'source_identity': {'tenant_id': '6', 'doc_id': 'document'}}
    handler._inject_external_model_configs = AsyncMock(return_value=args)
    registry = SimpleNamespace(execute_command=AsyncMock(return_value=SimpleNamespace(content='ok', is_error=False)))
    message = MCPMessage(method='tools/call', params={
        'name': 'pdf2md-enhanced.start_task', 'arguments': args})
    result = asyncio.run(handler._handle_tools_call(message, {
        'registry': registry, 'client_info': {'tenant_id': '6'}}))
    assert not result['isError']
    assert registry.execute_command.await_args.kwargs['source_identity'] == args['source_identity']
