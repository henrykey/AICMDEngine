from __future__ import annotations

import json
import logging
import sqlite3
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import faiss
import numpy as np


logger = logging.getLogger(__name__)


class FaissVectorStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._indices: Dict[str, faiss.IndexFlatIP] = {}
        self._external_ids: Dict[str, List[str]] = defaultdict(list)
        self._dimensions: Dict[str, int] = {}
        self._init_db()
        self._reload_indices()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS command_embeddings (
                    external_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    dimension INTEGER NOT NULL,
                    vector_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_command_embeddings_tenant_id ON command_embeddings(tenant_id)"
            )
            conn.commit()

    @staticmethod
    def _normalize(vector: List[float]) -> np.ndarray:
        array = np.array(vector, dtype="float32")
        norm = np.linalg.norm(array)
        if norm > 0:
            array = array / norm
        return array

    def _reload_indices(self) -> None:
        self._indices = {}
        self._external_ids = defaultdict(list)
        self._dimensions = {}
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT external_id, tenant_id, dimension, vector_json FROM command_embeddings ORDER BY external_id"
            ).fetchall()

        by_tenant: Dict[str, List[sqlite3.Row]] = defaultdict(list)
        for row in rows:
            by_tenant[str(row["tenant_id"])].append(row)

        for tenant_id, tenant_rows in by_tenant.items():
            dimension = int(tenant_rows[0]["dimension"])
            index = faiss.IndexFlatIP(dimension)
            vectors: List[np.ndarray] = []
            external_ids: List[str] = []
            for row in tenant_rows:
                vector = self._normalize(json.loads(row["vector_json"]))
                vectors.append(vector)
                external_ids.append(str(row["external_id"]))
            if vectors:
                stacked = np.vstack(vectors)
                index.add(stacked)
                self._indices[tenant_id] = index
                self._external_ids[tenant_id] = external_ids
                self._dimensions[tenant_id] = dimension

    def upsert_many(self, tenant_id: str, embeddings: Dict[str, List[float]], timestamp: str) -> int:
        if not embeddings:
            return 0
        with self._connect() as conn:
            for external_id, vector in embeddings.items():
                normalized = self._normalize(vector).tolist()
                conn.execute("DELETE FROM command_embeddings WHERE external_id = ?", (external_id,))
                conn.execute(
                    """
                    INSERT INTO command_embeddings (external_id, tenant_id, dimension, vector_json, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (external_id, tenant_id, len(normalized), json.dumps(normalized), timestamp),
                )
            conn.commit()
        self._reload_indices()
        return len(embeddings)

    def delete_many(self, tenant_id: str, external_ids: List[str]) -> int:
        if not external_ids:
            return 0
        with self._connect() as conn:
            result = conn.execute(
                f"DELETE FROM command_embeddings WHERE tenant_id = ? AND external_id IN ({','.join(['?'] * len(external_ids))})",
                [tenant_id, *external_ids],
            )
            deleted = int(result.rowcount or 0)
            conn.commit()
        self._reload_indices()
        return deleted

    def search(self, tenant_id: str, query_embedding: List[float], top_k: int) -> List[Tuple[str, float]]:
        index = self._indices.get(tenant_id)
        if index is None or index.ntotal == 0:
            return []
        vector = self._normalize(query_embedding).reshape(1, -1)
        if vector.shape[1] != self._dimensions.get(tenant_id):
            logger.warning(
                "Skipping vector search for tenant %s because query dimension %s does not match index dimension %s",
                tenant_id,
                vector.shape[1],
                self._dimensions.get(tenant_id),
            )
            return []
        scores, ids = index.search(vector, min(top_k, index.ntotal))
        results: List[Tuple[str, float]] = []
        external_ids = self._external_ids.get(tenant_id, [])
        for score, idx in zip(scores[0], ids[0]):
            if idx < 0 or idx >= len(external_ids):
                continue
            results.append((external_ids[idx], float(score)))
        return results

    def stats(self) -> Dict[str, object]:
        total_vectors = 0
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM command_embeddings").fetchone()
            total_vectors = int(row["count"]) if row else 0
        return {
            "vector_docs": total_vectors,
            "vector_tenants": len(self._indices),
        }
