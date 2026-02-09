"""
Tests for MCP JWT Authentication
"""

import pytest
import time
from src.mcp.auth_jwt import MCPJWTAuth, JWTAuthConfig
from fastapi import HTTPException


def test_validate_valid_token():
    """测试有效token验证"""
    config = JWTAuthConfig(secret_key="test-secret")
    auth = MCPJWTAuth(config)

    import jwt
    token = jwt.encode(
        {
            "sub": "user123",
            "scopes": ["mcp:*"],
            "exp": int(time.time()) + 3600
        },
        "test-secret"
    )

    payload = auth.validate_token(token)
    assert payload["sub"] == "user123"
    assert "mcp:*" in payload["scopes"]


def test_validate_token_without_mcp_scope():
    """测试缺少mcp权限的token"""
    config = JWTAuthConfig(secret_key="test-secret")
    auth = MCPJWTAuth(config)

    import jwt
    token = jwt.encode(
        {
            "sub": "user123",
            "scopes": ["api:read"],  # 没有mcp权限
            "exp": int(time.time()) + 3600
        },
        "test-secret"
    )

    with pytest.raises(HTTPException) as exc:
        auth.validate_token(token)
    assert exc.value.status_code == 403


def test_validate_expired_token():
    """测试过期token"""
    config = JWTAuthConfig(secret_key="test-secret")
    auth = MCPJWTAuth(config)

    import jwt
    token = jwt.encode(
        {
            "sub": "user123",
            "scopes": ["mcp:*"],
            "exp": int(time.time()) - 3600  # 过期
        },
        "test-secret"
    )

    with pytest.raises(HTTPException) as exc:
        auth.validate_token(token)
    assert exc.value.status_code == 401


def test_extract_client_info():
    """测试提取客户端信息"""
    config = JWTAuthConfig(secret_key="test-secret")
    auth = MCPJWTAuth(config)

    payload = {
        "sub": "user123",
        "name": "Test User",
        "scopes": ["mcp:*"],
        "tenant_id": 1
    }

    client_info = auth.extract_client_info(payload)
    assert client_info["client_id"] == "user123"
    assert client_info["name"] == "Test User"
    assert client_info["tenant_id"] == 1
    assert "mcp:*" in client_info["scopes"]


def test_has_mcp_permission_with_scopes():
    """测试scopes方式检查mcp权限"""
    config = JWTAuthConfig(secret_key="test-secret")
    auth = MCPJWTAuth(config)

    # 测试 mcp:*
    assert auth._has_mcp_permission({"scopes": ["mcp:*", "api:read"]})

    # 测试 mcp.read
    assert auth._has_mcp_permission({"scopes": ["mcp:read", "mcp:write"]})

    # 测试没有权限
    assert not auth._has_mcp_permission({"scopes": ["api:read", "api:write"]})


def test_has_mcp_permission_with_permissions():
    """测试permissions方式检查mcp权限"""
    config = JWTAuthConfig(secret_key="test-secret")
    auth = MCPJWTAuth(config)

    # 测试 mcp.access
    assert auth._has_mcp_permission({"permissions": ["mcp.access"]})

    # 测试 mcp.tools.execute
    assert auth._has_mcp_permission({"permissions": ["mcp.tools.execute"]})

    # 测试没有权限
    assert not auth._has_mcp_permission({"permissions": ["api.access"]})


def test_has_mcp_permission_with_resource_access():
    """测试resource_access方式检查mcp权限（Keycloak风格）"""
    config = JWTAuthConfig(secret_key="test-secret")
    auth = MCPJWTAuth(config)

    # 测试有mcp资源访问
    assert auth._has_mcp_permission({
        "resource_access": {"mcp": {"roles": ["admin"]}}
    })

    # 测试没有mcp资源访问
    assert not auth._has_mcp_permission({
        "resource_access": {"api": {"roles": ["user"]}}
    })
