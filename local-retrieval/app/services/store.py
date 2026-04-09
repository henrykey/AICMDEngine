from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.models import CommandDocument, CommandSearchResult


class SQLiteCommandStore:
    """SQLite-backed command store with FTS5 full-text retrieval."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS command_documents (
                    external_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    category TEXT NOT NULL,
                    content TEXT NOT NULL,
                    classification INTEGER NOT NULL DEFAULT 0,
                    include_in_kb INTEGER NOT NULL DEFAULT 0,
                    tags_json TEXT,
                    version TEXT,
                    metadata_json TEXT NOT NULL,
                    source_type TEXT,
                    source_name TEXT,
                    entity_type TEXT,
                    parameter_names_text TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS command_documents_fts USING fts5(
                    external_id UNINDEXED,
                    tenant_id UNINDEXED,
                    category UNINDEXED,
                    source_type UNINDEXED,
                    source_name UNINDEXED,
                    entity_type UNINDEXED,
                    title,
                    content,
                    tags_text,
                    parameter_names_text
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_command_documents_tenant_id ON command_documents(tenant_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_command_documents_source_name ON command_documents(source_name)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_command_documents_source_type ON command_documents(source_type)"
            )
            conn.commit()

    @staticmethod
    def _extract_tenant_id(document: CommandDocument, fallback_tenant_id: str) -> str:
        metadata = document.metadata or {}
        tenant_id = metadata.get("tenant_id")
        if tenant_id is None:
            return fallback_tenant_id
        return str(tenant_id)

    @staticmethod
    def _extract_parameter_names_text(document: CommandDocument) -> str:
        parameter_names = (document.metadata or {}).get("parameter_names") or []
        return " ".join(str(name) for name in parameter_names if name)

    @staticmethod
    def _build_tags_text(document: CommandDocument) -> str:
        return " ".join(document.tags or [])

    @staticmethod
    def _normalize_fts_query(query: str) -> str:
        terms = [term.strip() for term in query.split() if term.strip()]
        if not terms:
            return ""
        escaped = []
        for term in terms:
            sanitized = term.replace('"', '""')
            escaped.append(f'"{sanitized}"')
        return " OR ".join(escaped)

    def upsert_many(self, documents: List[CommandDocument], tenant_id: str) -> List[str]:
        doc_ids: List[str] = []
        timestamp = datetime.now(timezone.utc).isoformat()

        with self._connect() as conn:
            for document in documents:
                effective_tenant_id = self._extract_tenant_id(document, tenant_id)
                metadata_json = json.dumps(document.metadata, ensure_ascii=False)
                tags_json = json.dumps(document.tags or [], ensure_ascii=False)
                tags_text = self._build_tags_text(document)
                parameter_names_text = self._extract_parameter_names_text(document)
                source_type = (document.metadata or {}).get("source_type")
                source_name = (document.metadata or {}).get("source_name")
                entity_type = (document.metadata or {}).get("entity_type")

                conn.execute("DELETE FROM command_documents WHERE external_id = ?", (document.external_id,))
                conn.execute("DELETE FROM command_documents_fts WHERE external_id = ?", (document.external_id,))

                conn.execute(
                    """
                    INSERT INTO command_documents (
                        external_id, tenant_id, title, category, content, classification,
                        include_in_kb, tags_json, version, metadata_json, source_type,
                        source_name, entity_type, parameter_names_text, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document.external_id,
                        effective_tenant_id,
                        document.title,
                        document.category,
                        document.content,
                        document.classification,
                        1 if document.include_in_kb else 0,
                        tags_json,
                        document.version,
                        metadata_json,
                        source_type,
                        source_name,
                        entity_type,
                        parameter_names_text,
                        timestamp,
                    ),
                )

                conn.execute(
                    """
                    INSERT INTO command_documents_fts (
                        external_id, tenant_id, category, source_type, source_name,
                        entity_type, title, content, tags_text, parameter_names_text
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document.external_id,
                        effective_tenant_id,
                        document.category,
                        source_type,
                        source_name,
                        entity_type,
                        document.title,
                        document.content,
                        tags_text,
                        parameter_names_text,
                    ),
                )

                doc_ids.append(document.external_id)
            conn.commit()
        return doc_ids

    def delete_many(self, external_ids: List[str], tenant_id: str) -> int:
        deleted = 0
        with self._connect() as conn:
            for external_id in external_ids:
                row = conn.execute(
                    "SELECT external_id FROM command_documents WHERE external_id = ? AND tenant_id = ?",
                    (external_id, tenant_id),
                ).fetchone()
                if not row:
                    continue
                conn.execute("DELETE FROM command_documents WHERE external_id = ?", (external_id,))
                conn.execute("DELETE FROM command_documents_fts WHERE external_id = ?", (external_id,))
                deleted += 1
            conn.commit()
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
        params: List[object] = [tenant_id]
        where_clauses = ["d.tenant_id = ?"]

        if source_types:
            where_clauses.append(f"d.source_type IN ({','.join(['?'] * len(source_types))})")
            params.extend(source_types)
        if source_names:
            where_clauses.append(f"d.source_name IN ({','.join(['?'] * len(source_names))})")
            params.extend(source_names)
        if categories:
            where_clauses.append(f"d.category IN ({','.join(['?'] * len(categories))})")
            params.extend(categories)
        if entity_type:
            where_clauses.append("d.entity_type = ?")
            params.append(entity_type)

        fts_query = self._normalize_fts_query(query)
        if fts_query:
            sql = f"""
                SELECT
                    d.external_id,
                    d.title,
                    d.category,
                    d.content,
                    d.metadata_json,
                    bm25(command_documents_fts, 10.0, 6.0, 2.0, 2.0) AS rank
                FROM command_documents_fts
                JOIN command_documents d ON d.external_id = command_documents_fts.external_id
                WHERE command_documents_fts MATCH ? AND {" AND ".join(where_clauses)}
                ORDER BY rank ASC
                LIMIT ?
            """
            sql_params = [fts_query, *params, top_k]
            with self._connect() as conn:
                rows = conn.execute(sql, sql_params).fetchall()
            hits = [self._row_to_result(row) for row in rows]
            if hits:
                return hits

        like_term = f"%{query.strip()}%"
        with self._connect() as conn:
            sql = f"""
                SELECT
                    external_id,
                    title,
                    category,
                    content,
                    metadata_json,
                    1.0 AS rank
                FROM command_documents d
                WHERE {" AND ".join(where_clauses)}
                  AND (title LIKE ? OR content LIKE ? OR parameter_names_text LIKE ?)
                LIMIT ?
            """
            rows = conn.execute(sql, [*params, like_term, like_term, like_term, top_k]).fetchall()
        return [self._row_to_result(row, fallback_rank=1.0) for row in rows]

    def get_documents_by_ids(
        self,
        tenant_id: str,
        external_ids: List[str],
        source_types: Optional[List[str]] = None,
        source_names: Optional[List[str]] = None,
        categories: Optional[List[str]] = None,
        entity_type: Optional[str] = None,
    ) -> Dict[str, CommandSearchResult]:
        if not external_ids:
            return {}

        params: List[object] = [tenant_id, *external_ids]
        where_clauses = [
            "tenant_id = ?",
            f"external_id IN ({','.join(['?'] * len(external_ids))})",
        ]

        if source_types:
            where_clauses.append(f"source_type IN ({','.join(['?'] * len(source_types))})")
            params.extend(source_types)
        if source_names:
            where_clauses.append(f"source_name IN ({','.join(['?'] * len(source_names))})")
            params.extend(source_names)
        if categories:
            where_clauses.append(f"category IN ({','.join(['?'] * len(categories))})")
            params.extend(categories)
        if entity_type:
            where_clauses.append("entity_type = ?")
            params.append(entity_type)

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT external_id, title, category, content, metadata_json, 1.0 AS rank
                FROM command_documents
                WHERE {" AND ".join(where_clauses)}
                """,
                params,
            ).fetchall()

        return {row["external_id"]: self._row_to_result(row, fallback_rank=1.0) for row in rows}

    def _row_to_result(self, row: sqlite3.Row, fallback_rank: Optional[float] = None) -> CommandSearchResult:
        rank = row["rank"] if "rank" in row.keys() else fallback_rank
        try:
            rank_value = float(rank if rank is not None else 1.0)
        except Exception:
            rank_value = 1.0
        total_score = 1.0 / (1.0 + max(rank_value, 0.0))
        return CommandSearchResult(
            documentId=row["external_id"],
            title=row["title"],
            category=row["category"],
            totalScore=total_score,
            content=row["content"],
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    def stats(self) -> Dict[str, object]:
        command_docs = 0
        mcp_docs = 0
        total_docs = 0
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT source_type, COUNT(*) AS count FROM command_documents GROUP BY source_type"
            ).fetchall()
            total_row = conn.execute("SELECT COUNT(*) AS count FROM command_documents").fetchone()
            total_docs = int(total_row["count"]) if total_row else 0

        for row in rows:
            source_type = row["source_type"]
            count = int(row["count"])
            if source_type == "mcp_tool":
                mcp_docs += count
            else:
                command_docs += count
        return {
            "command_docs": command_docs,
            "mcp_tool_docs": mcp_docs,
            "total_docs": total_docs,
            "db_path": self.db_path,
        }
