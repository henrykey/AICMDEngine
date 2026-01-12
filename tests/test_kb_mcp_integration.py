"""
Integration test for KBMCP in MCP Registry

Tests that KBMCP is properly registered and can be discovered/executed
through the MCP Registry system.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.mcp.registry import MCPRegistry
from src.mcp_servers.kb_mcp import KBMCP


class TestKBMCPIntegration:
    """Integration tests for KBMCP with MCP Registry"""

    @pytest.mark.asyncio
    async def test_kb_mcp_registration(self):
        """RED: Test KBMCP can be registered in MCP registry"""
        registry = MCPRegistry()

        with patch('src.mcp_servers.kb_mcp.KBClient'):
            kb_mcp = KBMCP(
                kb_base_url="http://localhost:8001",
                kb_api_key="test-key"
            )

            registry.register_mcp(kb_mcp)

            # Verify registration
            assert registry.has_mcp("kb_mcp")
            assert registry.get_mcp("kb_mcp") == kb_mcp

    @pytest.mark.asyncio
    async def test_kb_mcp_discovery(self):
        """RED: Test KBMCP tools can be discovered via registry"""
        registry = MCPRegistry()

        with patch('src.mcp_servers.kb_mcp.KBClient'):
            kb_mcp = KBMCP(
                kb_base_url="http://localhost:8001",
                kb_api_key="test-key"
            )
            registry.register_mcp(kb_mcp)

            # Get all MCPs
            all_mcps = registry.get_all_mcps()
            assert len(all_mcps) >= 1

            # Find KB MCP
            kb_mcp_found = None
            for mcp in all_mcps:
                if mcp.name == "kb_mcp":
                    kb_mcp_found = mcp
                    break

            assert kb_mcp_found is not None
            assert kb_mcp_found.name == "kb_mcp"
            assert kb_mcp_found.version == "1.0.0"

    @pytest.mark.asyncio
    async def test_kb_mcp_tool_execution_via_registry(self):
        """RED: Test KB search tool can be executed via registry"""
        registry = MCPRegistry()

        with patch('src.mcp_servers.kb_mcp.KBClient') as mock_kb_client_class:
            mock_kb_client = AsyncMock()
            mock_kb_client.kb_search = AsyncMock(return_value=[
                {"id": "doc1", "title": "Test Document"}
            ])
            mock_kb_client_class.return_value = mock_kb_client

            kb_mcp = KBMCP(
                kb_base_url="http://localhost:8001",
                kb_api_key="test-key"
            )
            registry.register_mcp(kb_mcp)

            # Execute tool via registry
            result = await kb_mcp.execute_tool(
                tool_name="kb_search",
                params={"query": "test"},
                tenant_id="test_tenant"
            )

            assert "results" in result
            assert len(result["results"]) > 0
            assert result["results"][0]["title"] == "Test Document"

    @pytest.mark.asyncio
    async def test_multiple_mcps_in_registry(self):
        """RED: Test multiple MCPs can coexist in registry"""
        from src.mcp_servers.test_mcp import TestMCPServer

        registry = MCPRegistry()

        # Register both test and KB MCPs
        test_mcp = TestMCPServer()

        with patch('src.mcp_servers.kb_mcp.KBClient'):
            kb_mcp = KBMCP(
                kb_base_url="http://localhost:8001",
                kb_api_key="test-key"
            )

            registry.register_mcp(test_mcp)
            registry.register_mcp(kb_mcp)

            # Verify both are registered
            assert registry.has_mcp("test")  # TestMCPServer uses "test" as name
            assert registry.has_mcp("kb_mcp")
            assert len(registry.get_all_mcps()) == 2

    @pytest.mark.asyncio
    async def test_kb_mcp_semantic_search_via_registry(self):
        """RED: Test KB semantic search tool via registry"""
        registry = MCPRegistry()

        with patch('src.mcp_servers.kb_mcp.KBClient') as mock_kb_client_class:
            mock_kb_client = AsyncMock()
            mock_kb_client.kb_semantic_search = AsyncMock(return_value=[
                {"id": "doc2", "similarity_score": 0.95}
            ])
            mock_kb_client_class.return_value = mock_kb_client

            kb_mcp = KBMCP(
                kb_base_url="http://localhost:8001",
                kb_api_key="test-key"
            )
            registry.register_mcp(kb_mcp)

            result = await kb_mcp.execute_tool(
                tool_name="kb_semantic_search",
                params={"query": "approval process"},
                tenant_id="test_tenant"
            )

            assert "results" in result
            assert result["count"] == 1
            assert result["results"][0]["similarity_score"] >= 0.7
