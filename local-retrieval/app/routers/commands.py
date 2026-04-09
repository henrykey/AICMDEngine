from fastapi import APIRouter, Header, Request

from app.models import (
    CommandCorpusDeleteRequest,
    CommandCorpusSyncRequest,
    CommandSearchRequest,
    CommandSearchResponse,
)

router = APIRouter()


@router.post("/v2/documents/commands/sync/batch")
async def sync_command_corpus_batch(
    payload: CommandCorpusSyncRequest,
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    retrieval_service = request.app.state.retrieval_service
    document_ids = retrieval_service.upsert_many(payload.documents, x_tenant_id)
    return {
        "synced": len(document_ids),
        "tenantId": x_tenant_id,
        "documentIds": document_ids,
    }


@router.post("/v2/documents/commands/delete")
async def delete_command_corpus_by_external_ids(
    payload: CommandCorpusDeleteRequest,
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    retrieval_service = request.app.state.retrieval_service
    deleted = retrieval_service.delete_many(payload.external_ids, x_tenant_id)
    return {
        "deleted": deleted,
        "tenantId": x_tenant_id,
        "externalIds": payload.external_ids,
    }


@router.post("/v2/documents/search/commands", response_model=CommandSearchResponse)
async def search_commands(
    payload: CommandSearchRequest,
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    retrieval_service = request.app.state.retrieval_service
    results = retrieval_service.search(
        tenant_id=x_tenant_id,
        query=payload.query,
        top_k=payload.top_k,
        source_types=payload.source_types,
        source_names=payload.source_names,
        categories=payload.categories,
        entity_type=payload.entity_type,
    )
    return CommandSearchResponse(results=results, total=len(results))
