"""
Tests for the MCP framework core functionality.
"""

import pytest
import logging

from src.mcp import BaseMCPServer, MCPRegistry, Tool, ToolResult
from src.mcp_servers.test_mcp import TestMCPServer


@pytest.mark.asyncio
class TestMCPFramework:
    """Tests for MCP framework components."""

    async def test_tool_result_success(self):
        """Test creating a successful ToolResult."""
        result = ToolResult.success(
            content="Test passed",
            data={"key": "value"}
        )
        assert result.is_error is False
        assert result.content == "Test passed"
        assert result.data == {"key": "value"}
        assert result.error_code is None

    async def test_tool_result_error(self):
        """Test creating an error ToolResult."""
        result = ToolResult.error(
            content="Test failed",
            error_code="TEST_ERROR"
        )
        assert result.is_error is True
        assert result.content == "Test failed"
        assert result.error_code == "TEST_ERROR"

    async def test_tool_result_to_dict(self):
        """Test converting ToolResult to dictionary."""
        result = ToolResult.success(
            content="Test",
            data={"test": "data"}
        )
        result_dict = result.to_dict()
        assert isinstance(result_dict, dict)
        assert result_dict["is_error"] is False
        assert result_dict["content"] == "Test"

    async def test_tool_creation(self):
        """Test creating a Tool."""
        async def handler():
            return ToolResult.success("Done")

        tool = Tool(
            name="test_tool",
            description="A test tool",
            input_schema={"type": "object"},
            handler=handler
        )
        assert tool.name == "test_tool"
        assert tool.description == "A test tool"

    async def test_base_mcp_server_initialization(self):
        """Test BaseMCPServer initialization."""
        mcp = TestMCPServer()
        assert mcp.name == "test"
        assert mcp.version == "1.0"
        assert len(mcp.get_tools()) > 0

    async def test_base_mcp_server_register_tool(self):
        """Test registering tools with MCP server."""
        async def dummy_handler():
            return ToolResult.success("Test")

        mcp = TestMCPServer()
        initial_count = len(mcp.get_tools())

        tool = Tool(
            name="test_new_tool",
            description="New test tool",
            input_schema={"type": "object"},
            handler=dummy_handler
        )
        mcp.register_tool(tool)

        assert len(mcp.get_tools()) == initial_count + 1
        assert mcp.has_tool("test_new_tool")

    async def test_base_mcp_server_execute_tool(self):
        """Test executing a tool."""
        mcp = TestMCPServer()
        result = await mcp.execute_tool("echo", message="Hello, MCP!")
        assert result.is_error is False
        assert "Hello, MCP!" in result.content
        assert result.data["original_message"] == "Hello, MCP!"

    async def test_base_mcp_server_execute_nonexistent_tool(self):
        """Test executing a non-existent tool."""
        mcp = TestMCPServer()
        result = await mcp.execute_tool("nonexistent_tool")
        assert result.is_error is True
        assert result.error_code == "TOOL_NOT_FOUND"

    async def test_mcp_registry_initialization(self):
        """Test MCPRegistry initialization."""
        registry = MCPRegistry()
        assert len(registry.get_all_mcps()) == 0

    async def test_mcp_registry_register_mcp(self):
        """Test registering an MCP with registry."""
        registry = MCPRegistry()
        mcp = TestMCPServer()
        registry.register_mcp(mcp)

        assert len(registry.get_all_mcps()) == 1
        assert registry.has_mcp("test")

    async def test_mcp_registry_get_mcp(self):
        """Test retrieving an MCP from registry."""
        registry = MCPRegistry()
        mcp = TestMCPServer()
        registry.register_mcp(mcp)

        retrieved_mcp = registry.get_mcp("test")
        assert retrieved_mcp is not None
        assert retrieved_mcp.name == "test"

    async def test_mcp_registry_execute_command(self):
        """Test executing a command through registry."""
        registry = MCPRegistry()
        mcp = TestMCPServer()
        registry.register_mcp(mcp)

        result = await registry.execute_command("test", "echo", message="Test message")
        assert result.is_error is False
        assert "Test message" in result.content

    async def test_mcp_registry_execute_nonexistent_mcp(self):
        """Test executing command with non-existent MCP."""
        registry = MCPRegistry()
        result = await registry.execute_command("nonexistent", "some_tool")
        assert result.is_error is True
        assert result.error_code == "MCP_NOT_FOUND"

    async def test_test_mcp_echo_tool(self):
        """Test the echo tool in TestMCP."""
        mcp = TestMCPServer()
        result = await mcp.execute_tool("echo", message="Hello")
        assert result.is_error is False
        assert result.data["original_message"] == "Hello"

    async def test_test_mcp_add_tool(self):
        """Test the add tool in TestMCP."""
        mcp = TestMCPServer()
        result = await mcp.execute_tool("add", a=5, b=3)
        assert result.is_error is False
        assert result.data["result"] == 8

    async def test_test_mcp_get_time_tool(self):
        """Test the get_time tool in TestMCP."""
        mcp = TestMCPServer()
        result = await mcp.execute_tool("get_time")
        assert result.is_error is False
        assert "timestamp" in result.data

    async def test_mcp_server_get_info(self):
        """Test getting MCP server information."""
        mcp = TestMCPServer()
        info = mcp.get_info()
        assert info["name"] == "test"
        assert info["version"] == "1.0"
        assert "tools" in info
        assert len(info["tools"]) > 0

    async def test_mcp_registry_get_registry_info(self):
        """Test getting registry information."""
        registry = MCPRegistry()
        mcp = TestMCPServer()
        registry.register_mcp(mcp)

        info = registry.get_registry_info()
        assert info["total_mcps"] == 1
        assert "test" in info["mcps"]
        assert "tools" in info["mcps"]["test"]

    async def test_mcp_registry_get_tool_info(self):
        """Test getting information about a specific tool."""
        registry = MCPRegistry()
        mcp = TestMCPServer()
        registry.register_mcp(mcp)

        tool_info = registry.get_tool_info("test", "echo")
        assert tool_info is not None
        assert tool_info["name"] == "echo"
        assert "description" in tool_info
        assert "input_schema" in tool_info


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
