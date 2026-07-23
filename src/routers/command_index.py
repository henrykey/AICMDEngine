from fastapi import APIRouter, HTTPException, Request
import logging
from src.utils.request_auth import extract_bearer_token, extract_user_id

logger = logging.getLogger(__name__)

router = APIRouter()


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
    docintel_status = _get_docintel_status(request)
    return {
        "docintel_enabled": docintel_status["enabled"],
        "docintel": docintel_status,
    }


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
