"""
Simple test MCP server for framework validation.

This MCP provides basic tools for testing the MCP framework.
"""

from typing import Any, Dict
import logging

from ..mcp import BaseMCPServer, Tool, ToolResult

logger = logging.getLogger(__name__)


class TestMCPServer(BaseMCPServer):
    """
    Simple test MCP for framework validation.

    Provides basic tools like echo, add, and get_time for testing.
    """

    def __init__(self):
        """Initialize the test MCP server."""
        super().__init__("test", "1.0")
        self._register_tools()

    def _register_tools(self) -> None:
        """Register test tools."""
        # Echo tool
        self.register_tool(Tool(
            name="echo",
            description="Echo back the input message",
            input_schema={
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "The message to echo"
                    }
                },
                "required": ["message"]
            },
            handler=self.echo
        ))

        # Add numbers tool
        self.register_tool(Tool(
            name="add",
            description="Add two numbers",
            input_schema={
                "type": "object",
                "properties": {
                    "a": {
                        "type": "number",
                        "description": "First number"
                    },
                    "b": {
                        "type": "number",
                        "description": "Second number"
                    }
                },
                "required": ["a", "b"]
            },
            handler=self.add
        ))

        # Get time tool
        self.register_tool(Tool(
            name="get_time",
            description="Get current server time",
            input_schema={
                "type": "object",
                "properties": {}
            },
            handler=self.get_time
        ))

    async def echo(self, message: str) -> ToolResult:
        """Echo a message."""
        logger.info(f"Echo: {message}")
        return ToolResult.success(
            content=f"Echo: {message}",
            data={"original_message": message}
        )

    async def add(self, a: float, b: float) -> ToolResult:
        """Add two numbers."""
        result = a + b
        logger.info(f"Add: {a} + {b} = {result}")
        return ToolResult.success(
            content=f"{a} + {b} = {result}",
            data={"a": a, "b": b, "result": result}
        )

    async def get_time(self) -> ToolResult:
        """Get current time."""
        from datetime import datetime
        now = datetime.utcnow().isoformat()
        logger.info(f"Get time: {now}")
        return ToolResult.success(
            content=f"Current time: {now}",
            data={"timestamp": now}
        )
