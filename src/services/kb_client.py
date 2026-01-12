"""
Knowledge Base Query Service Client

Provides async client for querying Membership's Knowledge Base API
with support for:
- Full-text search (Elasticsearch)
- Semantic search (Milvus embeddings)
- RAG queries (Retrieval-Augmented Generation)
"""

import aiohttp
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class KBClientError(Exception):
    """Raised when KB service returns error"""
    pass


@dataclass
class KBResult:
    """Single KB query result"""
    id: str
    title: str
    content: str
    score: float  # relevance or similarity score
    metadata: Dict[str, Any]


class KBClient:
    """
    Async client for Membership Knowledge Base API

    Supports three query types:
    1. Simple full-text search (ES)
    2. Semantic similarity search (Milvus)
    3. RAG queries with source attribution
    """

    def __init__(
        self,
        kb_base_url: str,
        kb_api_key: str,
        tenant_id: str,
        timeout: int = 30
    ):
        """
        Initialize KB client

        Args:
            kb_base_url: Base URL of KB API (e.g., http://kb.membership.local:8001)
            kb_api_key: API key for authentication
            tenant_id: Tenant ID for multi-tenant isolation
            timeout: Request timeout in seconds
        """
        self.kb_base_url = kb_base_url.rstrip('/')
        self.kb_api_key = kb_api_key
        self.tenant_id = tenant_id
        self.timeout = timeout

    async def kb_search(
        self,
        query: str,
        limit: int = 10,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Full-text search using Elasticsearch

        Args:
            query: Search query string
            limit: Max results to return
            offset: Pagination offset

        Returns:
            List of matching documents with relevance scores

        Raises:
            KBClientError: On API error
        """
        url = f"{self.kb_base_url}/api/v1/kb/search"

        params = {
            "q": query,
            "limit": limit,
            "offset": offset
        }

        headers = {
            "Authorization": f"Bearer {self.kb_api_key}",
            "X-Tenant-ID": self.tenant_id
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                params=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise KBClientError(
                        f"KB search failed: {response.status} - {error_text}"
                    )

                data = await response.json()
                return data.get("results", [])

    async def kb_semantic_search(
        self,
        query: str,
        similarity_threshold: float = 0.7,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Semantic similarity search using Milvus embeddings

        Args:
            query: Search query string
            similarity_threshold: Minimum similarity score (0-1)
            limit: Max results to return

        Returns:
            List of semantically similar documents

        Raises:
            KBClientError: On API error
        """
        url = f"{self.kb_base_url}/api/v1/kb/semantic-search"

        payload = {
            "query": query,
            "similarity_threshold": similarity_threshold,
            "limit": limit
        }

        headers = {
            "Authorization": f"Bearer {self.kb_api_key}",
            "X-Tenant-ID": self.tenant_id,
            "Content-Type": "application/json"
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise KBClientError(
                        f"KB semantic search failed: {response.status} - {error_text}"
                    )

                data = await response.json()
                return data.get("results", [])

    async def kb_rag_query(
        self,
        question: str,
        context: Optional[str] = None,
        include_sources: bool = True
    ) -> Dict[str, Any]:
        """
        Retrieval-Augmented Generation query

        Combines KB search with LLM to generate contextual answers

        Args:
            question: Natural language question
            context: Optional additional context
            include_sources: Whether to include source citations

        Returns:
            RAG response with answer, sources, and confidence

        Raises:
            KBClientError: On API error
        """
        url = f"{self.kb_base_url}/api/v1/kb/rag-query"

        payload = {
            "question": question,
            "context": context,
            "include_sources": include_sources
        }

        headers = {
            "Authorization": f"Bearer {self.kb_api_key}",
            "X-Tenant-ID": self.tenant_id,
            "Content-Type": "application/json"
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise KBClientError(
                        f"KB RAG query failed: {response.status} - {error_text}"
                    )

                data = await response.json()
                return {
                    "answer": data.get("answer", ""),
                    "sources": data.get("sources", []),
                    "confidence": data.get("confidence", 0.0)
                }
