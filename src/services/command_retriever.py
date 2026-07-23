import logging
from typing import Any, Dict, List, Optional

from src.services.docintel_client import DocIntelClient

logger = logging.getLogger(__name__)


class CommandRetriever:
    """Retrieve the most relevant commands/tools from DocIntel."""

    def __init__(
        self,
        docintel_client: Optional[DocIntelClient] = None,
        retrieval_top_k: int = 30,
        prompt_top_k: int = 15,
        remote_min_results: int = 1,
        remote_min_top_score: float = 0.0,
        timeout: int = 30,
    ):
        self.docintel_client = docintel_client
        self.retrieval_top_k = retrieval_top_k
        self.prompt_top_k = prompt_top_k
        self.remote_min_results = remote_min_results
        self.remote_min_top_score = remote_min_top_score
        self.timeout = timeout

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

    def _supplement_membership_commands(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not any(str(candidate.get("command", "")).startswith("MCP.membership.") for candidate in candidates):
            return candidates

        existing = {candidate.get("command") for candidate in candidates}
        supplemented = list(candidates)
        helpers = [
            "MCP.membership.list_orgs",
            "MCP.membership.lookup_org",
            "MCP.membership.render_org_chart",
            "MCP.membership.list_roles",
            "MCP.membership.list_members",
            "MCP.membership.get_member_roles",
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

    def _matches_org_chart_intent(self, goal: str) -> bool:
        text = str(goal or "").strip().lower()
        if not text:
            return False
        keywords = [
            "organization structure",
            "organization chart",
            "org chart",
            "org tree",
            "organizational tree",
            "mermaid",
            "组织结构",
            "组织机构",
            "组织关系",
            "组织树",
            "机构关系",
            "机构结构",
        ]
        return any(keyword in text for keyword in keywords)

    def _prioritize_membership_commands_by_intent(self, candidates: List[Dict[str, Any]], goal: str) -> List[Dict[str, Any]]:
        if not self._matches_org_chart_intent(goal):
            return candidates

        preferred = []
        others = []
        preferred_commands = {
            "MCP.membership.render_org_chart",
            "MCP.membership.get_org_hierarchy",
            "MCP.membership.list_orgs",
            "MCP.membership.lookup_org",
        }
        for candidate in candidates:
            command = str(candidate.get("command", ""))
            if command in preferred_commands:
                preferred.append(candidate)
            else:
                others.append(candidate)
        return preferred + others

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

        prompt_candidates = self._prioritize_membership_commands_by_intent(
            self._supplement_membership_commands(raw_candidates),
            goal,
        )[: self.prompt_top_k]
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
        if preferred_backend not in (None, "docintel"):
            raise ValueError(f"Unsupported command retrieval backend: {preferred_backend}")
        if not self.docintel_client:
            raise RuntimeError("DocIntel command retrieval is not configured")
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
            logger.error("DocIntel command retrieval failed for tenant=%s: %s", tenant_id, e)
            raise RuntimeError(f"DocIntel command retrieval is unavailable: {e}") from e
