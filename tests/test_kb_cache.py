import pytest
import asyncio
import time
from unittest.mock import AsyncMock, patch
from src.services.kb_cache import KBCache, KBCacheConfig


class TestKBCache:
    """Test Knowledge Base Response Caching"""

    @pytest.mark.asyncio
    async def test_kb_cache_initialization(self):
        """RED: Test KBCache initializes with config"""
        config = KBCacheConfig(
            max_size=100,
            ttl_seconds=300,
            enabled=True
        )

        cache = KBCache(config=config)

        assert cache.max_size == 100
        assert cache.ttl_seconds == 300
        assert cache.enabled is True

    @pytest.mark.asyncio
    async def test_kb_cache_search_hit(self):
        """RED: Test cache hit on kb_search"""
        config = KBCacheConfig(enabled=True)
        mock_client = AsyncMock()
        mock_client.kb_search = AsyncMock(return_value=[{"id": "doc1", "title": "Test"}])

        cache = KBCache(config=config, kb_client=mock_client)

        # First call - hits API
        result1 = await cache.kb_search("test query")

        # Second call - should hit cache
        result2 = await cache.kb_search("test query")

        # Verify same result
        assert result1 == result2
        # Verify API called only once
        assert mock_client.kb_search.call_count == 1

    @pytest.mark.asyncio
    async def test_kb_cache_semantic_search_hit(self):
        """RED: Test cache hit on semantic search"""
        config = KBCacheConfig(enabled=True)
        mock_client = AsyncMock()
        mock_client.kb_semantic_search = AsyncMock(return_value=[{"id": "doc2", "similarity_score": 0.95}])

        cache = KBCache(config=config, kb_client=mock_client)

        result1 = await cache.kb_semantic_search("How to approve?")
        result2 = await cache.kb_semantic_search("How to approve?")

        assert result1 == result2
        assert mock_client.kb_semantic_search.call_count == 1

    @pytest.mark.asyncio
    async def test_kb_cache_ttl_expiration(self):
        """RED: Test cache entry expires after TTL"""
        config = KBCacheConfig(enabled=True, ttl_seconds=1)
        mock_client = AsyncMock()
        mock_client.kb_search = AsyncMock(return_value=[{"id": "doc1"}])

        cache = KBCache(config=config, kb_client=mock_client)

        # First call
        await cache.kb_search("test")

        # Wait for TTL to expire
        await asyncio.sleep(1.1)

        # Second call - should miss cache
        await cache.kb_search("test")

        # Verify API called twice
        assert mock_client.kb_search.call_count == 2

    @pytest.mark.asyncio
    async def test_kb_cache_disabled(self):
        """RED: Test cache can be disabled"""
        config = KBCacheConfig(enabled=False)
        mock_client = AsyncMock()
        mock_client.kb_search = AsyncMock(return_value=[{"id": "doc1"}])

        cache = KBCache(config=config, kb_client=mock_client)

        # When cache is disabled, raises ValueError (expected behavior)
        with pytest.raises(ValueError):
            await cache.kb_search("test")
