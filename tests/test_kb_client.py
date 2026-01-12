import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.services.kb_client import KBClient, KBClientError


class TestKBClient:
    """Test Knowledge Base Query Service Client"""

    @pytest.mark.asyncio
    async def test_kb_client_initialization(self):
        """
        RED: Test KBClient initializes with Membership KB API config

        Given: KB service URL and tenant context
        When: Create KBClient instance
        Then: Client initializes with proper configuration
        """
        client = KBClient(
            kb_base_url="http://localhost:8001",
            kb_api_key="test-key",
            tenant_id="test_tenant"
        )

        assert client.kb_base_url == "http://localhost:8001"
        assert client.kb_api_key == "test-key"
        assert client.tenant_id == "test_tenant"

    @pytest.mark.asyncio
    async def test_kb_search_simple(self):
        """
        RED: Test simple full-text search against KB

        Given: Query string "approval process"
        When: Call kb_search()
        Then: Return list of matching documents
        """
        # Create mock response that acts as context manager
        mock_response = MagicMock()
        mock_response.json = AsyncMock(return_value={
            "results": [
                {
                    "id": "doc1",
                    "title": "Approval Process Guide",
                    "content": "Process for approving requests...",
                    "relevance_score": 0.95
                }
            ],
            "total": 1
        })
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        # Mock session - get returns async context manager
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch('src.services.kb_client.aiohttp.ClientSession', return_value=mock_session):
            client = KBClient(
                kb_base_url="http://localhost:8001",
                kb_api_key="test-key",
                tenant_id="test_tenant"
            )

            results = await client.kb_search("approval process")

            assert len(results) == 1
            assert results[0]["title"] == "Approval Process Guide"
            assert results[0]["relevance_score"] == 0.95

    @pytest.mark.asyncio
    async def test_kb_semantic_search(self):
        """
        RED: Test semantic similarity search using embeddings

        Given: Query "How do we handle manager approvals?"
        When: Call kb_semantic_search()
        Then: Return semantically similar documents
        """
        mock_response = MagicMock()
        mock_response.json = AsyncMock(return_value={
            "results": [
                {
                    "id": "doc2",
                    "title": "Role-Based Approval Matrix",
                    "content": "Manager approvals by role...",
                    "similarity_score": 0.87
                }
            ],
            "total": 1
        })
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch('src.services.kb_client.aiohttp.ClientSession', return_value=mock_session):
            client = KBClient(
                kb_base_url="http://localhost:8001",
                kb_api_key="test-key",
                tenant_id="test_tenant"
            )

            results = await client.kb_semantic_search(
                "How do we handle manager approvals?",
                similarity_threshold=0.8
            )

            assert len(results) == 1
            assert results[0]["similarity_score"] >= 0.8

    @pytest.mark.asyncio
    async def test_kb_rag_query(self):
        """
        RED: Test Retrieval-Augmented Generation query

        Given: Question and context
        When: Call kb_rag_query()
        Then: Return RAG response with source citations
        """
        mock_response = MagicMock()
        mock_response.json = AsyncMock(return_value={
            "answer": "Approval is required from Finance team for amounts > $1000",
            "sources": [
                {"id": "doc3", "title": "Finance Approval Policy", "excerpt": "..."}
            ],
            "confidence": 0.92
        })
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch('src.services.kb_client.aiohttp.ClientSession', return_value=mock_session):
            client = KBClient(
                kb_base_url="http://localhost:8001",
                kb_api_key="test-key",
                tenant_id="test_tenant"
            )

            result = await client.kb_rag_query(
                "What is the approval requirement for large expenses?"
            )

            assert "approval" in result["answer"].lower()
            assert len(result["sources"]) > 0
            assert result["confidence"] > 0.8

    @pytest.mark.asyncio
    async def test_kb_client_error_handling(self):
        """
        RED: Test KB client handles API errors gracefully

        Given: KB service returns 500 error
        When: Call kb_search()
        Then: Raise KBClientError with informative message
        """
        mock_response = MagicMock()
        mock_response.status = 500
        mock_response.text = AsyncMock(return_value="Internal Server Error")
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch('src.services.kb_client.aiohttp.ClientSession', return_value=mock_session):
            client = KBClient(
                kb_base_url="http://localhost:8001",
                kb_api_key="test-key",
                tenant_id="test_tenant"
            )

            with pytest.raises(KBClientError) as exc_info:
                await client.kb_search("test")

            assert "500" in str(exc_info.value)
