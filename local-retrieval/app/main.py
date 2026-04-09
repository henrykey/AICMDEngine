import logging

from fastapi import FastAPI

from app.config import settings
from app.routers import admin, commands
from app.services.embedding_client import OllamaEmbeddingClient
from app.services.retrieval_service import RetrievalService
from app.services.store import SQLiteCommandStore
from app.services.vector_store import FaissVectorStore


logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

app = FastAPI(
    title="Local Retrieval Service",
    description="DocIntel-compatible local command corpus retrieval service",
    version="0.1.0",
)


@app.on_event("startup")
async def startup() -> None:
    keyword_store = SQLiteCommandStore(settings.sqlite_db_path)
    vector_store = None
    embedding_client = None

    if settings.vector_search_enabled:
        try:
            embedding_client = OllamaEmbeddingClient(
                base_url=settings.ollama_base_url,
                model=settings.ollama_embedding_model,
                timeout_ms=settings.ollama_timeout_ms,
            )
            vector_store = FaissVectorStore(settings.sqlite_db_path)
        except Exception as exc:
            logging.getLogger(__name__).warning("Failed to initialize vector search: %s", exc)

    app.state.command_store = keyword_store
    app.state.retrieval_service = RetrievalService(
        keyword_store=keyword_store,
        vector_store=vector_store,
        embedding_client=embedding_client,
        keyword_score_weight=settings.keyword_score_weight,
        vector_score_weight=settings.vector_score_weight,
    )


app.include_router(admin.router)
app.include_router(commands.router)
