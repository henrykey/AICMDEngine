"""
Knowledge Base Response Caching Layer

Caches KB search results to reduce API calls with configurable:
- Max cache size
- TTL per entry
- Enable/disable toggle
"""

import time
import hashlib
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import logging

from src.services.kb_client import KBClient

logger = logging.getLogger(__name__)


@dataclass
class KBCacheConfig:
    """KB cache configuration"""
    max_size: int = 100
    ttl_seconds: int = 300  # 5 minutes
    enabled: bool = True


class KBCache:
    """Caching wrapper for KB client"""

    def __init__(self, config: KBCacheConfig, kb_client: Optional[KBClient] = None):
        """Initialize cache"""
        self.config = config
        self.kb_client = kb_client
        self.max_size = config.max_size
        self.ttl_seconds = config.ttl_seconds
        self.enabled = config.enabled
        self._cache: Dict[str, tuple] = {}  # key -> (value, timestamp)

    def _make_key(self, prefix: str, **kwargs) -> str:
        """Create cache key from parameters"""
        key_str = prefix + ":" + "|".join(
            f"{k}={v}" for k, v in sorted(kwargs.items())
        )
        return hashlib.md5(key_str.encode()).hexdigest()

    def _is_expired(self, timestamp: float) -> bool:
        """Check if cache entry is expired"""
        return (time.time() - timestamp) > self.ttl_seconds

    async def kb_search(
        self,
        query: str,
        limit: int = 10,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Cached kb_search"""
        if not self.enabled or not self.kb_client:
            raise ValueError("Cache disabled or kb_client not set")

        key = self._make_key("search", query=query, limit=limit, offset=offset)

        # Check cache
        if key in self._cache:
            value, timestamp = self._cache[key]
            if not self._is_expired(timestamp):
                logger.debug(f"KB cache hit: {key}")
                return value

        # Cache miss - fetch from KB
        logger.debug(f"KB cache miss: {key}")
        result = await self.kb_client.kb_search(query, limit, offset)

        # Store in cache
        if len(self._cache) >= self.max_size:
            # Simple eviction: remove oldest entry
            oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][1])
            del self._cache[oldest_key]

        self._cache[key] = (result, time.time())
        return result

    async def kb_semantic_search(
        self,
        query: str,
        similarity_threshold: float = 0.7,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Cached kb_semantic_search"""
        if not self.enabled or not self.kb_client:
            raise ValueError("Cache disabled or kb_client not set")

        key = self._make_key(
            "semantic",
            query=query,
            threshold=similarity_threshold,
            limit=limit
        )

        if key in self._cache:
            value, timestamp = self._cache[key]
            if not self._is_expired(timestamp):
                logger.debug(f"KB cache hit: {key}")
                return value

        logger.debug(f"KB cache miss: {key}")
        result = await self.kb_client.kb_semantic_search(
            query,
            similarity_threshold,
            limit
        )

        if len(self._cache) >= self.max_size:
            oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][1])
            del self._cache[oldest_key]

        self._cache[key] = (result, time.time())
        return result

    async def kb_rag_query(
        self,
        question: str,
        context: Optional[str] = None
    ) -> Dict[str, Any]:
        """Cached kb_rag_query"""
        if not self.enabled or not self.kb_client:
            raise ValueError("Cache disabled or kb_client not set")

        key = self._make_key("rag", question=question, context=context or "")

        if key in self._cache:
            value, timestamp = self._cache[key]
            if not self._is_expired(timestamp):
                logger.debug(f"KB cache hit: {key}")
                return value

        logger.debug(f"KB cache miss: {key}")
        result = await self.kb_client.kb_rag_query(question, context)

        if len(self._cache) >= self.max_size:
            oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][1])
            del self._cache[oldest_key]

        self._cache[key] = (result, time.time())
        return result

    def clear(self):
        """Clear all cached entries"""
        self._cache.clear()
        logger.info("KB cache cleared")
