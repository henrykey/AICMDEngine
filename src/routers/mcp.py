"""
MCP (Model Context Protocol) API endpoints.
"""

from fastapi import APIRouter, Request, HTTPException, Depends, Header
from typing import Dict, Any, List, Optional
from datetime import datetime
import hmac
import logging

from src.core.config import settings
from src.mcp.registry import MCPRegistry, ToolResult
from src.mcp.protocol_handler import choose_vlm_injection_key, get_tool_schema_properties

logger = logging.getLogger(__name__)

router = APIRouter()


def _require_mcp_admin_token(x_mcp_admin_token: Optional[str]) -> None:
    expected = settings.mcp_admin_token
    if not expected:
        if settings.environment.lower() in {"development", "test"}:
            return
        raise HTTPException(
            status_code=503,
            detail="MCP_ADMIN_TOKEN must be configured before runtime refresh is enabled",
        )
    if not x_mcp_admin_token or not hmac.compare_digest(x_mcp_admin_token, expected):
        raise HTTPException(status_code=403, detail="Invalid MCP admin token")


async def _load_mcp_provider_settings(request: Request) -> Dict[str, Dict[str, str]]:
    db = getattr(request.app, "mongodb", None)
    if db is None:
        return {}
    try:
        docs = await db.mcp_server_settings.find(
            {},
            {"server_name": 1, "llm_provider": 1, "glm_ocr_provider": 1},
        ).to_list(length=1000)
        settings: Dict[str, Dict[str, str]] = {}
        for doc in docs:
            server_name = doc.get("server_name")
            if not server_name:
                continue
            item: Dict[str, str] = {}
            if doc.get("llm_provider"):
                item["llm_provider"] = str(doc.get("llm_provider"))
            if doc.get("glm_ocr_provider"):
                item["glm_ocr_provider"] = str(doc.get("glm_ocr_provider"))
            settings[str(server_name)] = item
        return settings
    except Exception as exc:
        logger.warning(f"Failed to load mcp_server_settings: {exc}")
        return {}


async def _load_mcp_llm_map(request: Request) -> Dict[str, str]:
    settings = await _load_mcp_provider_settings(request)
    return {
        server_name: item["llm_provider"]
        for server_name, item in settings.items()
        if item.get("llm_provider")
    }


def _fallback_llm_provider_from_external_config(mcp: Any) -> Optional[str]:
    cfg = getattr(mcp, "external_config", {}) or {}
    provider = cfg.get("llm_provider") or cfg.get("vlm")
    if provider:
        return str(provider)
    return None


def _fallback_glm_ocr_provider_from_external_config(mcp: Any) -> Optional[str]:
    cfg = getattr(mcp, "external_config", {}) or {}
    provider = cfg.get("glm_ocr_provider") or cfg.get("ocr_provider")
    if not provider and isinstance(cfg.get("glm_ocr"), dict):
        provider = cfg["glm_ocr"].get("provider")
    if provider:
        return str(provider)
    return None


def _build_vlm_config_from_provider(request: Request, provider_name: str) -> Optional[Dict[str, Any]]:
    manager = getattr(request.app, "provider_manager", None)
    if manager is None:
        return None
    provider = manager.get_provider(provider_name)
    if not provider:
        return None
    api_key = manager.config_loader.get_api_key(provider.api_key_ref) or ""
    return {
        "provider": provider.name,
        "model": provider.model,
        "base_url": provider.base_url,
        "api_key": api_key,
        "timeout_sec": provider.timeout,
        "temperature": provider.temperature,
        "max_tokens": provider.max_tokens,
        "context_window": getattr(provider, "context_window", 4096),
        "dual_output_max_tokens": getattr(provider, "dual_output_max_tokens", 4096),
    }


def _build_glm_ocr_config_from_provider(request: Request, provider_name: str) -> Optional[Dict[str, Any]]:
    cfg = _build_vlm_config_from_provider(request, provider_name)
    if not cfg:
        return None
    cfg["enabled"] = True
    return {"glm_ocr": cfg}

@router.get("/servers")
async def list_mcp_servers(request: Request) -> Dict[str, Any]:
    """
    List all registered MCP servers.
    """
    registry = getattr(request.app, 'mcp_registry', None)
    if not registry:
        raise HTTPException(status_code=503, detail="MCP Registry not initialized")

    provider_settings = await _load_mcp_provider_settings(request)
    servers_info = []
    for mcp in registry.get_all_mcps():
        try:
            # Get server information
            mcp_info = mcp.get_info()
            tools_count = len(mcp_info.get('tools', {}))

            # Determine server status (simplified - real implementation would check actual server status)
            status = "running" if mcp.is_initialized else "stopped"
            health_score = 85 if status == "running" else 40

            # Get last heartbeat time
            last_heartbeat = getattr(mcp, 'last_heartbeat', datetime.now())
            if isinstance(last_heartbeat, str):
                last_heartbeat = datetime.fromisoformat(last_heartbeat.replace('Z', '+00:00'))

            # Count commands (from tools)
            commands_count = tools_count

            server_info = {
                "_id": str(hash(mcp.name)),  # Mock ID for UI
                "name": mcp.name,
                "type": "builtin" if hasattr(mcp, 'is_builtin') and mcp.is_builtin else "custom",
                "endpoint": getattr(mcp, 'endpoint', f'mcp://{mcp.name}'),
                "status": status,
                "health_score": health_score,
                "last_heartbeat": last_heartbeat.isoformat(),
                "tools_count": tools_count,
                "commands_count": commands_count,
                "tools": mcp_info.get('tools', []),
                "metadata": {
                    "description": getattr(mcp, 'description', f'MCP Server: {mcp.name}'),
                    "version": getattr(mcp, 'version', '1.0.0'),
                    "author": getattr(mcp, 'author', 'Unknown'),
                    "dependencies": getattr(mcp, 'dependencies', []),
                    "llm_provider": (provider_settings.get(mcp.name) or {}).get("llm_provider")
                    or _fallback_llm_provider_from_external_config(mcp),
                    "glm_ocr_provider": (provider_settings.get(mcp.name) or {}).get("glm_ocr_provider")
                    or _fallback_glm_ocr_provider_from_external_config(mcp),
                }
            }
            servers_info.append(server_info)

        except Exception as e:
            logger.error(f"Error getting info for MCP server {mcp.name}: {e}")
            # Add server with error status
            servers_info.append({
                "_id": str(hash(mcp.name)),
                "name": mcp.name,
                "type": "builtin" if hasattr(mcp, 'is_builtin') and mcp.is_builtin else "custom",
                "endpoint": getattr(mcp, 'endpoint', f'mcp://{mcp.name}'),
                "status": "error",
                "health_score": 0,
                "last_heartbeat": datetime.now().isoformat(),
                "tools_count": 0,
                "commands_count": 0,
                "metadata": {
                    "description": f"Error loading server: {str(e)}",
                    "version": "unknown",
                    "author": "Unknown",
                    "dependencies": []
                }
            })

    return {"servers": servers_info}

@router.get("/servers/{server_name}")
async def get_mcp_server(server_name: str, request: Request) -> Dict[str, Any]:
    """
    Get information about a specific MCP server.
    """
    registry = getattr(request.app, 'mcp_registry', None)
    if not registry:
        raise HTTPException(status_code=503, detail="MCP Registry not initialized")

    info = registry.get_mcp_info(server_name)
    if not info:
        raise HTTPException(status_code=404, detail=f"MCP server '{server_name}' not found")

    return info

@router.get("/servers/{server_name}/tools")
async def list_mcp_tools(server_name: str, request: Request) -> Dict[str, Any]:
    """
    List all tools available in a specific MCP server.
    """
    registry = getattr(request.app, 'mcp_registry', None)
    if not registry:
        raise HTTPException(status_code=503, detail="MCP Registry not initialized")

    mcp = registry.get_mcp(server_name)
    if not mcp:
        raise HTTPException(status_code=404, detail=f"MCP server '{server_name}' not found")

    return mcp.get_info()

@router.get("/servers/{server_name}/tools/{tool_name}")
async def get_mcp_tool_info(server_name: str, tool_name: str, request: Request) -> Dict[str, Any]:
    """
    Get information about a specific tool in an MCP server.
    """
    registry = getattr(request.app, 'mcp_registry', None)
    if not registry:
        raise HTTPException(status_code=503, detail="MCP Registry not initialized")

    tool_info = registry.get_tool_info(server_name, tool_name)
    if not tool_info:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found in server '{server_name}'")

    return tool_info

@router.post("/servers/{server_name}/tools/{tool_name}/execute")
async def execute_mcp_tool(
    server_name: str,
    tool_name: str,
    request: Request
) -> Dict[str, Any]:
    """
    Execute a tool from a specific MCP server.

    Args:
        server_name: Name of the MCP server
        tool_name: Name of the tool to execute

    Request Body:
        All tool parameters are passed as JSON.
        Optional "llm" key: specifies which LLM provider to use (e.g., "ChatGPT", "multmode")

    Examples:
        # Use default LLM selection
        {"question": "How to use membership?"}

        # Use specific LLM provider
        {"question": "How to use membership?", "llm": "ChatGPT"}
    """
    registry = getattr(request.app, 'mcp_registry', None)
    if not registry:
        raise HTTPException(status_code=503, detail="MCP Registry not initialized")

    # Read parameters from request body
    kwargs = await request.json()

    # Extract "llm" parameter if present
    llm_provider = kwargs.pop("llm", None)

    # Runtime model binding injection for external MCPs (REST path consistency with WS path).
    # Injection is schema-driven: only tools that declare these fields receive provider configs.
    properties = get_tool_schema_properties(registry, server_name, tool_name)
    vlm_key = choose_vlm_injection_key(properties, kwargs)
    if vlm_key:
        llm_map = await _load_mcp_llm_map(request)
        bound_provider = llm_map.get(server_name)
        if not bound_provider:
            mcp = registry.get_mcp(server_name)
            bound_provider = _fallback_llm_provider_from_external_config(mcp) if mcp else None
        if bound_provider:
            vlm_config = _build_vlm_config_from_provider(request, bound_provider)
            if vlm_config:
                kwargs[vlm_key] = vlm_config
        else:
            logger.info("[%s.%s] no MCP->LLM binding found; skip VLM injection", server_name, tool_name)

    if "ocr_config" in properties and "ocr_config" not in kwargs:
        provider_settings = await _load_mcp_provider_settings(request)
        bound_ocr_provider = (provider_settings.get(server_name) or {}).get("glm_ocr_provider")
        if not bound_ocr_provider:
            mcp = registry.get_mcp(server_name)
            bound_ocr_provider = _fallback_glm_ocr_provider_from_external_config(mcp) if mcp else None
        if bound_ocr_provider:
            ocr_config = _build_glm_ocr_config_from_provider(request, bound_ocr_provider)
            if ocr_config:
                kwargs["ocr_config"] = ocr_config
        else:
            logger.info("[%s.%s] no MCP->GLM-OCR binding found; skip OCR injection", server_name, tool_name)

    try:
        result = await registry.execute_command(
            mcp_name=server_name,
            tool_name=tool_name,
            llm_provider=llm_provider,
            **kwargs
        )
        # Transform ToolResult to MCP standard format
        # Java client expects: {"result": {"content": [{"type": "text", "text": "..."}]}}
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": result.content
                    }
                ]
            }
        }
    except Exception as e:
        # Return error in MCP format
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {
                "code": -32603,
                "message": str(e)
            }
        }


@router.get("/servers/{server_name}/llm-provider")
async def get_server_llm_provider(server_name: str, request: Request) -> Dict[str, Any]:
    registry = getattr(request.app, 'mcp_registry', None)
    if not registry:
        raise HTTPException(status_code=503, detail="MCP Registry not initialized")

    mcp = registry.get_mcp(server_name)
    if not mcp:
        raise HTTPException(status_code=404, detail=f"MCP server '{server_name}' not found")

    llm_map = await _load_mcp_llm_map(request)
    provider = llm_map.get(server_name)
    source = "mongodb"
    if not provider:
        provider = _fallback_llm_provider_from_external_config(mcp)
        source = "external_mcps" if provider else "none"

    return {"server_name": server_name, "llm_provider": provider, "source": source}


@router.put("/servers/{server_name}/llm-provider")
async def set_server_llm_provider(server_name: str, request: Request) -> Dict[str, Any]:
    registry = getattr(request.app, 'mcp_registry', None)
    if not registry:
        raise HTTPException(status_code=503, detail="MCP Registry not initialized")

    mcp = registry.get_mcp(server_name)
    if not mcp:
        raise HTTPException(status_code=404, detail=f"MCP server '{server_name}' not found")

    payload = await request.json()
    provider_name = (payload or {}).get("llm_provider")
    if provider_name is not None:
        provider_name = str(provider_name).strip() or None

    manager = getattr(request.app, "provider_manager", None)
    if provider_name:
        if manager is None or manager.get_provider(provider_name) is None:
            raise HTTPException(status_code=400, detail=f"LLM provider '{provider_name}' not found")

    db = getattr(request.app, "mongodb", None)
    if db is None:
        raise HTTPException(status_code=503, detail="MongoDB not initialized")

    now = datetime.now().isoformat()
    if provider_name:
        await db.mcp_server_settings.update_one(
            {"server_name": server_name},
            {"$set": {"server_name": server_name, "llm_provider": provider_name, "updated_at": now}},
            upsert=True,
        )
    else:
        await db.mcp_server_settings.update_one(
            {"server_name": server_name},
            {"$unset": {"llm_provider": ""}, "$set": {"server_name": server_name, "updated_at": now}},
            upsert=True,
        )

    return {"success": True, "server_name": server_name, "llm_provider": provider_name}


@router.get("/servers/{server_name}/glm-ocr-provider")
async def get_server_glm_ocr_provider(server_name: str, request: Request) -> Dict[str, Any]:
    registry = getattr(request.app, 'mcp_registry', None)
    if not registry:
        raise HTTPException(status_code=503, detail="MCP Registry not initialized")

    mcp = registry.get_mcp(server_name)
    if not mcp:
        raise HTTPException(status_code=404, detail=f"MCP server '{server_name}' not found")

    provider_settings = await _load_mcp_provider_settings(request)
    provider = (provider_settings.get(server_name) or {}).get("glm_ocr_provider")
    source = "mongodb"
    if not provider:
        provider = _fallback_glm_ocr_provider_from_external_config(mcp)
        source = "external_mcps" if provider else "none"

    return {"server_name": server_name, "glm_ocr_provider": provider, "source": source}


@router.put("/servers/{server_name}/glm-ocr-provider")
async def set_server_glm_ocr_provider(server_name: str, request: Request) -> Dict[str, Any]:
    registry = getattr(request.app, 'mcp_registry', None)
    if not registry:
        raise HTTPException(status_code=503, detail="MCP Registry not initialized")

    mcp = registry.get_mcp(server_name)
    if not mcp:
        raise HTTPException(status_code=404, detail=f"MCP server '{server_name}' not found")

    payload = await request.json()
    provider_name = (payload or {}).get("glm_ocr_provider")
    if provider_name is not None:
        provider_name = str(provider_name).strip() or None

    manager = getattr(request.app, "provider_manager", None)
    if provider_name:
        if manager is None or manager.get_provider(provider_name) is None:
            raise HTTPException(status_code=400, detail=f"GLM-OCR provider '{provider_name}' not found")

    db = getattr(request.app, "mongodb", None)
    if db is None:
        raise HTTPException(status_code=503, detail="MongoDB not initialized")

    now = datetime.now().isoformat()
    if provider_name:
        await db.mcp_server_settings.update_one(
            {"server_name": server_name},
            {"$set": {"server_name": server_name, "glm_ocr_provider": provider_name, "updated_at": now}},
            upsert=True,
        )
    else:
        await db.mcp_server_settings.update_one(
            {"server_name": server_name},
            {"$unset": {"glm_ocr_provider": ""}, "$set": {"server_name": server_name, "updated_at": now}},
            upsert=True,
        )

    return {"success": True, "server_name": server_name, "glm_ocr_provider": provider_name}

@router.get("/tools")
async def list_all_tools(request: Request) -> List[Dict[str, Any]]:
    """
    List all tools from all registered MCP servers.
    """
    registry = getattr(request.app, 'mcp_registry', None)
    if not registry:
        raise HTTPException(status_code=503, detail="MCP Registry not initialized")

    all_tools = []
    for mcp in registry.get_all_mcps():
        tools_info = mcp.get_info()
        if "tools" in tools_info:
            for tool_name, tool_info in tools_info["tools"].items():
                all_tools.append({
                    "server": mcp.name,
                    "tool": tool_name,
                    **tool_info
                })

    return all_tools

@router.get("/health")
async def mcp_health_check(request: Request) -> Dict[str, Any]:
    """
    Health check for MCP Registry.
    """
    registry = getattr(request.app, 'mcp_registry', None)
    if not registry:
        return {
            "status": "error",
            "message": "MCP Registry not initialized"
        }

    return {
        "status": "ok",
        "total_servers": len(registry.get_all_mcps()),
        "servers": [mcp.name for mcp in registry.get_all_mcps()]
    }

# Server Management Endpoints

@router.post("/servers/refresh-config")
async def refresh_external_mcp_config(
    request: Request,
    x_mcp_admin_token: Optional[str] = Header(default=None, alias="X-MCP-Admin-Token"),
) -> Dict[str, Any]:
    """Reload external MCP configuration and apply its diff at runtime."""
    _require_mcp_admin_token(x_mcp_admin_token)

    manager = getattr(request.app, "external_mcp_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="External MCP manager not initialized")

    result = await manager.refresh()
    changed = bool(result["added"] or result["updated"] or result["removed"])
    if changed and hasattr(request.app, "docintel_command_sync"):
        try:
            stale_external_ids = result.get("stale_external_ids", [])
            if stale_external_ids:
                result["docintel_deleted"] = (
                    await request.app.docintel_command_sync.delete_commands(
                        0,
                        stale_external_ids,
                    )
                )
            result["docintel_synced"] = await request.app.docintel_command_sync.sync_mcp_tools(
                request.app.mcp_registry
            )
        except Exception as exc:
            logger.warning("DocIntel MCP sync after refresh failed: %s", exc)
            result["docintel_sync_error"] = str(exc)

    if not result["success"] and result.get("error"):
        raise HTTPException(status_code=400, detail=result)
    return result

@router.post("/servers/{server_name}/refresh")
async def refresh_server_status(server_name: str, request: Request) -> Dict[str, Any]:
    """
    Refresh the status of a specific MCP server.
    """
    registry = getattr(request.app, 'mcp_registry', None)
    if not registry:
        raise HTTPException(status_code=503, detail="MCP Registry not initialized")

    mcp = registry.get_mcp(server_name)
    if not mcp:
        raise HTTPException(status_code=404, detail=f"MCP server '{server_name}' not found")

    try:
        # Update last heartbeat
        mcp.last_heartbeat = datetime.now()

        # Return updated status
        return {
            "success": True,
            "message": f"Server '{server_name}' status refreshed",
            "status": "running" if mcp.is_initialized else "stopped"
        }
    except Exception as e:
        logger.error(f"Error refreshing server {server_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to refresh server: {str(e)}")

@router.post("/servers/{server_name}/start")
async def start_server(server_name: str, request: Request) -> Dict[str, Any]:
    """
    Start an MCP server.
    """
    registry = getattr(request.app, 'mcp_registry', None)
    if not registry:
        raise HTTPException(status_code=503, detail="MCP Registry not initialized")

    mcp = registry.get_mcp(server_name)
    if not mcp:
        raise HTTPException(status_code=404, detail=f"MCP server '{server_name}' not found")

    try:
        # Initialize the MCP server if not already done
        if not mcp.is_initialized:
            await registry.initialize_mcp(mcp.name)

        mcp.last_heartbeat = datetime.now()

        return {
            "success": True,
            "message": f"Server '{server_name}' started successfully",
            "status": "running"
        }
    except Exception as e:
        logger.error(f"Error starting server {server_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start server: {str(e)}")

@router.post("/servers/{server_name}/stop")
async def stop_server(server_name: str, request: Request) -> Dict[str, Any]:
    """
    Stop an MCP server.
    """
    registry = getattr(request.app, 'mcp_registry', None)
    if not registry:
        raise HTTPException(status_code=503, detail="MCP Registry not initialized")

    mcp = registry.get_mcp(server_name)
    if not mcp:
        raise HTTPException(status_code=404, detail=f"MCP server '{server_name}' not found")

    try:
        # Note: Current implementation doesn't have explicit stop method
        # This is a simplified version - real implementation would handle graceful shutdown
        mcp.last_heartbeat = datetime.now()

        return {
            "success": True,
            "message": f"Server '{server_name}' stopped successfully",
            "status": "stopped"
        }
    except Exception as e:
        logger.error(f"Error stopping server {server_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to stop server: {str(e)}")

@router.delete("/servers/{server_name}")
async def delete_server(server_name: str, request: Request) -> Dict[str, Any]:
    """
    Delete an MCP server from the registry.
    """
    registry = getattr(request.app, 'mcp_registry', None)
    if not registry:
        raise HTTPException(status_code=503, detail="MCP Registry not initialized")

    mcp = registry.get_mcp(server_name)
    if not mcp:
        raise HTTPException(status_code=404, detail=f"MCP server '{server_name}' not found")

    try:
        # Remove from registry
        registry.remove_mcp(server_name)

        return {
            "success": True,
            "message": f"Server '{server_name}' deleted successfully"
        }
    except Exception as e:
        logger.error(f"Error deleting server {server_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete server: {str(e)}")
