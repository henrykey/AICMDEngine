import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx

from src.services.docintel_client import DocIntelClient
from src.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


class CommandRetriever:
    """Retrieve the most relevant commands/tools from Elasticsearch."""

    def __init__(
        self,
        es_url: str,
        index_name: str,
        embedding_service: EmbeddingService,
        docintel_client: Optional[DocIntelClient] = None,
        local_retrieval_client: Optional[DocIntelClient] = None,
        api_key: str = "",
        retrieval_top_k: int = 30,
        prompt_top_k: int = 15,
        prefer_remote: bool = True,
        remote_min_results: int = 1,
        remote_min_top_score: float = 0.0,
        timeout: int = 30,
    ):
        self.es_url = es_url.rstrip("/")
        self.index_name = index_name
        self.embedding_service = embedding_service
        self.docintel_client = docintel_client
        self.local_retrieval_client = local_retrieval_client
        self.api_key = api_key
        self.retrieval_top_k = retrieval_top_k
        self.prompt_top_k = prompt_top_k
        self.prefer_remote = prefer_remote
        self.remote_min_results = remote_min_results
        self.remote_min_top_score = remote_min_top_score
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"ApiKey {self.api_key}"
        return headers

    async def _keyword_search(self, goal: str, tenant_id: int, limit: int) -> List[Dict[str, Any]]:
        return await self._search(
            body={
                "size": limit,
                "query": {
                    "bool": {
                        "filter": [
                            {"terms": {"tenant_id": [tenant_id, 0]}}
                        ],
                        "must": [
                            {
                                "multi_match": {
                                    "query": goal,
                                    "fields": [
                                        "retrieval_text^4",
                                        "summary^3",
                                        "description^2",
                                        "examples^2",
                                        "parameter_descriptions",
                                        "parameter_names"
                                    ]
                                }
                            }
                        ]
                    }
                }
            }
        )

    async def _search(self, body: Dict[str, Any]) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.es_url}/{self.index_name}/_search",
                headers=self._headers(),
                json=body
            )
            response.raise_for_status()
        return response.json().get("hits", {}).get("hits", [])

    def _apply_filters(
        self,
        bool_query: Dict[str, Any],
        tenant_id: int,
        source_types: Optional[List[str]] = None,
        source_names: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        filters = [{"terms": {"tenant_id": [tenant_id, 0]}}]
        if source_types:
            filters.append({"terms": {"source_type": source_types}})
        if source_names:
            filters.append({"terms": {"source_name": source_names}})
        bool_query["filter"] = filters
        return bool_query

    async def _filtered_keyword_search(
        self,
        goal: str,
        tenant_id: int,
        limit: int,
        source_types: Optional[List[str]] = None,
        source_names: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        query = {
            "size": limit,
            "query": {
                "bool": self._apply_filters(
                    {
                        "must": [
                        {
                            "multi_match": {
                                "query": goal,
                                "fields": [
                                    "retrieval_text^4",
                                    "summary^3",
                                    "description^2",
                                    "examples^2",
                                    "parameter_descriptions",
                                    "parameter_names"
                                ]
                            }
                        }
                    ]
                    },
                    tenant_id,
                    source_types,
                    source_names
                )
            }
        }
        return await self._search(query)

    async def _vector_search(
        self,
        goal: str,
        tenant_id: int,
        limit: int,
        source_types: Optional[List[str]] = None,
        source_names: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        embedding = await self.embedding_service.embed_text(goal)
        query = {
            "size": limit,
            "query": {
                "script_score": {
                    "query": {"bool": self._apply_filters({}, tenant_id, source_types, source_names)},
                    "script": {
                        "source": "cosineSimilarity(params.query_vector, 'embedding') + 1.0",
                        "params": {"query_vector": embedding}
                    }
                }
            }
        }

        return await self._search(query)

    def _to_planner_command(self, source_doc: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "command": source_doc.get("command", ""),
            "summary": source_doc.get("summary", ""),
            "description": source_doc.get("description", ""),
            "parameters": source_doc.get("parameters", []),
            "riskLevel": source_doc.get("risk_level", "normal"),
            "sourceType": source_doc.get("source_type"),
            "sourceName": source_doc.get("source_name"),
            "tags": source_doc.get("tags", []),
        }

    def _to_planner_command_from_remote(self, result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        metadata = result.get("metadata", {}) or {}
        command = metadata.get("command")
        if not command:
            return None
        parameter_names = metadata.get("parameter_names") or []
        return {
            "command": command,
            "summary": result.get("title", ""),
            "description": result.get("chunkText") or result.get("content") or result.get("title", ""),
            "parameters": [{"name": name} for name in parameter_names if name],
            "riskLevel": metadata.get("risk_level", "normal"),
            "sourceType": metadata.get("source_type"),
            "sourceName": metadata.get("source_name"),
            "tags": metadata.get("tags", []),
        }

    def _merge_hits(
        self,
        keyword_hits: List[Dict[str, Any]],
        vector_hits: List[Dict[str, Any]]
    ) -> List[Tuple[str, Dict[str, Any]]]:
        merged: Dict[str, Dict[str, Any]] = {}

        for hit in keyword_hits:
            source = hit.get("_source", {})
            doc_id = source.get("doc_id") or hit.get("_id")
            if not doc_id:
                continue
            merged.setdefault(doc_id, {"source": source, "keyword_score": 0.0, "vector_score": 0.0})
            merged[doc_id]["keyword_score"] = float(hit.get("_score", 0.0))

        for hit in vector_hits:
            source = hit.get("_source", {})
            doc_id = source.get("doc_id") or hit.get("_id")
            if not doc_id:
                continue
            merged.setdefault(doc_id, {"source": source, "keyword_score": 0.0, "vector_score": 0.0})
            merged[doc_id]["vector_score"] = float(hit.get("_score", 0.0))

        results = []
        for doc_id, item in merged.items():
            final_score = (0.35 * item["keyword_score"]) + (0.65 * item["vector_score"])
            item["final_score"] = final_score
            results.append((doc_id, item))

        results.sort(key=lambda item: item[1]["final_score"], reverse=True)
        return results

    def _supplement_membership_commands(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not any(str(candidate.get("command", "")).startswith("MCP.membership.") for candidate in candidates):
            return candidates

        existing = {candidate.get("command") for candidate in candidates}
        supplemented = list(candidates)
        helpers = [
            "MCP.membership.list_orgs",
            "MCP.membership.list_roles",
            "MCP.membership.list_members",
        ]
        for helper in helpers:
            if helper not in existing:
                supplemented.append({
                    "command": helper,
                    "summary": f"Helper command for {helper}",
                    "description": "Supplemented helper command for membership planning",
                    "parameters": [],
                    "riskLevel": "normal",
                    "sourceType": "mcp_tool",
                    "sourceName": "membership",
                    "tags": ["membership", "mcp", "helper"],
                })
        return supplemented

    async def _retrieve_local(
        self,
        goal: str,
        tenant_id: int,
        candidate_limit: Optional[int] = None,
        source_types: Optional[List[str]] = None,
        source_names: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        if not self.es_url:
            raise ValueError("Local ES command retrieval is unavailable because ELASTICSEARCH_URL is not configured")
        limit = candidate_limit or self.retrieval_top_k
        keyword_hits = await self._filtered_keyword_search(goal, tenant_id, limit, source_types, source_names)
        vector_hits = await self._vector_search(goal, tenant_id, limit, source_types, source_names)
        merged = self._merge_hits(keyword_hits, vector_hits)

        raw_candidates = [self._to_planner_command(item["source"]) for _, item in merged[:limit]]
        prompt_candidates = self._supplement_membership_commands(raw_candidates)[: self.prompt_top_k]
        metadata = self.embedding_service.get_embedding_metadata()

        logger.info(
            "Retrieved command candidates for tenant=%s keyword_hits=%s vector_hits=%s raw=%s prompt=%s",
            tenant_id,
            len(keyword_hits),
            len(vector_hits),
            len(raw_candidates),
            len(prompt_candidates),
        )

        return {
            "raw_candidates": raw_candidates,
            "prompt_candidates": prompt_candidates,
            "diagnostics": {
                "retrieval_backend": "local_es",
                "keyword_hits": len(keyword_hits),
                "vector_hits": len(vector_hits),
                "raw_candidate_count": len(raw_candidates),
                "prompt_candidate_count": len(prompt_candidates),
                "embedding_provider": metadata.get("provider"),
                "embedding_model": metadata.get("model"),
                "top_commands": [candidate.get("command", "") for candidate in prompt_candidates[:5]],
            }
        }

    async def _retrieve_remote(
        self,
        client: DocIntelClient,
        backend_name: str,
        goal: str,
        tenant_id: int,
        candidate_limit: Optional[int] = None,
        source_types: Optional[List[str]] = None,
        source_names: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        auth_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not client:
            raise ValueError(f"{backend_name} client is not configured")

        limit = candidate_limit or self.retrieval_top_k
        response = await client.search_commands(
            query=goal,
            tenant_id=tenant_id,
            top_k=limit,
            source_types=source_types,
            source_names=source_names,
            user_id=user_id,
            auth_token=auth_token,
        )
        results = response.get("results", []) or []
        raw_candidates = []
        top_score = None
        for index, result in enumerate(results):
            if index == 0:
                try:
                    top_score = float(result.get("totalScore", 0.0))
                except Exception:
                    top_score = 0.0
            candidate = self._to_planner_command_from_remote(result)
            if candidate:
                raw_candidates.append(candidate)

        if len(raw_candidates) < self.remote_min_results:
            raise ValueError(f"DocIntel returned insufficient results: {len(raw_candidates)}")
        if top_score is not None and top_score < self.remote_min_top_score:
            raise ValueError(f"DocIntel top score below threshold: {top_score}")

        prompt_candidates = self._supplement_membership_commands(raw_candidates)[: self.prompt_top_k]
        return {
            "raw_candidates": raw_candidates,
            "prompt_candidates": prompt_candidates,
            "diagnostics": {
                "retrieval_backend": backend_name,
                "remote_candidate_count": len(raw_candidates),
                "remote_top_score": top_score,
                "raw_candidate_count": len(raw_candidates),
                "prompt_candidate_count": len(prompt_candidates),
                "embedding_provider": backend_name,
                "embedding_model": f"{backend_name}-managed",
                "top_commands": [candidate.get("command", "") for candidate in prompt_candidates[:5]],
            }
        }

    async def retrieve(
        self,
        goal: str,
        tenant_id: int,
        candidate_limit: Optional[int] = None,
        source_types: Optional[List[str]] = None,
        source_names: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        auth_token: Optional[str] = None,
        preferred_backend: Optional[str] = None,
    ) -> Dict[str, Any]:
        if preferred_backend == "local_semantic" and self.local_retrieval_client:
            try:
                return await self._retrieve_remote(
                    self.local_retrieval_client,
                    "local_semantic",
                    goal,
                    tenant_id,
                    candidate_limit,
                    source_types,
                    source_names,
                    user_id,
                    auth_token,
                )
            except Exception as e:
                logger.warning("Preferred local semantic retrieval failed for tenant=%s; falling back to local ES: %s", tenant_id, e)
                try:
                    local = await self._retrieve_local(goal, tenant_id, candidate_limit, source_types, source_names)
                    local.setdefault("diagnostics", {})
                    local["diagnostics"]["remote_fallback_reason"] = str(e)
                    local["diagnostics"]["remote_candidate_count"] = 0
                    return local
                except Exception as local_error:
                    logger.error(
                        "Local ES fallback also failed for tenant=%s after preferred local semantic failure. local_semantic_error=%s local_error=%s",
                        tenant_id,
                        e,
                        local_error,
                    )
                    raise ValueError(
                        f"Local semantic unavailable ({e}); local ES unavailable ({local_error})"
                    ) from local_error

        if preferred_backend == "docintel" and self.docintel_client:
            try:
                return await self._retrieve_remote(
                    self.docintel_client,
                    "docintel",
                    goal,
                    tenant_id,
                    candidate_limit,
                    source_types,
                    source_names,
                    user_id,
                    auth_token,
                )
            except Exception as e:
                logger.warning("Preferred DocIntel retrieval failed for tenant=%s; trying local semantic fallback: %s", tenant_id, e)
                remote_error: Exception = e
                if self.local_retrieval_client:
                    try:
                        local_semantic = await self._retrieve_remote(
                            self.local_retrieval_client,
                            "local_semantic",
                            goal,
                            tenant_id,
                            candidate_limit,
                            source_types,
                            source_names,
                            user_id,
                            auth_token,
                        )
                        local_semantic.setdefault("diagnostics", {})
                        local_semantic["diagnostics"]["remote_fallback_reason"] = str(remote_error)
                        local_semantic["diagnostics"]["remote_candidate_count"] = 0
                        return local_semantic
                    except Exception as local_semantic_error:
                        remote_error = ValueError(
                            f"DocIntel unavailable ({e}); local semantic unavailable ({local_semantic_error})"
                        )
                try:
                    local = await self._retrieve_local(goal, tenant_id, candidate_limit, source_types, source_names)
                    local.setdefault("diagnostics", {})
                    local["diagnostics"]["remote_fallback_reason"] = str(remote_error)
                    local["diagnostics"]["remote_candidate_count"] = 0
                    return local
                except Exception as local_error:
                    raise ValueError(
                        f"{remote_error}; local ES unavailable ({local_error})"
                    ) from local_error

        if self.docintel_client and self.prefer_remote:
            try:
                return await self._retrieve_remote(
                    self.docintel_client,
                    "docintel",
                    goal,
                    tenant_id,
                    candidate_limit,
                    source_types,
                    source_names,
                    user_id,
                    auth_token,
                )
            except Exception as e:
                logger.warning("DocIntel retrieval failed for tenant=%s; trying local semantic fallback: %s", tenant_id, e)
                remote_error: Exception = e
                if self.local_retrieval_client:
                    try:
                        local_semantic = await self._retrieve_remote(
                            self.local_retrieval_client,
                            "local_semantic",
                            goal,
                            tenant_id,
                            candidate_limit,
                            source_types,
                            source_names,
                            user_id,
                            auth_token,
                        )
                        local_semantic.setdefault("diagnostics", {})
                        local_semantic["diagnostics"]["remote_fallback_reason"] = str(remote_error)
                        local_semantic["diagnostics"]["remote_candidate_count"] = 0
                        return local_semantic
                    except Exception as local_semantic_error:
                        logger.warning(
                            "Local semantic fallback also failed for tenant=%s after DocIntel failure. docintel_error=%s local_semantic_error=%s",
                            tenant_id,
                            e,
                            local_semantic_error,
                        )
                        remote_error = ValueError(
                            f"DocIntel unavailable ({e}); local semantic unavailable ({local_semantic_error})"
                        )
                try:
                    local = await self._retrieve_local(goal, tenant_id, candidate_limit, source_types, source_names)
                    local.setdefault("diagnostics", {})
                    local["diagnostics"]["remote_fallback_reason"] = str(remote_error)
                    local["diagnostics"]["remote_candidate_count"] = 0
                    return local
                except Exception as local_error:
                    logger.error(
                        "Local ES fallback also failed for tenant=%s after remote failure. remote_error=%s local_error=%s",
                        tenant_id,
                        remote_error,
                        local_error,
                    )
                    raise ValueError(
                        f"{remote_error}; local ES unavailable ({local_error})"
                    ) from local_error

        if self.local_retrieval_client:
            try:
                return await self._retrieve_remote(
                    self.local_retrieval_client,
                    "local_semantic",
                    goal,
                    tenant_id,
                    candidate_limit,
                    source_types,
                    source_names,
                    user_id,
                    auth_token,
                )
            except Exception as e:
                logger.warning("Local semantic retrieval failed for tenant=%s; falling back to local ES: %s", tenant_id, e)
                try:
                    local = await self._retrieve_local(goal, tenant_id, candidate_limit, source_types, source_names)
                    local.setdefault("diagnostics", {})
                    local["diagnostics"]["remote_fallback_reason"] = str(e)
                    local["diagnostics"]["remote_candidate_count"] = 0
                    return local
                except Exception as local_error:
                    logger.error(
                        "Local ES fallback also failed for tenant=%s after local semantic failure. local_semantic_error=%s local_error=%s",
                        tenant_id,
                        e,
                        local_error,
                    )
                    raise ValueError(
                        f"Local semantic unavailable ({e}); local ES unavailable ({local_error})"
                    ) from local_error

        try:
            return await self._retrieve_local(goal, tenant_id, candidate_limit, source_types, source_names)
        except Exception as e:
            logger.error("Local ES retrieval failed for tenant=%s: %s", tenant_id, e)
            raise
