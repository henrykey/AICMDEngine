import logging
from typing import List, Dict, Any, Optional

from src.llm.provider_manager import LLMProviderManager

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Capability-aware embedding generation using the shared LLM provider manager."""

    def __init__(self, provider_manager: LLMProviderManager, embedding_dimensions: Optional[int] = None):
        self.provider_manager = provider_manager
        self.embedding_dimensions = embedding_dimensions

    def _select_provider_name(self) -> str:
        provider_name = self.provider_manager.select_provider_by_capabilities(
            required_capabilities=["embedding"],
            embedding_dimensions=self.embedding_dimensions
        )
        if not provider_name:
            raise ValueError("No embedding-capable provider available")
        return provider_name

    def get_embedding_metadata(self) -> Dict[str, Any]:
        provider_name = self._select_provider_name()
        provider = self.provider_manager.get_provider(provider_name)
        if not provider:
            raise ValueError(f"Embedding provider '{provider_name}' not found")

        return {
            "provider": provider_name,
            "model": provider.model,
            "dimensions": provider.embedding_dimensions,
        }

    async def embed_text(self, text: str) -> List[float]:
        embeddings = await self.embed_texts([text])
        return embeddings[0]

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        provider_name = self._select_provider_name()
        provider = self.provider_manager.get_provider(provider_name)
        client = self.provider_manager.get_client(provider_name)

        if not provider or not client:
            raise ValueError(f"Embedding provider '{provider_name}' is not initialized")

        logger.info(
            "Generating embeddings with provider='%s', model='%s', count=%s",
            provider_name,
            provider.model,
            len(texts)
        )

        response = await client.embeddings.create(
            model=provider.model,
            input=texts,
            timeout=provider.timeout,
        )

        embeddings = [item.embedding for item in response.data]
        if self.embedding_dimensions is not None:
            for embedding in embeddings:
                if len(embedding) != self.embedding_dimensions:
                    raise ValueError(
                        f"Embedding dimension mismatch: expected {self.embedding_dimensions}, got {len(embedding)}"
                    )

        return embeddings
