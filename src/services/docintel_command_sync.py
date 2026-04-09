from typing import Any, Dict, List

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.services.command_document_builder import CommandDocumentBuilder
from src.services.docintel_client import DocIntelClient


class DocIntelCommandSyncService:
    """Sync commands and MCP tools into Membership DocIntel."""

    def __init__(
        self,
        client: DocIntelClient,
        db: AsyncIOMotorDatabase,
        category_prefix: str = "cmdengine.command",
        default_user_id: str = "system",
    ):
        self.client = client
        self.db = db
        self.category_prefix = category_prefix
        self.default_user_id = default_user_id
        self.document_builder = CommandDocumentBuilder()

    def _resolve_user_id(
        self,
        user_id: str | None = None,
        auth_token: str | None = None,
    ) -> str | None:
        if user_id:
            return user_id
        # For user-triggered requests with bearer auth, omit X-User-ID if
        # we could not extract a numeric user id. Membership Docs accepts the
        # header as optional Long and will reject non-numeric values such as
        # "system" during argument binding.
        if auth_token:
            return None
        if self.default_user_id and str(self.default_user_id).isdigit():
            return str(self.default_user_id)
        return None

    async def sync_command(self, command_doc: Dict[str, Any], source_name: str) -> int:
        return await self.sync_command_with_auth(command_doc, source_name)

    async def sync_command_with_auth(
        self,
        command_doc: Dict[str, Any],
        source_name: str,
        user_id: str | None = None,
        auth_token: str | None = None,
    ) -> int:
        tenant_id = int(command_doc.get("tenant_id", 0))
        payload = self.document_builder.build_docintel_document_from_command(
            command_doc=command_doc,
            source_name=source_name,
            category_prefix=self.category_prefix,
        )
        return await self.client.bulk_upsert_command_documents(
            tenant_id,
            [payload],
            user_id=self._resolve_user_id(user_id, auth_token),
            auth_token=auth_token,
        )

    async def sync_commands(self, command_docs: List[Dict[str, Any]], source_name: str) -> int:
        return await self.sync_commands_with_auth(command_docs, source_name)

    async def sync_commands_with_auth(
        self,
        command_docs: List[Dict[str, Any]],
        source_name: str,
        user_id: str | None = None,
        auth_token: str | None = None,
    ) -> int:
        if not command_docs:
            return 0
        tenant_id = int(command_docs[0].get("tenant_id", 0))
        payloads = [
            self.document_builder.build_docintel_document_from_command(
                command_doc=command_doc,
                source_name=source_name,
                category_prefix=self.category_prefix,
            )
            for command_doc in command_docs
        ]
        return await self.client.bulk_upsert_command_documents(
            tenant_id,
            payloads,
            user_id=self._resolve_user_id(user_id, auth_token),
            auth_token=auth_token,
        )

    async def sync_mcp_tools(self, mcp_registry: Any, tenant_id: int = 0) -> int:
        if not mcp_registry:
            return 0
        payloads = []
        for mcp in mcp_registry.get_all_mcps():
            tools_info = mcp.get_info()
            for tool_info in tools_info.get("tools", []):
                payloads.append(
                    self.document_builder.build_docintel_document_from_mcp_tool(
                        mcp_name=mcp.name,
                        tool_info=tool_info,
                        category_prefix=self.category_prefix,
                        tenant_id=tenant_id,
                    )
                )
        return await self.client.bulk_upsert_command_documents(
            tenant_id,
            payloads,
            user_id=self._resolve_user_id(),
        )

    async def delete_commands(self, tenant_id: int, external_ids: List[str]) -> int:
        return await self.delete_commands_with_auth(tenant_id, external_ids)

    async def delete_commands_with_auth(
        self,
        tenant_id: int,
        external_ids: List[str],
        user_id: str | None = None,
        auth_token: str | None = None,
    ) -> int:
        return await self.client.delete_command_documents(
            tenant_id,
            external_ids,
            user_id=self._resolve_user_id(user_id, auth_token),
            auth_token=auth_token,
        )

    async def delete_command_set(self, set_id: str, tenant_id: int) -> int:
        return await self.delete_command_set_with_auth(set_id, tenant_id)

    async def delete_command_set_with_auth(
        self,
        set_id: str,
        tenant_id: int,
        user_id: str | None = None,
        auth_token: str | None = None,
    ) -> int:
        cursor = self.db["commands"].find({"command_set_id": set_id, "tenant_id": tenant_id})
        docs = [doc async for doc in cursor]
        external_ids = [
            self.document_builder.build_docintel_document_from_command(
                command_doc=doc,
                source_name="manual",
                category_prefix=self.category_prefix,
            )["externalId"]
            for doc in docs
        ]
        return await self.delete_commands_with_auth(
            tenant_id,
            external_ids,
            user_id=user_id,
            auth_token=auth_token,
        )

    async def rebuild_from_mongo(self) -> int:
        command_docs = [doc async for doc in self.db["commands"].find({})]
        if not command_docs:
            return 0

        source_names: Dict[str, str] = {}
        set_ids = list({str(doc.get("command_set_id")) for doc in command_docs if doc.get("command_set_id")})
        object_ids: List[ObjectId] = []
        for set_id in set_ids:
            try:
                object_ids.append(ObjectId(set_id))
            except Exception:
                continue

        if object_ids:
            async for command_set in self.db["command_sets"].find({"_id": {"$in": object_ids}}):
                source_names[str(command_set["_id"])] = command_set.get("name", "manual")

        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for command_doc in command_docs:
            source_name = source_names.get(str(command_doc.get("command_set_id")), "manual")
            grouped.setdefault(source_name, []).append(command_doc)

        synced = 0
        for source_name, docs in grouped.items():
            synced += await self.sync_commands(docs, source_name)
        return synced
