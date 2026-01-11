"""
Registry for managing multiple MCP servers.
"""

from typing import Dict, Optional, List, Any
import logging
from datetime import datetime

from .base_server import BaseMCPServer
from .result import ToolResult

logger = logging.getLogger(__name__)


class MCPRegistry:
    """
    Central registry for managing all MCP servers in the system.

    Allows registering, querying, and executing commands across multiple MCPs.
    """

    def __init__(self):
        """Initialize the MCP registry."""
        self.mcps: Dict[str, BaseMCPServer] = {}
        logger.info("Initialized MCPRegistry")

    def register_mcp(self, mcp: BaseMCPServer) -> None:
        """
        Register an MCP server.

        Args:
            mcp: BaseMCPServer instance to register

        Raises:
            ValueError: If an MCP with the same name is already registered
        """
        if mcp.name in self.mcps:
            logger.warning(f"MCP '{mcp.name}' already registered, overwriting")
        self.mcps[mcp.name] = mcp
        logger.info(f"Registered MCP '{mcp.name}' (version {mcp.version})")

    def get_mcp(self, mcp_name: str) -> Optional[BaseMCPServer]:
        """
        Get an MCP server by name.

        Args:
            mcp_name: Name of the MCP to retrieve

        Returns:
            BaseMCPServer instance or None if not found
        """
        return self.mcps.get(mcp_name)

    def has_mcp(self, mcp_name: str) -> bool:
        """Check if an MCP is registered."""
        return mcp_name in self.mcps

    def get_all_mcps(self) -> List[BaseMCPServer]:
        """Get all registered MCPs."""
        return list(self.mcps.values())

    async def execute_command(
        self,
        mcp_name: str,
        tool_name: str,
        **kwargs
    ) -> ToolResult:
        """
        Execute a tool command in a specific MCP.

        Args:
            mcp_name: Name of the MCP containing the tool
            tool_name: Name of the tool to execute
            **kwargs: Parameters to pass to the tool

        Returns:
            ToolResult with execution result
        """
        mcp = self.get_mcp(mcp_name)
        if not mcp:
            error_msg = f"MCP '{mcp_name}' not found in registry"
            logger.error(error_msg)
            return ToolResult.error(error_msg, error_code="MCP_NOT_FOUND")

        logger.debug(f"Executing {mcp_name}.{tool_name} with params: {kwargs}")
        return await mcp.execute_tool(tool_name, **kwargs)

    def get_registry_info(self) -> Dict[str, Any]:
        """
        Get comprehensive information about all registered MCPs and their tools.

        Returns:
            Dictionary with registry info and all MCP info
        """
        return {
            "total_mcps": len(self.mcps),
            "mcps": {mcp.name: mcp.get_info() for mcp in self.get_all_mcps()}
        }

    def get_mcp_info(self, mcp_name: str) -> Optional[Dict[str, Any]]:
        """Get information about a specific MCP."""
        mcp = self.get_mcp(mcp_name)
        if mcp:
            return mcp.get_info()
        return None

    def get_tool_info(self, mcp_name: str, tool_name: str) -> Optional[Dict[str, Any]]:
        """Get information about a specific tool in an MCP."""
        mcp = self.get_mcp(mcp_name)
        if mcp:
            tool = mcp.get_tool(tool_name)
            if tool:
                return tool.get_info()
        return None

    def remove_mcp(self, mcp_name: str) -> bool:
        """
        Remove an MCP server from the registry.

        Args:
            mcp_name: Name of the MCP to remove

        Returns:
            True if MCP was removed, False if not found
        """
        if mcp_name in self.mcps:
            removed_mcp = self.mcps.pop(mcp_name)
            logger.info(f"Removed MCP '{mcp_name}' from registry")

            # Reset initialization status
            if hasattr(removed_mcp, 'is_initialized'):
                removed_mcp.is_initialized = False

            return True
        return False

    async def initialize_mcp(self, mcp_name: str) -> bool:
        """
        Initialize an MCP server.

        Args:
            mcp_name: Name of the MCP to initialize

        Returns:
            True if initialization was successful, False if not found or failed
        """
        mcp = self.get_mcp(mcp_name)
        if not mcp:
            logger.error(f"MCP '{mcp_name}' not found for initialization")
            return False

        try:
            # Initialize the MCP server
            if hasattr(mcp, 'initialize'):
                await mcp.initialize()

            # Update last heartbeat
            if hasattr(mcp, 'last_heartbeat'):
                mcp.last_heartbeat = datetime.now()
            else:
                mcp.last_heartbeat = datetime.now()

            logger.info(f"Initialized MCP '{mcp_name}'")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize MCP '{mcp_name}': {e}")
            return False
