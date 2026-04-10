"""Tool definition for MCP servers."""

from typing import Callable, Dict, Any, Optional, List


class Tool:
    """
    Represents a tool that can be executed by an MCP server.

    A tool has execution metadata, semantic metadata, and a handler function.
    """

    def __init__(
        self,
        name: str,
        description: str,
        input_schema: Dict[str, Any],
        handler: Callable,
        semantic_description: Optional[str] = None,
        use_cases: Optional[List[str]] = None,
        natural_language_examples: Optional[List[str]] = None,
        output_description: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ):
        """
        Initialize a Tool.

        Args:
            name: Unique name of the tool (e.g., "list_members")
            description: Human-readable description of what the tool does
            input_schema: JSON Schema defining the tool's input parameters
            handler: Async callable that implements the tool's logic
            semantic_description: Retrieval-friendly semantic description
            use_cases: Short use cases this tool is suitable for
            natural_language_examples: Example user utterances that should retrieve this tool
            output_description: Short description of important output fields/results
            tags: Retrieval/filter tags
        """
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.handler = handler
        self.semantic_description = semantic_description or description
        self.use_cases = use_cases or []
        self.natural_language_examples = natural_language_examples or []
        self.output_description = output_description or ""
        self.tags = tags or []

    def __repr__(self) -> str:
        return f"Tool(name='{self.name}', description='{self.description}')"

    def get_info(self) -> Dict[str, Any]:
        """Get tool metadata for display or API responses."""
        return {
            "name": self.name,
            "description": self.description,
            "semantic_description": self.semantic_description,
            "use_cases": self.use_cases,
            "natural_language_examples": self.natural_language_examples,
            "output_description": self.output_description,
            "tags": self.tags,
            "input_schema": self.input_schema,
            "inputSchema": self.input_schema,
        }

    def to_dict(self) -> Dict[str, Any]:
        """Convert tool to dictionary."""
        return self.get_info()
