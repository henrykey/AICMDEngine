import json
import logging
from typing import Any, Dict, List, Optional

import httpx
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.services.command_document_builder import CommandDocumentBuilder
from src.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


class CommandIndexer:
    """Manage Elasticsearch indexing for commands and MCP tools."""

    def __init__(
        self,
        es_url: str,
        index_name: str,
        embedding_service: EmbeddingService,
        db: AsyncIOMotorDatabase,
        api_key: str = "",
        index_version: str = "v1",
        timeout: int = 30,
    ):
        self.es_url = es_url.rstrip("/")
        self.index_name = index_name
        self.embedding_service = embedding_service
        self.db = db
        self.api_key = api_key
        self.index_version = index_version
        self.timeout = timeout
        self.document_builder = CommandDocumentBuilder()

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"ApiKey {self.api_key}"
        return headers

    def _mapping(self, dimensions: int) -> Dict[str, Any]:
        return {
            "mappings": {
                "properties": {
                    "doc_id": {"type": "keyword"},
                    "tenant_id": {"type": "integer"},
                    "source_type": {"type": "keyword"},
                    "source_name": {"type": "keyword"},
                    "command": {"type": "keyword"},
                    "summary": {"type": "text"},
                    "description": {"type": "text"},
                    "tags": {"type": "keyword"},
                    "examples": {"type": "text"},
                    "parameter_names": {"type": "keyword"},
                    "parameter_descriptions": {"type": "text"},
                    "risk_level": {"type": "keyword"},
                    "retrieval_text": {"type": "text"},
                    "embedding_provider": {"type": "keyword"},
                    "embedding_model": {"type": "keyword"},
                    "embedding_dimensions": {"type": "integer"},
                    "index_version": {"type": "keyword"},
                    "updated_at": {"type": "date"},
                    "embedding": {
                        "type": "dense_vector",
                        "dims": dimensions,
                        "index": True,
                        "similarity": "cosine"
                    }
                }
            }
        }

    async def ensure_index(self) -> None:
        if not self.es_url:
            raise ValueError("Elasticsearch URL is not configured")

        metadata = self.embedding_service.get_embedding_metadata()
        dimensions = metadata.get("dimensions")
        if not dimensions:
            raise ValueError("Embedding dimensions are required for command index creation")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.head(
                f"{self.es_url}/{self.index_name}",
                headers=self._headers()
            )
            if response.status_code == 200:
                return

            create_response = await client.put(
                f"{self.es_url}/{self.index_name}",
                headers=self._headers(),
                json=self._mapping(int(dimensions))
            )
            create_response.raise_for_status()
            logger.info("Created Elasticsearch command index '%s'", self.index_name)

    async def index_exists(self) -> bool:
        if not self.es_url:
            return False
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.head(
                f"{self.es_url}/{self.index_name}",
                headers=self._headers()
            )
        return response.status_code == 200

    async def _index_document(self, doc: Dict[str, Any]) -> None:
        embedding = await self.embedding_service.embed_text(doc["retrieval_text"])
        payload = dict(doc)
        payload["embedding"] = embedding

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.put(
                f"{self.es_url}/{self.index_name}/_doc/{doc['doc_id']}",
                headers=self._headers(),
                json=payload
            )
            response.raise_for_status()

    async def upsert_command(self, command_doc: Dict[str, Any], source_name: str) -> Dict[str, Any]:
        await self.ensure_index()
        embedding_metadata = self.embedding_service.get_embedding_metadata()
        doc = self.document_builder.build_from_command(
            command_doc=command_doc,
            source_name=source_name,
            index_version=self.index_version,
            embedding_metadata=embedding_metadata,
        )
        await self._index_document(doc)
        return doc

    async def bulk_upsert_commands(self, command_docs: List[Dict[str, Any]], source_name: str) -> int:
        if not command_docs:
            return 0

        await self.ensure_index()
        embedding_metadata = self.embedding_service.get_embedding_metadata()
        docs = [
            self.document_builder.build_from_command(
                command_doc=command_doc,
                source_name=source_name,
                index_version=self.index_version,
                embedding_metadata=embedding_metadata,
            )
            for command_doc in command_docs
        ]

        embeddings = await self.embedding_service.embed_texts([doc["retrieval_text"] for doc in docs])
        bulk_lines = []
        for doc, embedding in zip(docs, embeddings):
            payload = dict(doc)
            payload["embedding"] = embedding
            bulk_lines.append(json.dumps({"index": {"_index": self.index_name, "_id": doc["doc_id"]}}))
            bulk_lines.append(json.dumps(payload))

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.es_url}/_bulk",
                headers={"Content-Type": "application/x-ndjson", **({"Authorization": f"ApiKey {self.api_key}"} if self.api_key else {})},
                content="\n".join(bulk_lines) + "\n"
            )
            response.raise_for_status()

        return len(docs)

    async def upsert_mcp_tools(self, mcp_registry: Any) -> int:
        if not mcp_registry:
            return 0

        await self.ensure_index()
        embedding_metadata = self.embedding_service.get_embedding_metadata()
        docs = []
        for mcp in mcp_registry.get_all_mcps():
            tools_info = mcp.get_info()
            for tool_info in tools_info.get("tools", []):
                docs.append(
                    self.document_builder.build_from_mcp_tool(
                        mcp_name=mcp.name,
                        tool_info=tool_info,
                        index_version=self.index_version,
                        embedding_metadata=embedding_metadata,
                    )
                )

        if not docs:
            return 0

        embeddings = await self.embedding_service.embed_texts([doc["retrieval_text"] for doc in docs])
        bulk_lines = []
        for doc, embedding in zip(docs, embeddings):
            payload = dict(doc)
            payload["embedding"] = embedding
            bulk_lines.append(json.dumps({"index": {"_index": self.index_name, "_id": doc["doc_id"]}}))
            bulk_lines.append(json.dumps(payload))

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.es_url}/_bulk",
                headers={"Content-Type": "application/x-ndjson", **({"Authorization": f"ApiKey {self.api_key}"} if self.api_key else {})},
                content="\n".join(bulk_lines) + "\n"
            )
            response.raise_for_status()

        logger.info("Indexed %s MCP tool documents into '%s'", len(docs), self.index_name)
        return len(docs)

    async def delete_docs(self, doc_ids: List[str]) -> int:
        """Delete documents from the command retrieval index by document id."""
        if not doc_ids:
            return 0

        await self.ensure_index()

        bulk_lines = []
        for doc_id in doc_ids:
            bulk_lines.append(json.dumps({"delete": {"_index": self.index_name, "_id": doc_id}}))

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.es_url}/_bulk",
                headers={
                    "Content-Type": "application/x-ndjson",
                    **({"Authorization": f"ApiKey {self.api_key}"} if self.api_key else {})
                },
                content="\n".join(bulk_lines) + "\n"
            )
            response.raise_for_status()

        logger.info("Deleted %s command index documents from '%s'", len(doc_ids), self.index_name)
        return len(doc_ids)

    async def list_doc_ids(
        self,
        source_type: Optional[str] = None,
        source_name: Optional[str] = None,
        limit: int = 10000,
    ) -> List[str]:
        await self.ensure_index()
        filters: List[Dict[str, Any]] = []
        if source_type:
            filters.append({"term": {"source_type": source_type}})
        if source_name:
            filters.append({"term": {"source_name": source_name}})

        query: Dict[str, Any] = {
            "size": limit,
            "_source": ["doc_id"],
            "query": {
                "bool": {
                    "filter": filters
                }
            }
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.es_url}/{self.index_name}/_search",
                headers=self._headers(),
                json=query
            )
            response.raise_for_status()

        hits = response.json().get("hits", {}).get("hits", [])
        return [hit.get("_id") or hit.get("_source", {}).get("doc_id") for hit in hits if hit.get("_id") or hit.get("_source", {}).get("doc_id")]

    async def delete_by_source(
        self,
        source_type: Optional[str] = None,
        source_name: Optional[str] = None,
    ) -> int:
        doc_ids = await self.list_doc_ids(source_type=source_type, source_name=source_name)
        return await self.delete_docs(doc_ids)

    async def get_index_status(self) -> Dict[str, Any]:
        exists = await self.index_exists()
        if not exists:
            return {
                "exists": False,
                "index_name": self.index_name,
                "command_docs": 0,
                "mcp_tool_docs": 0,
                "total_docs": 0,
                "index_version": self.index_version,
            }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            total_response = await client.post(
                f"{self.es_url}/{self.index_name}/_count",
                headers=self._headers(),
                json={"query": {"match_all": {}}}
            )
            total_response.raise_for_status()

            agg_response = await client.post(
                f"{self.es_url}/{self.index_name}/_search",
                headers=self._headers(),
                json={
                    "size": 0,
                    "aggs": {
                        "by_source_type": {
                            "terms": {"field": "source_type"}
                        }
                    }
                }
            )
            agg_response.raise_for_status()

        total_docs = int(total_response.json().get("count", 0))
        buckets = agg_response.json().get("aggregations", {}).get("by_source_type", {}).get("buckets", [])
        counts = {bucket.get("key"): int(bucket.get("doc_count", 0)) for bucket in buckets}

        return {
            "exists": True,
            "index_name": self.index_name,
            "command_docs": counts.get("command", 0),
            "mcp_tool_docs": counts.get("mcp_tool", 0),
            "total_docs": total_docs,
            "index_version": self.index_version,
        }

    async def rebuild_from_mongo(self) -> int:
        await self.ensure_index()
        cursor = self.db["commands"].find({})
        command_docs = [doc async for doc in cursor]
        source_names: Dict[str, str] = {}
        if command_docs:
            set_ids = list({str(doc.get("command_set_id")) for doc in command_docs if doc.get("command_set_id")})
            if set_ids:
                object_ids = []
                for set_id in set_ids:
                    try:
                        object_ids.append(ObjectId(set_id))
                    except Exception:
                        continue
                async for command_set in self.db["command_sets"].find({"_id": {"$in": object_ids}}):
                    source_names[str(command_set["_id"])] = command_set.get("name", "manual")

        count = 0
        for doc in command_docs:
            source_name = source_names.get(str(doc.get("command_set_id")), "manual")
            await self.upsert_command(doc, source_name)
            count += 1
        return count
