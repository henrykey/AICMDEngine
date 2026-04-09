from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.models import CommandDocument, CommandSearchResult
from app.services.embedding_client import OllamaEmbeddingClient
from app.services.store import SQLiteCommandStore
from app.services.vector_store import FaissVectorStore


logger = logging.getLogger(__name__)


class RetrievalService:
    def __init__(
        self,
        keyword_store: SQLiteCommandStore,
        vector_store: Optional[FaissVectorStore] = None,
        embedding_client: Optional[OllamaEmbeddingClient] = None,
        *,
        keyword_score_weight: float = 0.45,
        vector_score_weight: float = 0.55,
    ) -> None:
        self.keyword_store = keyword_store
        self.vector_store = vector_store
        self.embedding_client = embedding_client
        self.keyword_score_weight = keyword_score_weight
        self.vector_score_weight = vector_score_weight

    @property
    def vector_enabled(self) -> bool:
        return self.vector_store is not None and self.embedding_client is not None

    def upsert_many(self, documents: List[CommandDocument], tenant_id: str) -> List[str]:
        doc_ids = self.keyword_store.upsert_many(documents, tenant_id)
        if not self.vector_enabled or not documents:
            return doc_ids

        timestamp = datetime.now(timezone.utc).isoformat()
        embeddings: Dict[str, List[float]] = {}
        for document in documents:
            try:
                embeddings[document.external_id] = self.embedding_client.embed_text(document.content)
            except Exception as exc:
                logger.warning("Failed to embed command document %s: %s", document.external_id, exc)
        if embeddings:
            self.vector_store.upsert_many(tenant_id=str(tenant_id), embeddings=embeddings, timestamp=timestamp)
        return doc_ids

    def delete_many(self, external_ids: List[str], tenant_id: str) -> int:
        deleted = self.keyword_store.delete_many(external_ids, tenant_id)
        if self.vector_store is not None and external_ids:
            self.vector_store.delete_many(tenant_id=str(tenant_id), external_ids=external_ids)
        return deleted

    def search(
        self,
        tenant_id: str,
        query: str,
        top_k: int,
        source_types: Optional[List[str]] = None,
        source_names: Optional[List[str]] = None,
        categories: Optional[List[str]] = None,
        entity_type: Optional[str] = None,
    ) -> List[CommandSearchResult]:
        keyword_hits = self.keyword_store.search(
            tenant_id=tenant_id,
            query=query,
            top_k=max(top_k, 20),
            source_types=source_types,
            source_names=source_names,
            categories=categories,
            entity_type=entity_type,
        )
        if not self.vector_enabled:
            return keyword_hits[:top_k]

        query_embedding: Optional[List[float]] = None
        try:
            query_embedding = self.embedding_client.embed_text(query)
        except Exception as exc:
            logger.warning("Vector search disabled for this query because embedding failed: %s", exc)
            return keyword_hits[:top_k]

        vector_pairs = self.vector_store.search(tenant_id=str(tenant_id), query_embedding=query_embedding, top_k=max(top_k, 20))
        vector_ids = [external_id for external_id, _ in vector_pairs]
        vector_docs = self.keyword_store.get_documents_by_ids(
            tenant_id=tenant_id,
            external_ids=vector_ids,
            source_types=source_types,
            source_names=source_names,
            categories=categories,
            entity_type=entity_type,
        )

        keyword_scores = {hit.document_id: hit.total_score for hit in keyword_hits}
        merged: Dict[str, CommandSearchResult] = {hit.document_id: hit for hit in keyword_hits}

        for external_id, vector_score in vector_pairs:
            hit = vector_docs.get(external_id)
            if not hit:
                continue
            keyword_score = keyword_scores.get(external_id, 0.0)
            combined_score = (self.vector_score_weight * max(vector_score, 0.0)) + (
                self.keyword_score_weight * keyword_score
            )
            hit.total_score = combined_score
            merged[external_id] = hit

        ranked = sorted(merged.values(), key=lambda item: item.total_score, reverse=True)
        return ranked[:top_k]

    def stats(self) -> Dict[str, object]:
        stats = self.keyword_store.stats()
        stats["vector_enabled"] = self.vector_enabled
        if self.embedding_client is not None:
            stats["embedding_model"] = self.embedding_client.model
            stats["embedding_base_url"] = self.embedding_client.base_url
            stats["embedding_healthy"] = self.embedding_client.healthcheck()
        if self.vector_store is not None:
            stats.update(self.vector_store.stats())
        return stats
