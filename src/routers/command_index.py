from fastapi import APIRouter, HTTPException, Request
import logging
import httpx
from src.utils.request_auth import extract_bearer_token, extract_user_id

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_indexer(request: Request):
    indexer = getattr(request.app, "command_indexer", None)
    if not indexer:
        raise HTTPException(status_code=503, detail="Command indexer not initialized")
    return indexer


async def _get_local_retrieval_status(request: Request):
    client = getattr(request.app, "local_retrieval_client", None)
    if not client:
        return {
            "enabled": False,
            "reason": "Local retrieval client is not initialized",
        }
    try:
        async with httpx.AsyncClient(timeout=max(client.timeout, 1.0)) as http_client:
            response = await http_client.get(
                f"{client.base_url}/v1/status",
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
        body = response.json()
        body["enabled"] = True
        return body
    except Exception as e:
        logger.warning("Failed to get local retrieval status: %s", e)
        return {
            "enabled": False,
            "reason": str(e),
        }


def _get_docintel_status(request: Request):
    client = getattr(request.app, "docintel_client", None)
    if not client:
        return {
            "enabled": False,
            "base_url": "",
        }
    return {
        "enabled": True,
        "base_url": client.base_url,
    }


def _get_docintel_sync(request: Request):
    sync_service = getattr(request.app, "docintel_command_sync", None)
    if not sync_service:
        raise HTTPException(status_code=503, detail="DocIntel command sync is not initialized")
    return sync_service


@router.get("/status")
async def get_command_index_status(request: Request):
    indexer = getattr(request.app, "command_indexer", None)
    local_retrieval_status = await _get_local_retrieval_status(request)
    docintel_status = _get_docintel_status(request)
    if not indexer:
        return {
            "exists": False,
            "index_name": "",
            "command_docs": 0,
            "mcp_tool_docs": 0,
            "total_docs": 0,
            "index_version": "disabled",
            "enabled": False,
            "reason": "Local ES command indexer is not initialized",
            "docintel_enabled": docintel_status["enabled"],
            "docintel": docintel_status,
            "local_retrieval": local_retrieval_status,
        }
    try:
        body = await indexer.get_index_status()
        body["docintel_enabled"] = docintel_status["enabled"]
        body["docintel"] = docintel_status
        body["local_retrieval"] = local_retrieval_status
        return body
    except Exception as e:
        logger.error("Failed to get command index status: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rebuild")
async def rebuild_command_index(request: Request):
    indexer = _get_indexer(request)
    try:
        deleted = await indexer.delete_by_source(source_type="command")
        rebuilt = await indexer.rebuild_from_mongo()
        return {
            "status": "ok",
            "deleted_command_docs": deleted,
            "rebuilt_command_docs": rebuilt,
        }
    except Exception as e:
        logger.error("Failed to rebuild command index: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/refresh-mcp")
async def refresh_mcp_command_index(request: Request):
    indexer = _get_indexer(request)
    mcp_registry = getattr(request.app, "mcp_registry", None)
    if not mcp_registry:
        raise HTTPException(status_code=503, detail="MCP registry not initialized")

    try:
        deleted = await indexer.delete_by_source(source_type="mcp_tool")
        indexed = await indexer.upsert_mcp_tools(mcp_registry)
        return {
            "status": "ok",
            "deleted_mcp_docs": deleted,
            "indexed_mcp_docs": indexed,
        }
    except Exception as e:
        logger.error("Failed to refresh MCP command index: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync-mcp-docintel")
async def sync_mcp_tools_to_docintel(request: Request):
    sync_service = _get_docintel_sync(request)
    mcp_registry = getattr(request.app, "mcp_registry", None)
    if not mcp_registry:
        raise HTTPException(status_code=503, detail="MCP registry not initialized")

    auth_token = extract_bearer_token(request)
    if not auth_token:
        raise HTTPException(status_code=401, detail="Bearer token is required")
    user_id = extract_user_id(request, auth_token)
    tenant_header = request.headers.get("X-Tenant-ID")
    try:
        tenant_id = int(tenant_header) if tenant_header else 0
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid X-Tenant-ID header")

    try:
        synced = await sync_service.sync_mcp_tools(
            mcp_registry,
            tenant_id=tenant_id,
            user_id=user_id,
            auth_token=auth_token,
        )
        return {
            "status": "ok",
            "tenant_id": tenant_id,
            "user_id": user_id,
            "synced_mcp_docs": synced,
        }
    except Exception as e:
        logger.error("Failed to sync MCP tools to DocIntel: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
