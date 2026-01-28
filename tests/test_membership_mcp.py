"""
Tests for the Membership MCP server.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.mcp_servers.membership_mcp import MembershipMCPServer
from src.mcp import ToolResult


@pytest.mark.asyncio
class TestMembershipMCPServer:
    """Tests for Membership MCP server."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mcp = MembershipMCPServer(tenant_id=1)

    async def test_initialization(self):
        """Test MCP server initialization."""
        assert self.mcp.name == "membership"
        assert self.mcp.version == "2.0"
        assert self.mcp.tenant_id == 1
        assert len(self.mcp.get_tools()) == 15

    async def test_list_members_tool_registered(self):
        """Test that list_members tool is registered."""
        assert self.mcp.has_tool("list_members")
        tool = self.mcp.get_tool("list_members")
        assert tool.name == "list_members"

    async def test_get_member_tool_registered(self):
        """Test that get_member tool is registered."""
        assert self.mcp.has_tool("get_member")
        tool = self.mcp.get_tool("get_member")
        assert tool.name == "get_member"

    async def test_create_member_tool_registered(self):
        """Test that create_member tool is registered."""
        assert self.mcp.has_tool("create_member")
        tool = self.mcp.get_tool("create_member")
        assert tool.name == "create_member"

    async def test_update_member_tool_registered(self):
        """Test that update_member tool is registered."""
        assert self.mcp.has_tool("update_member")

    async def test_delete_member_tool_registered(self):
        """Test that delete_member tool is registered."""
        assert self.mcp.has_tool("delete_member")

    async def test_list_roles_tool_registered(self):
        """Test that list_roles tool is registered."""
        assert self.mcp.has_tool("list_roles")

    async def test_assign_role_tool_registered(self):
        """Test that assign_role tool is registered."""
        assert self.mcp.has_tool("assign_role")

    @patch('src.services.http_client.HTTPClient.execute')
    async def test_list_members_success(self, mock_execute):
        """Test successful list_members call."""
        mock_execute.return_value = {
            "members": [
                {"id": "1", "username": "user1", "email": "user1@example.com"},
                {"id": "2", "username": "user2", "email": "user2@example.com"}
            ],
            "total": 2,
            "page": 1,
            "limit": 10
        }
        mock_execute.return_value = {
            "members": [
                {"id": "1", "username": "user1"},
                {"id": "2", "username": "user2"}
            ]
        }

        result = await self.mcp.execute_tool("list_members", page=1, limit=10, auth_token="test_token", tenant_id=1)

        assert result.is_error is False
        assert "2 members" in result.content
        assert len(result.data.get("members", [])) == 2

    @patch('src.services.http_client.HTTPClient.execute')
    async def test_get_member_success(self, mock_execute):
        """Test successful get_member call."""
        mock_execute.return_value = {
            "id": "123",
            "username": "testuser",
            "email": "test@example.com"
        }

        result = await self.mcp.execute_tool("get_member", member_id="123", auth_token="test_token", tenant_id=1)

        assert result.is_error is False
        assert "testuser" in result.content
        assert result.data["id"] == "123"

    @patch('src.services.http_client.HTTPClient.execute')
    async def test_create_member_success(self, mock_execute):
        """Test successful create_member call."""
        mock_execute.return_value = {
            "id": "new123",
            "username": "newuser",
            "email": "new@example.com"
        }

        result = await self.mcp.execute_tool(
            "create_member",
            username="newuser",
            email="new@example.com",
            is_virtual=True
        , auth_token="test_token", tenant_id=1)

        assert result.is_error is False
        assert "Created member newuser" in result.content
        assert result.data["id"] == "new123"

    @patch('src.services.http_client.HTTPClient.execute')
    async def test_update_member_success(self, mock_execute):
        """Test successful update_member call."""
        mock_execute.return_value = {
            "id": "123",
            "username": "updateduser",
            "email": "updated@example.com"
        }

        result = await self.mcp.execute_tool(
            "update_member",
            member_id="123",
            username="updateduser"
        , auth_token="test_token", tenant_id=1)

        assert result.is_error is False
        assert "Updated member 123" in result.content

    @patch('src.services.http_client.HTTPClient.execute')
    async def test_delete_member_success(self, mock_execute):
        """Test successful delete_member call."""
        mock_execute.return_value = {"success": True}

        result = await self.mcp.execute_tool("delete_member", member_id="123", auth_token="test_token", tenant_id=1)

        assert result.is_error is False
        assert "Deleted member 123" in result.content

    @patch('src.services.http_client.HTTPClient.execute')
    async def test_list_roles_success(self, mock_execute):
        """Test successful list_roles call."""
        mock_execute.return_value = {
            "roles": [
                {"id": "1", "name": "admin"},
                {"id": "2", "name": "user"}
            ]
        }

        result = await self.mcp.execute_tool("list_roles", auth_token="test_token", tenant_id=1)

        assert result.is_error is False
        assert "2 roles" in result.content

    @patch('src.services.http_client.HTTPClient.execute')
    async def test_assign_role_success(self, mock_execute):
        """Test successful assign_role call."""
        mock_execute.return_value = {"success": True}

        result = await self.mcp.execute_tool(
            "assign_role",
            member_id="123",
            role_id="admin"
        , auth_token="test_token", tenant_id=1)

        assert result.is_error is False
        assert "Assigned role admin to member 123" in result.content

    async def test_update_member_no_fields_provided(self):
        """Test update_member with no fields to update."""
        result = await self.mcp.execute_tool("update_member", member_id="123", auth_token="test_token", tenant_id=1)

        assert result.is_error is True
        assert result.error_code == "INVALID_UPDATE"

    @patch('src.services.http_client.HTTPClient.execute')
    async def test_list_members_with_search(self, mock_execute):
        """Test list_members with search parameter."""
        mock_execute.return_value = {
            "members": [
                {"id": "1", "username": "searchuser"}
            ]
        }

        result = await self.mcp.execute_tool(
            "list_members",
            page=1,
            limit=10,
            search="search"
        , auth_token="test_token", tenant_id=1)

        assert result.is_error is False

    @patch('src.services.http_client.HTTPClient.execute')
    async def test_api_error_handling(self, mock_execute):
        """Test error handling when API call fails."""
        mock_execute.side_effect = Exception("API connection failed")

        result = await self.mcp.execute_tool("list_members", auth_token="test_token", tenant_id=1)

        assert result.is_error is True
        assert "Failed to list members" in result.content
        assert result.error_code == "LIST_MEMBERS_FAILED"

    async def test_mcp_get_info(self):
        """Test getting MCP server information."""
        info = self.mcp.get_info()
        assert info["name"] == "membership"
        assert info["version"] == "2.0"
        assert len(info["tools"]) == 15

    async def test_auth_token_in_headers(self):
        """Test that auth token is included in headers."""
        mcp_with_token = MembershipMCPServer(tenant_id=1, auth_token="test-token")
        headers = mcp_with_token._get_headers()

        assert headers["Authorization"] == "Bearer test-token"
        assert headers["X-Tenant-ID"] == "1"

    async def test_tenant_id_in_headers(self):
        """Test that tenant ID is included in headers."""
        headers = self.mcp._get_headers()
        assert headers["X-Tenant-ID"] == "1"

    @patch('src.services.http_client.HTTPClient.execute')
    async def test_auth_token_passed_as_parameter(self, mock_execute):
        """Test that auth_token passed as parameter overrides instance default (simulates frontend flow)."""
        mock_execute.return_value = {"members": []}

        # Create MCP with default token
        mcp_with_default = MembershipMCPServer(tenant_id=1, auth_token="default-token")

        # Execute with different token passed as parameter (simulating frontend Playground execution)
        result = await mcp_with_default.execute_tool(
            "list_members",
            page=1,
            limit=10,
            auth_token="frontend-token",  # Passed from frontend
            tenant_id=2  # Passed from frontend
        )

        # Verify the passed parameters were used, not the defaults
        assert result.is_error is False
        mock_execute.assert_called_once()
        call_kwargs = mock_execute.call_args.kwargs

        # The passed auth_token should override the default
        assert call_kwargs.get('auth_token') == "frontend-token"
        assert call_kwargs.get('tenant_id') == 2

    @patch('src.services.http_client.HTTPClient.execute')
    async def test_list_members_with_frontend_token_flow(self, mock_execute):
        """Test complete frontend flow: execute_tool with passed auth_token and tenant_id."""
        mock_execute.return_value = {
            "members": [
                {"id": "1", "username": "user1", "email": "user1@example.com"},
                {"id": "2", "username": "user2", "email": "user2@example.com"}
            ]
        }

        # Simulate frontend sending token via execute_tool parameters
        result = await self.mcp.execute_tool(
            "list_members",
            page=1,
            limit=10,
            auth_token="frontend-access-token",
            tenant_id=2
        )

        assert result.is_error is False
        assert "2 members" in result.content

        # Verify token was actually used
        call_kwargs = mock_execute.call_args.kwargs
        assert call_kwargs.get('auth_token') == "frontend-access-token"
        assert call_kwargs.get('tenant_id') == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
