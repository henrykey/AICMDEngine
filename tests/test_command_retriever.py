from unittest.mock import AsyncMock

import pytest

from src.services.command_retriever import CommandRetriever


@pytest.mark.asyncio
async def test_retrieve_fails_when_docintel_is_not_configured():
  retriever = CommandRetriever(docintel_client=None)

  with pytest.raises(RuntimeError, match="DocIntel command retrieval is not configured"):
    await retriever.retrieve("list organizations", tenant_id=1)


@pytest.mark.asyncio
async def test_retrieve_fails_when_docintel_is_unavailable():
  client = AsyncMock()
  client.search_commands.side_effect = OSError("connection refused")
  retriever = CommandRetriever(docintel_client=client)

  with pytest.raises(RuntimeError, match="DocIntel command retrieval is unavailable"):
    await retriever.retrieve("list organizations", tenant_id=1)


@pytest.mark.asyncio
async def test_retrieve_rejects_removed_local_backend():
  retriever = CommandRetriever(docintel_client=AsyncMock())

  with pytest.raises(ValueError, match="Unsupported command retrieval backend: local_semantic"):
    await retriever.retrieve("list organizations", tenant_id=1, preferred_backend="local_semantic")
