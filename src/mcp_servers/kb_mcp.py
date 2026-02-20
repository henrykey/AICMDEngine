"""
Knowledge Base MCP Server

Provides MCP tools for KB access in workflow runtime:
- kb_search: Full-text search
- kb_semantic_search: Similarity search
- kb_rag_query: RAG with sources
"""

from typing import List, Dict, Any, Optional
import logging

from src.mcp.base_server import BaseMCPServer
from src.services.kb_client import KBClient, KBClientError

logger = logging.getLogger(__name__)


class KBMCPError(Exception):
    """KB MCP specific error"""
    pass


class KBMCP(BaseMCPServer):
    """MCP Server for Knowledge Base access"""

    def __init__(
        self,
        kb_base_url: str,
        kb_api_key: str,
        timeout: int = 30
    ):
        """Initialize KB MCP server"""
        super().__init__(
            name="kb_mcp",
            version="1.0.0"
        )
        self.kb_client = KBClient(
            kb_base_url=kb_base_url,
            kb_api_key=kb_api_key,
            tenant_id="default",
            timeout=timeout
        )

    async def list_tools(self, tenant_id: str) -> List[Dict[str, Any]]:
        """List available KB tools"""
        return [
            {
                "name": "kb_search",
                "description": "Full-text search against Knowledge Base using Elasticsearch",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query string"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max results (default: 10)",
                            "default": 10
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "kb_semantic_search",
                "description": "Semantic similarity search using embeddings (Milvus)",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Natural language query"
                        },
                        "similarity_threshold": {
                            "type": "number",
                            "description": "Min similarity (0-1, default: 0.7)",
                            "default": 0.7
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max results (default: 10)",
                            "default": 10
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "kb_rag_query",
                "description": "RAG query with LLM context and source attribution",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "Natural language question"
                        },
                        "context": {
                            "type": "string",
                            "description": "Optional additional context"
                        }
                    },
                    "required": ["question"]
                }
            }
        ]

    async def execute_tool(
        self,
        tool_name: str,
        params: Dict[str, Any],
        tenant_id: str
    ) -> Dict[str, Any]:
        """Execute KB tool"""
        try:
            if tool_name == "kb_search":
                return await self._handle_search(params, tenant_id)
            elif tool_name == "kb_semantic_search":
                return await self._handle_semantic_search(params, tenant_id)
            elif tool_name == "kb_rag_query":
                return await self._handle_rag_query(params, tenant_id)
            else:
                raise KBMCPError(f"Unknown tool: {tool_name}")
        except KBClientError as e:
            logger.error(f"KB error in {tool_name}: {e}")
            raise KBMCPError(f"KB query failed: {str(e)}")

    async def _handle_search(
        self,
        params: Dict[str, Any],
        tenant_id: str
    ) -> Dict[str, Any]:
        """Handle kb_search tool"""
        query = params.get("query")
        if not query:
            raise KBMCPError("query parameter required")

        limit = params.get("limit", 10)

        results = await self.kb_client.kb_search(query, limit=limit)

        return {
            "results": results,
            "count": len(results),
            "query": query
        }

    async def _handle_semantic_search(
        self,
        params: Dict[str, Any],
        tenant_id: str
    ) -> Dict[str, Any]:
        """Handle kb_semantic_search tool"""
        query = params.get("query")
        if not query:
            raise KBMCPError("query parameter required")

        threshold = params.get("similarity_threshold", 0.7)
        limit = params.get("limit", 10)

        results = await self.kb_client.kb_semantic_search(
            query,
            similarity_threshold=threshold,
            limit=limit
        )

        return {
            "results": results,
            "count": len(results),
            "query": query,
            "threshold": threshold
        }

    async def _handle_rag_query(
        self,
        params: Dict[str, Any],
        tenant_id: str
    ) -> Dict[str, Any]:
        """Handle kb_rag_query tool"""
        question = params.get("question")
        if not question:
            raise KBMCPError("question parameter required")

        context = params.get("context")

        # Note: LLM provider selection is handled at MCPRegistry level
        # If _llm_provider is in params, it means user specified a valid provider
        llm_provider = params.get("_llm_provider", "default")

        logger.info(f"[kb_mcp] Processing RAG query using LLM provider: {llm_provider}")

        result = await self.kb_client.kb_rag_query(
            question,
            context=context
        )

        return {
            "answer": result.get("answer", ""),
            "sources": result.get("sources", []),
            "confidence": result.get("confidence", 0.0),
            "question": question,
            "llm_provider": llm_provider
        }
