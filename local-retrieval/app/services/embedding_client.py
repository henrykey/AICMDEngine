from __future__ import annotations

import logging
from typing import List

import httpx


logger = logging.getLogger(__name__)


class OllamaEmbeddingClient:
    def __init__(self, base_url: str, model: str, timeout_ms: int = 15000) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout_ms / 1000.0

    def embed_text(self, text: str) -> List[float]:
        payload = {
            "model": self.model,
            "input": text,
        }
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(f"{self.base_url}/api/embed", json=payload)
            response.raise_for_status()
            data = response.json()

        embeddings = data.get("embeddings") or []
        if not embeddings or not isinstance(embeddings, list):
            raise ValueError("Ollama embedding response did not contain embeddings")
        vector = embeddings[0]
        if not isinstance(vector, list) or not vector:
            raise ValueError("Ollama embedding response did not contain a valid embedding vector")
        return [float(value) for value in vector]

    def healthcheck(self) -> bool:
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
            return True
        except Exception as exc:
            logger.warning("Ollama embedding healthcheck failed: %s", exc)
            return False
