import httpx
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class DocIntelClient:
    """Client for Membership DocIntel command corpus APIs."""

    def __init__(
        self,
        base_url: str,
        search_path: str = "/v2/documents/search",
        command_sync_path: str = "/v2/documents/commands/sync/batch",
        command_delete_path: str = "/v2/documents/commands/delete",
        api_key: str = "",
        timeout_ms: int = 10000,
        category_prefix: str = "cmdengine.command",
    ):
        self.base_url = base_url.rstrip("/")
        self.search_path = search_path
        self.command_sync_path = command_sync_path
        self.command_delete_path = command_delete_path
        self.api_key = api_key
        self.timeout = max(timeout_ms / 1000.0, 1.0)
        self.category_prefix = category_prefix.rstrip(".")

    def _headers(
        self,
        tenant_id: int,
        user_id: Optional[str] = None,
        auth_token: Optional[str] = None,
    ) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "X-Tenant-ID": str(tenant_id),
        }
        if user_id:
            headers["X-User-ID"] = str(user_id)
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        elif self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _categories_for_source_types(self, source_types: Optional[List[str]]) -> List[str]:
        if not source_types:
            return [f"{self.category_prefix}.membership", f"{self.category_prefix}.mcp"]
        categories: List[str] = []
        if "command" in source_types:
            categories.append(f"{self.category_prefix}.membership")
        if "mcp_tool" in source_types:
            categories.append(f"{self.category_prefix}.mcp")
        return categories or [self.category_prefix]

    @staticmethod
    def _response_excerpt(response: httpx.Response, limit: int = 1200) -> str:
        try:
            text = response.text or ""
        except Exception:
            return ""
        text = text.strip()
        if len(text) > limit:
            return text[:limit] + "...(truncated)"
        return text

    @staticmethod
    def _raise_for_status_with_body(
        response: httpx.Response,
        operation: str,
        payload_summary: Dict[str, Any],
    ) -> None:
        if response.is_success:
            return
        body_excerpt = DocIntelClient._response_excerpt(response)
        logger.error(
            "DocIntel %s failed: status=%s url=%s payload_summary=%s response_body=%s",
            operation,
            response.status_code,
            response.request.url,
            payload_summary,
            body_excerpt,
        )
        response.raise_for_status()

    async def search_commands(
        self,
        query: str,
        tenant_id: int,
        top_k: int = 20,
        source_types: Optional[List[str]] = None,
        source_names: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        auth_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "query": query,
            "searchMode": "TWO_STAGE",
            "topK": top_k,
            "searchChunks": False,
            "categories": self._categories_for_source_types(source_types),
            "entityType": "command",
            "metadataFilters": {"entity_type": "command"},
        }
        if source_types:
            payload["metadataFilters"]["source_type"] = source_types
        if source_names:
            payload["metadataFilters"]["source_name"] = source_names

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}{self.search_path}",
                headers=self._headers(tenant_id, user_id, auth_token),
                json=payload,
            )
            self._raise_for_status_with_body(
                response,
                "search_commands",
                {
                    "tenant_id": tenant_id,
                    "top_k": top_k,
                    "source_types": source_types or [],
                    "source_names": source_names or [],
                },
            )
        return response.json()

    async def bulk_upsert_command_documents(
        self,
        tenant_id: int,
        documents: List[Dict[str, Any]],
        user_id: Optional[str] = None,
        auth_token: Optional[str] = None,
    ) -> int:
        if not documents:
            return 0

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}{self.command_sync_path}",
                headers=self._headers(tenant_id, user_id, auth_token),
                json={"documents": documents},
            )
            self._raise_for_status_with_body(
                response,
                "bulk_upsert_command_documents",
                {
                    "tenant_id": tenant_id,
                    "document_count": len(documents),
                    "first_external_id": documents[0].get("externalId") if documents else None,
                    "first_category": documents[0].get("category") if documents else None,
                },
            )
        body = response.json() if response.content else {}
        return int(body.get("synced", len(documents)))

    async def delete_command_documents(
        self,
        tenant_id: int,
        external_ids: List[str],
        user_id: Optional[str] = None,
        auth_token: Optional[str] = None,
    ) -> int:
        if not external_ids:
            return 0

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}{self.command_delete_path}",
                headers=self._headers(tenant_id, user_id, auth_token),
                json={"externalIds": external_ids},
            )
            self._raise_for_status_with_body(
                response,
                "delete_command_documents",
                {
                    "tenant_id": tenant_id,
                    "external_id_count": len(external_ids),
                    "first_external_id": external_ids[0] if external_ids else None,
                },
            )
        body = response.json() if response.content else {}
        return int(body.get("deleted", len(external_ids)))

    async def has_command_source(
        self,
        tenant_id: int,
        source_name: str,
        user_id: Optional[str] = None,
        auth_token: Optional[str] = None,
    ) -> bool:
        response = await self.search_commands(
            query="Command",
            tenant_id=tenant_id,
            top_k=1,
            source_types=["command"],
            source_names=[source_name],
            user_id=user_id,
            auth_token=auth_token,
        )
        results = response.get("results", []) or []
        return len(results) > 0
