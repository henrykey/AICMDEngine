"""
Tool execution result types for MCP servers.
"""

from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict
import json


@dataclass
class ToolResult:
    """Result of executing an MCP tool."""

    is_error: bool
    content: str
    data: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None

    def __post_init__(self):
        """Ensure data is a dict."""
        if self.data is None:
            self.data = {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary for JSON serialization."""
        return {
            "is_error": self.is_error,
            "content": self.content,
            "data": self.data,
            "error_code": self.error_code
        }

    def to_json(self) -> str:
        """Convert result to JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def success(cls, content: str, data: Optional[Dict[str, Any]] = None) -> "ToolResult":
        """Create a success result."""
        return cls(is_error=False, content=content, data=data)

    @classmethod
    def error(cls, content: str, error_code: str = "ERROR", data: Optional[Dict[str, Any]] = None) -> "ToolResult":
        """Create an error result."""
        return cls(is_error=True, content=content, error_code=error_code, data=data)
