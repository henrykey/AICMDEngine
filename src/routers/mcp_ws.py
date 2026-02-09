"""
MCP WebSocket Router

WebSocket endpoint for MCP client connections.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from typing import Optional
import logging
import json
from datetime import datetime

from ..mcp.connection_manager import ConnectionManager
from ..mcp.auth_jwt import MCPJWTAuth, JWTAuthConfig
from ..mcp.protocol_handler import MCPProtocolHandler
from ..mcp.audit_integration import SimpleAuditLogger
from ..core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

# 全局单例
connection_manager = ConnectionManager()
protocol_handler = MCPProtocolHandler()


@router.websocket("/mcp/v1")
async def mcp_websocket_endpoint(
    websocket: WebSocket,
    token: Optional[str] = None,
    registry = Depends(lambda: None)  # Will be injected
):
    """
    MCP WebSocket端点

    连接URL: ws://localhost:8000/mcp/v1?token=xxx
    或通过header: Authorization: Bearer xxx

    Args:
        websocket: FastAPI WebSocket connection
        token: JWT token (from query param)
        registry: MCP Registry (injected dependency)
    """

    # 如果registry没有注入，使用全局注册表
    if registry is None:
        from ..core.dependencies import get_mcp_registry
        registry = get_mcp_registry()

    if not registry:
        logger.error("MCP Registry not available")
        await websocket.close(code=1011, reason="Server not ready")
        return

    # 初始化认证器
    auth_config = JWTAuthConfig(
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        required_scope=settings.mcp_required_scope
    )
    auth = MCPJWTAuth(auth_config)

    # 认证客户端
    client_info = await auth.authenticate_websocket(websocket)
    if not client_info:
        return

    client_id = client_info["client_id"]

    # 初始化审计日志
    audit_logger = SimpleAuditLogger(registry)

    # 记录连接事件
    tenant_id = client_info.get("tenant_id")
    member_id = client_info.get("member_id")

    if tenant_id and member_id:
        await audit_logger.log_operation(
            tenant_id=tenant_id,
            member_id=member_id,
            action="WEBSOCKET_CONNECT",
            category="API",
            metadata={
                "client_id": client_id,
                "client_name": client_info.get("name"),
                "request_ip": websocket.client.host if websocket.client else None
            }
        )

    # 接受连接
    await connection_manager.connect(websocket, client_id, client_info)

    logger.info(
        f"Active connections: {connection_manager.get_connection_count()}"
    )

    # 准备上下文
    context = {
        "client_id": client_id,
        "client_info": client_info,
        "registry": registry,
        "audit_logger": audit_logger
    }

    try:
        # 消息循环
        while True:
            # 接收消息
            data = await websocket.receive_text()

            try:
                message = json.loads(data)
                logger.debug(f"Received message from {client_id}: {message}")

                # 处理消息
                response = await protocol_handler.handle_message(message, context)

                if response:
                    await websocket.send_json(response)

                    # 记录工具调用审计（如果是tools/call）
                    if message.get("method") == "tools/call":
                        await _log_tool_execution(
                            message, response, client_info, audit_logger
                        )

            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON from {client_id}: {e}")
                await websocket.send_json({
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32700,
                        "message": "Parse error"
                    }
                })

            except Exception as e:
                logger.error(f"Error handling message from {client_id}: {e}")
                await websocket.send_json({
                    "jsonrpc": "2.0",
                    "id": message.get("id") if isinstance(message, dict) else None,
                    "error": {
                        "code": -32603,
                        "message": "Internal error"
                    }
                })

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {client_id}")

    except Exception as e:
        logger.error(f"WebSocket error: {e}")

    finally:
        # 清理
        connection_manager.disconnect(client_id)

        logger.info(
            f"Active connections: {connection_manager.get_connection_count()}"
        )

        # 记录断开事件
        if tenant_id and member_id:
            await audit_logger.log_operation(
                tenant_id=tenant_id,
                member_id=member_id,
                action="WEBSOCKET_DISCONNECT",
                category="API",
                metadata={
                    "client_id": client_id,
                    "client_name": client_info.get("name")
                }
            )


async def _log_tool_execution(
    request_message: dict,
    response_message: dict,
    client_info: dict,
    audit_logger: SimpleAuditLogger
):
    """
    记录工具执行审计

    Args:
        request_message: Original request message
        response_message: Response message
        client_info: Client information
        audit_logger: Audit logger instance
    """
    try:
        tenant_id = client_info.get("tenant_id")
        member_id = client_info.get("member_id")

        if not tenant_id or not member_id:
            return

        params = request_message.get("params", {})
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        result = response_message.get("result", {})
        is_error = result.get("isError", False)

        if is_error:
            content = result.get("content", [{}])[0]
            error_msg = content.get("text") if content else "Unknown error"
            action = "MCP_TOOL_CALL_ERROR"
        else:
            error_msg = None
            action = "MCP_TOOL_CALL_SUCCESS"

        await audit_logger.log_operation(
            tenant_id=tenant_id,
            member_id=member_id,
            action=action,
            category="API",
            tool_name=tool_name,
            arguments=arguments,
            success=not is_error,
            error_message=error_msg
        )
    except Exception as e:
        logger.error(f"Failed to log tool execution: {e}")
