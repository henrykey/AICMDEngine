"""
Tool definition for MCP servers.
"""

from typing import Callable, Dict, Any, Optional
import json


class Tool:
    """
    Represents a tool that can be executed by an MCP server.

    A tool has a name, description, input schema, and a handler function.
    """

    def __init__(
        self,
        name: str,
        description: str,
        input_schema: Dict[str, Any],
        handler: Callable
    ):
        """
        Initialize a Tool.

        Args:
            name: Unique name of the tool (e.g., "list_members")
            description: Human-readable description of what the tool does
            input_schema: JSON Schema defining the tool's input parameters
            handler: Async callable that implements the tool's logic
        """
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.handler = handler

    def __repr__(self) -> str:
        return f"Tool(name='{self.name}', description='{self.description}')"

    def get_info(self) -> Dict[str, Any]:
        """Get tool metadata for display or API responses."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema
        }

    def to_dict(self) -> Dict[str, Any]:
        """Convert tool to dictionary."""
        return self.get_info()
