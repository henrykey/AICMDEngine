"""
Core Dependencies for MCP Router

Provides dependency injection for MCP registry and other services.
"""

from typing import Optional
from ..mcp.registry import MCPRegistry

# 全局MCP注册表
_mcp_registry: Optional[MCPRegistry] = None


def get_mcp_registry() -> Optional[MCPRegistry]:
    """
    获取MCP注册表

    Returns:
        MCPRegistry: The global MCP registry instance
    """
    return _mcp_registry


def set_mcp_registry(registry: MCPRegistry):
    """
    设置MCP注册表

    Args:
        registry: MCP registry instance to set as global
    """
    global _mcp_registry
    _mcp_registry = registry
