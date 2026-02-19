"""
JWT Authentication for MCP Router

This module provides JWT authentication for WebSocket connections,
delegating token validation to Membership Service.
"""

from typing import Optional, Dict, Any
from datetime import datetime
import httpx
from fastapi import HTTPException, WebSocket, status
import logging

logger = logging.getLogger(__name__)


class JWTAuthConfig:
    """JWT认证配置"""

    def __init__(
        self,
        membership_url: str,
        required_scope: str = "mcp",
    ):
        """
        Initialize JWT auth config

        Args:
            membership_url: Membership service URL (e.g., "http://localhost:8080")
            required_scope: Required scope/permission (default: "mcp")
        """
        self.membership_url = membership_url
        self.required_scope = required_scope


class MCPJWTAuth:
    """MCP JWT认证器"""

    def __init__(self, config: JWTAuthConfig):
        """
        Initialize JWT authenticator

        Args:
            config: JWT authentication configuration
        """
        self.config = config

    async def validate_token(self, token: str) -> dict:
        """
        验证JWT token并返回payload（委托给 membership 服务）

        Args:
            token: JWT string

        Returns:
            dict: JWT payload

        Raises:
            HTTPException: Token无效或缺少MCP权限
        """
        try:
            # 调用 membership 服务验证 token
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{self.config.membership_url}/v2/auth/validate",
                    headers={
                        "Authorization": f"Bearer {token}"
                    }
                )

                if response.status_code == 200:
                    payload = response.json()
                    logger.info(f"Token validated by membership service for: {payload.get('sub')}")
                    return payload
                else:
                    error_detail = response.json().get("error_message", "Validation failed")
                    logger.error(f"Token validation failed: {error_detail}")
                    raise HTTPException(
                        status_code=response.status_code,
                        detail=error_detail
                    )

        except httpx.RequestError as e:
            logger.error(f"Failed to connect to membership service: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication service unavailable"
            )

    def extract_client_info(self, payload: dict) -> dict:
        """
        从payload提取客户端信息

        Args:
            payload: JWT payload

        Returns:
            dict: Client information
        """
        return {
            "client_id": payload.get("sub", payload.get("user_id", "unknown")),
            "name": payload.get(
                "name",
                payload.get("preferred_username", "Unknown")
            ),
            "tenant_id": payload.get("tenant_id"),
            "member_id": payload.get("member_id"),
            "scopes": payload.get("scopes", []),
            "permissions": payload.get("permissions", []),
            "exp": payload.get("exp"),
            "iat": payload.get("iat")
        }

    async def authenticate_websocket(
        self,
        websocket: WebSocket,
        token_param: str = "token"
    ) -> Optional[dict]:
        """
        WebSocket连接认证

        Args:
            websocket: FastAPI WebSocket connection
            token_param: URL parameter name (default: "token")

        Returns:
            dict: Client information, or None if authentication failed
        """
        # 从查询参数获取token
        token = websocket.query_params.get(token_param)

        if not token:
            # 也可以从Authorization header获取
            auth_header = websocket.headers.get("authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]

        if not token:
            await websocket.close(code=4001, reason="Missing token")
            return None

        try:
            # 调用 membership 服务验证 token
            payload = await self.validate_token(token)
            client_info = self.extract_client_info(payload)

            logger.info(
                f"WebSocket authenticated: {client_info['client_id']} "
                f"({client_info.get('name', 'Unknown')})"
            )
            return client_info

        except HTTPException as e:
            await websocket.close(code=4003, reason=e.detail)
            return None
