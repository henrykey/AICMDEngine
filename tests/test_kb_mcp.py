import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.mcp_servers.kb_mcp import KBMCP, KBMCPError


class TestKBMCP:
    """Test Knowledge Base MCP Server"""

    @pytest.mark.asyncio
    async def test_kb_mcp_initialization(self):
        """RED: Test KBMCP initializes with KB client"""
        with patch('src.mcp_servers.kb_mcp.KBClient'):
            mcp = KBMCP(
                kb_base_url="http://localhost:8001",
                kb_api_key="test-key"
            )

            assert mcp.name == "kb_mcp"
            assert mcp.kb_client is not None

    @pytest.mark.asyncio
    async def test_kb_mcp_list_tools(self):
        """RED: Test KBMCP lists available KB tools"""
        with patch('src.mcp_servers.kb_mcp.KBClient'):
            mcp = KBMCP(
                kb_base_url="http://localhost:8001",
                kb_api_key="test-key"
            )

            tools = await mcp.list_tools(tenant_id="test_tenant")

            tool_names = [t["name"] for t in tools]
            assert "kb_search" in tool_names
            assert "kb_semantic_search" in tool_names
            assert "kb_rag_query" in tool_names

    @pytest.mark.asyncio
    async def test_kb_mcp_search_tool(self):
        """RED: Test KB search tool execution"""
        with patch('src.mcp_servers.kb_mcp.KBClient') as mock_kb_client_class:
            mock_kb_client = AsyncMock()
            mock_kb_client.kb_search = AsyncMock(return_value=[
                {"id": "doc1", "title": "Approval Workflow"}
            ])
            mock_kb_client_class.return_value = mock_kb_client

            mcp = KBMCP(
                kb_base_url="http://localhost:8001",
                kb_api_key="test-key"
            )

            result = await mcp.execute_tool(
                tool_name="kb_search",
                params={"query": "approval workflow"},
                tenant_id="test_tenant"
            )

            assert "results" in result
            assert len(result["results"]) > 0

    @pytest.mark.asyncio
    async def test_kb_mcp_semantic_search_tool(self):
        """RED: Test KB semantic search tool"""
        with patch('src.mcp_servers.kb_mcp.KBClient') as mock_kb_client_class:
            mock_kb_client = AsyncMock()
            mock_kb_client.kb_semantic_search = AsyncMock(return_value=[
                {"id": "doc2", "similarity_score": 0.87}
            ])
            mock_kb_client_class.return_value = mock_kb_client

            mcp = KBMCP(
                kb_base_url="http://localhost:8001",
                kb_api_key="test-key"
            )

            result = await mcp.execute_tool(
                tool_name="kb_semantic_search",
                params={"query": "How do approvals work?"},
                tenant_id="test_tenant"
            )

            assert "results" in result
            assert len(result["results"]) > 0

    @pytest.mark.asyncio
    async def test_kb_mcp_rag_tool(self):
        """RED: Test KB RAG query tool"""
        with patch('src.mcp_servers.kb_mcp.KBClient') as mock_kb_client_class:
            mock_kb_client = AsyncMock()
            mock_kb_client.kb_rag_query = AsyncMock(return_value={
                "answer": "Approvals require manager sign-off",
                "sources": [{"id": "doc3"}],
                "confidence": 0.92
            })
            mock_kb_client_class.return_value = mock_kb_client

            mcp = KBMCP(
                kb_base_url="http://localhost:8001",
                kb_api_key="test-key"
            )

            result = await mcp.execute_tool(
                tool_name="kb_rag_query",
                params={"question": "What is the approval process?"},
                tenant_id="test_tenant"
            )

            assert "answer" in result
            assert "sources" in result
            assert result["confidence"] > 0.8
