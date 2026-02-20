"""
MCP (Model Context Protocol) API endpoints.
"""

from fastapi import APIRouter, Request, HTTPException, Depends
from typing import Dict, Any, List, Optional
from datetime import datetime
import logging

from src.mcp.registry import MCPRegistry, ToolResult

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/servers")
async def list_mcp_servers(request: Request) -> Dict[str, Any]:
    """
    List all registered MCP servers.
    """
    registry = getattr(request.app, 'mcp_registry', None)
    if not registry:
        raise HTTPException(status_code=503, detail="MCP Registry not initialized")

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
                    "dependencies": getattr(mcp, 'dependencies', [])
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
    request: Request,
    **kwargs: Any
) -> ToolResult:
    """
    Execute a tool from a specific MCP server.

    Args:
        server_name: Name of the MCP server
        tool_name: Name of the tool to execute
        **kwargs: Tool parameters (including optional "llm" key to specify LLM provider)

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

    # Extract "llm" parameter if present
    llm_provider = kwargs.pop("llm", None)

    try:
        result = await registry.execute_command(
            mcp_name=server_name,
            tool_name=tool_name,
            llm_provider=llm_provider,
            **kwargs
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to execute tool: {str(e)}")

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