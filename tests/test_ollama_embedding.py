"""
Test script for fetching embeddings from a local Ollama instance.

Usage:
    python tests/test_ollama_embedding.py
    python tests/test_ollama_embedding.py --text "hello world"
    OLLAMA_BASE_URL=http://localhost:11434 python tests/test_ollama_embedding.py

Optional pytest run:
    pytest tests/test_ollama_embedding.py -v -s
"""

import argparse
import asyncio
import os
import time
from typing import List

import httpx
import pytest


DEFAULT_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
DEFAULT_MODEL = os.getenv("OLLAMA_EMBEDDING_MODEL", "qwen3-embedding")
DEFAULT_TEXT = os.getenv("OLLAMA_EMBEDDING_TEXT", "这是一个用于测试 embedding 的字符串。")
DEFAULT_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "60"))
DEFAULT_EXPECTED_DIMENSIONS = os.getenv("OLLAMA_EMBEDDING_DIMENSIONS")


async def fetch_embedding(
    text: str,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = DEFAULT_TIMEOUT,
    dimensions: int | None = None,
) -> List[float]:
    url = f"{base_url.rstrip('/')}/api/embed"
    payload = {
        "model": model,
        "input": text,
    }
    if dimensions is not None:
        payload["dimensions"] = dimensions

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()

    embeddings = data.get("embeddings") or []
    if not embeddings:
        raise ValueError(f"Ollama returned no embeddings: {data}")

    embedding = embeddings[0]
    if not isinstance(embedding, list) or not embedding:
        raise ValueError(f"Invalid embedding payload: {data}")

    return embedding


def summarize_embedding(embedding: List[float]) -> str:
    preview = ", ".join(f"{value:.6f}" for value in embedding[:8])
    min_value = min(embedding)
    max_value = max(embedding)
    return (
        f"dimension={len(embedding)}\n"
        f"min={min_value:.6f}\n"
        f"max={max_value:.6f}\n"
        f"preview=[{preview}]"
    )


@pytest.mark.asyncio
async def test_ollama_embedding():
    embedding = await fetch_embedding(DEFAULT_TEXT)

    assert isinstance(embedding, list)
    assert len(embedding) > 0
    assert all(isinstance(value, (int, float)) for value in embedding)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch a text embedding from local Ollama.")
    parser.add_argument(
        "--text",
        default=DEFAULT_TEXT,
        help="Text to embed. Defaults to OLLAMA_EMBEDDING_TEXT or a built-in sample.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="Embedding model name. Defaults to OLLAMA_EMBEDDING_MODEL or qwen3-embedding.",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="Ollama base URL. Defaults to OLLAMA_BASE_URL or http://localhost:11434.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="Request timeout in seconds. Defaults to OLLAMA_TIMEOUT_SECONDS or 60.",
    )
    parser.add_argument(
        "--dimensions",
        type=int,
        default=int(DEFAULT_EXPECTED_DIMENSIONS) if DEFAULT_EXPECTED_DIMENSIONS else None,
        help="Expected embedding dimensions. Also sent to Ollama when provided.",
    )
    args = parser.parse_args()

    started_at = time.perf_counter()
    embedding = await fetch_embedding(
        text=args.text,
        model=args.model,
        base_url=args.base_url,
        timeout=args.timeout,
        dimensions=args.dimensions,
    )
    elapsed_ms = (time.perf_counter() - started_at) * 1000

    if args.dimensions is not None and len(embedding) != args.dimensions:
        raise ValueError(
            f"Embedding dimension mismatch: expected {args.dimensions}, got {len(embedding)}"
        )

    print(f"base_url={args.base_url}")
    print(f"model={args.model}")
    print(f"text={args.text}")
    print(f"elapsed_ms={elapsed_ms:.2f}")
    if args.dimensions is not None:
        print(f"expected_dimensions={args.dimensions}")
    print(summarize_embedding(embedding))


if __name__ == "__main__":
    asyncio.run(main())
