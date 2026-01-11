"""
Base MCP Server implementation.
"""

from typing import Dict, List, Optional, Any
from abc import ABC, abstractmethod
import logging
from datetime import datetime

from .tool import Tool
from .result import ToolResult

logger = logging.getLogger(__name__)


class BaseMCPServer(ABC):
    """
    Base class for all MCP servers.

    Each MCP server manages a set of tools that correspond to API commands.
    Subclasses should implement their own tool registration in __init__.
    """

    def __init__(self, name: str, version: str):
        """
        Initialize an MCP server.

        Args:
            name: Unique name of the MCP (e.g., "membership")
            version: Version of the MCP (e.g., "2.0")
        """
        self.name = name
        self.version = version
        self.tools: Dict[str, Tool] = {}
        self.is_initialized = False
        self.last_heartbeat = datetime.now()
        self.endpoint = f"mcp://{name}"
        self.description = f"MCP Server: {name}"
        self.author = "Unknown"
        self.dependencies = []
        logger.info(f"Initialized {self.__class__.__name__} (name={name}, version={version})")

    def register_tool(self, tool: Tool) -> None:
        """
        Register a tool with this MCP server.

        Args:
            tool: Tool instance to register
        """
        if tool.name in self.tools:
            logger.warning(f"Tool '{tool.name}' already registered in {self.name}, overwriting")
        self.tools[tool.name] = tool
        logger.debug(f"Registered tool '{tool.name}' in MCP '{self.name}'")

    def get_tool(self, tool_name: str) -> Optional[Tool]:
        """
        Get a tool by name.

        Args:
            tool_name: Name of the tool to retrieve

        Returns:
            Tool instance or None if not found
        """
        return self.tools.get(tool_name)

    def get_tools(self) -> List[Tool]:
        """
        Get all registered tools.

        Returns:
            List of Tool instances
        """
        return list(self.tools.values())

    def has_tool(self, tool_name: str) -> bool:
        """Check if a tool is registered."""
        return tool_name in self.tools

    async def execute_tool(self, tool_name: str, **kwargs) -> ToolResult:
        """
        Execute a tool by name with provided parameters.

        Args:
            tool_name: Name of the tool to execute
            **kwargs: Parameters to pass to the tool handler

        Returns:
            ToolResult with execution result
        """
        if tool_name not in self.tools:
            error_msg = f"Tool '{tool_name}' not found in MCP '{self.name}'"
            logger.error(error_msg)
            return ToolResult.error(error_msg, error_code="TOOL_NOT_FOUND")

        tool = self.tools[tool_name]
        try:
            logger.debug(f"Executing tool '{tool_name}' in MCP '{self.name}' with params: {kwargs}")
            result = await tool.handler(**kwargs)
            return result
        except TypeError as e:
            error_msg = f"Invalid parameters for tool '{tool_name}': {str(e)}"
            logger.error(error_msg)
            return ToolResult.error(error_msg, error_code="INVALID_PARAMS")
        except Exception as e:
            error_msg = f"Error executing tool '{tool_name}': {str(e)}"
            logger.error(error_msg, exc_info=True)
            return ToolResult.error(error_msg, error_code="EXECUTION_ERROR")

    def get_info(self) -> Dict[str, Any]:
        """
        Get information about this MCP server.

        Returns:
            Dictionary with server info and tool list
        """
        return {
            "name": self.name,
            "version": self.version,
            "tools": [tool.get_info() for tool in self.get_tools()]
        }

    async def initialize(self) -> None:
        """
        Initialize the MCP server.

        This method should be overridden by subclasses to perform
        any initialization logic needed.
        """
        self.is_initialized = True
        self.last_heartbeat = datetime.now()
        logger.info(f"Initialized MCP server '{self.name}'")
