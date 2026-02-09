"""
JWT Authentication for MCP Router

This module provides JWT authentication for WebSocket connections,
validating tokens and checking for MCP permissions.
"""

from typing import Optional, Dict, Any
from datetime import datetime
import jwt
from jwt import PyJWTError
from fastapi import HTTPException, WebSocket, status
import logging

logger = logging.getLogger(__name__)


class JWTAuthConfig:
    """JWT认证配置"""

    def __init__(
        self,
        secret_key: str,
        algorithm: str = "HS256",
        required_scope: str = "mcp",
        issuer: Optional[str] = None,
        audience: Optional[str] = None
    ):
        """
        Initialize JWT auth config

        Args:
            secret_key: JWT secret key for validation
            algorithm: JWT algorithm (default: HS256)
            required_scope: Required scope/permission (default: "mcp")
            issuer: Expected JWT issuer (optional)
            audience: Expected JWT audience (optional)
        """
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.required_scope = required_scope
        self.issuer = issuer
        self.audience = audience


class MCPJWTAuth:
    """MCP JWT认证器"""

    def __init__(self, config: JWTAuthConfig):
        """
        Initialize JWT authenticator

        Args:
            config: JWT authentication configuration
        """
        self.config = config

    def validate_token(self, token: str) -> dict:
        """
        验证JWT token并返回payload

        Args:
            token: JWT string

        Returns:
            dict: JWT payload

        Raises:
            HTTPException: Token无效或缺少MCP权限
        """
        try:
            # 解码JWT
            payload = jwt.decode(
                token,
                self.config.secret_key,
                algorithms=[self.config.algorithm],
                issuer=self.config.issuer,
                audience=self.config.audience
            )

            # 检查MCP权限
            if not self._has_mcp_permission(payload):
                logger.warning(
                    f"Token valid but missing MCP permission: "
                    f"{payload.get('sub')}"
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Missing MCP permission scope"
                )

            logger.info(f"JWT validated successfully for: {payload.get('sub')}")
            return payload

        except PyJWTError as e:
            logger.error(f"JWT validation failed: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token: {str(e)}"
            )

    def _has_mcp_permission(self, payload: dict) -> bool:
        """
        检查payload中是否包含MCP权限

        支持多种格式:
        - scopes: ["mcp:*", "mcp.read", ...]
        - permissions: ["mcp.access", "mcp.tools.execute", ...]
        - resource_access: {"mcp": {"roles": ["admin"]}}

        Args:
            payload: JWT payload

        Returns:
            bool: True if has MCP permission
        """
        # 方式1: 检查scopes字段
        scopes = payload.get("scopes", payload.get("scope", []))
        if isinstance(scopes, str):
            scopes = scopes.split()

        for scope in scopes:
            if scope.startswith("mcp") or scope == "mcp:*":
                return True

        # 方式2: 检查permissions字段
        permissions = payload.get("permissions", [])
        for perm in permissions:
            if perm.startswith("mcp"):
                return True

        # 方式3: 检查resource_access (Keycloak风格)
        resource_access = payload.get("resource_access", {})
        if "mcp" in resource_access:
            return True

        return False

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
            payload = self.validate_token(token)
            client_info = self.extract_client_info(payload)

            logger.info(
                f"WebSocket authenticated: {client_info['client_id']} "
                f"({client_info.get('name', 'Unknown')})"
            )
            return client_info

        except HTTPException as e:
            await websocket.close(code=4003, reason=e.detail)
            return None
