"""Tenant-scoped storage for probe results, bound to provider configuration."""

import hashlib
from datetime import datetime, timedelta, timezone


def _key(tenant_id, provider_id, fingerprint):
    fields = (str(tenant_id), str(provider_id), str(fingerprint))
    encoded = b"".join(len(value.encode()).to_bytes(4, "big") + value.encode() for value in fields)
    return hashlib.sha256(encoded).hexdigest()


class ThinkingCapabilityStore:
    def __init__(self, collection):
        self.collection = collection

    async def begin(self, tenant_id, provider_id, fingerprint, task_id):
        if not tenant_id or not provider_id or not fingerprint or not task_id:
            raise ValueError("Tenant, provider, fingerprint and task are required")
        await self.collection.replace_one({"_id": _key(tenant_id, provider_id, fingerprint)}, {
            "tenant_id": str(tenant_id), "provider_id": provider_id, "provider_fingerprint": fingerprint,
            "task_id": task_id, "status": "discovering", "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
        }, upsert=True)

    async def save(self, tenant_id, provider_id, fingerprint, task_id, record):
        if not tenant_id or not provider_id or not fingerprint or not task_id:
            raise ValueError("Tenant, provider, fingerprint and task are required")
        document = dict(record)
        document.update({"tenant_id": str(tenant_id), "provider_id": provider_id,
                         "provider_fingerprint": fingerprint, "task_id": task_id})
        result = await self.collection.replace_one({"_id": _key(tenant_id, provider_id, fingerprint),
            "task_id": task_id, "status": "discovering"}, document, upsert=False)
        return result.matched_count == 1

    async def read(self, tenant_id, provider_id, fingerprint, now=None):
        if not tenant_id or not provider_id or not fingerprint:
            return None
        record = await self.collection.find_one({"_id": _key(tenant_id, provider_id, fingerprint),
            "tenant_id": str(tenant_id), "provider_id": provider_id, "provider_fingerprint": fingerprint})
        if not record or (record.get("status") != "http_accepted" and not (
                record.get("schema_version") == 2 and record.get("status") == "indeterminate")):
            return None
        expires_at = record.get("expires_at")
        if not isinstance(expires_at, datetime):
            return None
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= (now or datetime.now(timezone.utc)):
            return None
        return {key: value for key, value in record.items() if key != "_id"}
