from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health(request: Request):
    stats = request.app.state.retrieval_service.stats()
    return {"status": "ok", "service": "local-retrieval", **stats}


@router.get("/v1/status")
async def status(request: Request):
    stats = request.app.state.retrieval_service.stats()
    return {
        "enabled": True,
        "backend": "sqlite_fts5_faiss_hybrid" if stats.get("vector_enabled") else "sqlite_fts5",
        **stats,
    }
