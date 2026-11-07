from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.llm.thinking_capability_store import ThinkingCapabilityStore


class MemoryCollection:
    def __init__(self):
        self.data = {}

    async def replace_one(self, query, document, upsert):
        current = self.data.get(query["_id"])
        matched = bool(current and all(current.get(k) == v for k, v in query.items()))
        if matched or upsert:
            self.data[query["_id"]] = {"_id": query["_id"], **document}
        return SimpleNamespace(matched_count=int(matched))

    async def find_one(self, query):
        result = self.data.get(query["_id"])
        return result if result and all(result.get(k) == v for k, v in query.items()) else None

    async def delete_one(self, query):
        if await self.find_one(query):
            self.data.pop(query["_id"])


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_only_current_tenant_provider_fingerprint_and_fresh_record_are_read():
    store = ThinkingCapabilityStore(MemoryCollection())
    now = datetime.now(timezone.utc)
    await store.begin("1", "p", "fingerprint-a", "task")
    await store.save("1", "p", "fingerprint-a", "task", {"status": "http_accepted", "expires_at": now + timedelta(hours=1), "modes": ["default", "low"]})
    assert (await store.read("1", "p", "fingerprint-a", now))["modes"] == ["default", "low"]
    assert await store.read("2", "p", "fingerprint-a", now) is None
    assert await store.read("1", "other", "fingerprint-a", now) is None
    assert await store.read("1", "p", "fingerprint-b", now) is None
    assert await store.read("1", "p", "fingerprint-a", now + timedelta(hours=1)) is None


@pytest.mark.anyio
async def test_unverified_or_missing_expiry_never_reused():
    store = ThinkingCapabilityStore(MemoryCollection())
    await store.begin("1", "p", "fp", "task-1")
    await store.save("1", "p", "fp", "task-1", {"status": "indeterminate"})
    assert await store.read("1", "p", "fp") is None
    await store.begin("1", "p", "fp", "task-2")
    await store.save("1", "p", "fp", "task-2", {"status": "http_accepted"})
    assert await store.read("1", "p", "fp") is None


@pytest.mark.anyio
async def test_concurrent_tasks_cannot_overwrite_new_configuration_or_newer_task():
    store = ThinkingCapabilityStore(MemoryCollection())
    now = datetime.now(timezone.utc)
    old = {"status": "http_accepted", "expires_at": now + timedelta(hours=1), "modes": ["default", "low"]}
    new = {"status": "http_accepted", "expires_at": now + timedelta(hours=1), "modes": ["default", "high"]}
    await store.begin("1", "p", "old-fp", "old-task")
    await store.begin("1", "p", "new-fp", "new-task")
    assert await store.save("1", "p", "new-fp", "new-task", new)
    assert await store.save("1", "p", "old-fp", "old-task", old)
    assert (await store.read("1", "p", "new-fp", now))["modes"] == ["default", "high"]
    await store.begin("1", "p", "new-fp", "first")
    await store.begin("1", "p", "new-fp", "second")
    assert not await store.save("1", "p", "new-fp", "first", old)
    assert await store.read("1", "p", "new-fp", now) is None
    assert await store.save("1", "p", "new-fp", "second", new)
    assert (await store.read("1", "p", "new-fp", now))["modes"] == ["default", "high"]
