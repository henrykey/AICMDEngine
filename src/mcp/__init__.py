"""
MCP (Model Context Protocol) Framework for AICMDEngine.

This module provides the base classes and utilities for implementing
MCP servers that wrap API commands.
"""

from .tool import Tool
from .result import ToolResult
from .base_server import BaseMCPServer
from .registry import MCPRegistry

__all__ = [
    "Tool",
    "ToolResult",
    "BaseMCPServer",
    "MCPRegistry",
]
