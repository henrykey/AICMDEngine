"""
Tests for BPMN-MCP MembershipClient integration.

Following TDD methodology:
1. Write failing tests first
2. Implement minimal code to pass
3. Refactor as needed
"""

import pytest
from typing import Dict, List
from unittest.mock import Mock, AsyncMock, patch


class TestMembershipClientGetOrgContext:
    """Test MembershipClient.get_org_context() - Organizational structure retrieval"""

    @pytest.mark.asyncio
    async def test_get_org_context_returns_org_structure(self):
        """
        RED: Test that get_org_context returns departments, roles, and members

        Given: tenant_id = "tenant_123"
        When: call get_org_context()
        Then: return dict with keys: departments, roles, members
              each key contains a list
        """
        from src.mcp_servers.bpmn_mcp import MembershipClient

        # Arrange
        client = MembershipClient(base_url="http://membership:8000", tenant_id="tenant_123")

        # Mock the internal HTTP calls
        with patch.object(client, '_fetch_departments', new_callable=AsyncMock) as mock_depts, \
             patch.object(client, '_fetch_roles', new_callable=AsyncMock) as mock_roles, \
             patch.object(client, '_fetch_members', new_callable=AsyncMock) as mock_members:

            mock_depts.return_value = [
                {"id": "dept_001", "name": "finance"},
                {"id": "dept_002", "name": "medical"}
            ]
            mock_roles.return_value = [
                {"id": "role_001", "name": "approver"},
                {"id": "role_002", "name": "reviewer"}
            ]
            mock_members.return_value = [
                {"id": "mem_001", "name": "Alice", "roles": ["approver"]},
                {"id": "mem_002", "name": "Bob", "roles": ["reviewer"]}
            ]

            # Act
            result = await client.get_org_context()

            # Assert
            assert isinstance(result, dict)
            assert "departments" in result
            assert "roles" in result
            assert "members" in result
            assert isinstance(result["departments"], list)
            assert isinstance(result["roles"], list)
            assert isinstance(result["members"], list)
            assert len(result["departments"]) == 2
            assert len(result["roles"]) == 2
            assert len(result["members"]) == 2


class TestMembershipClientValidateExecutor:
    """Test MembershipClient.validate_executor() - Executor pattern validation"""

    @pytest.mark.asyncio
    async def test_validate_executor_static_role_exists(self):
        """
        RED: Test that validate_executor validates static role pattern

        Given: executor_pattern = "static", executor_config = {type: "role", value: "approver"}
        When: call validate_executor()
        Then: return {"valid": True} if role exists
        """
        from src.mcp_servers.bpmn_mcp import MembershipClient

        # Arrange
        client = MembershipClient(base_url="http://membership:8000", tenant_id="tenant_123")
        executor_pattern = "static"
        executor_config = {"type": "role", "value": "approver"}

        with patch.object(client, '_fetch_roles', new_callable=AsyncMock) as mock_roles:
            mock_roles.return_value = [
                {"id": "role_001", "name": "approver"},
                {"id": "role_002", "name": "reviewer"}
            ]

            # Act
            result = await client.validate_executor(executor_pattern, executor_config)

            # Assert
            assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_validate_executor_static_role_not_exists(self):
        """
        RED: Test that validate_executor returns error for non-existent role

        Given: executor_pattern = "static", executor_config = {type: "role", value: "nonexistent"}
        When: call validate_executor()
        Then: return {"valid": False, "error": "Role not found: nonexistent"}
        """
        from src.mcp_servers.bpmn_mcp import MembershipClient

        # Arrange
        client = MembershipClient(base_url="http://membership:8000", tenant_id="tenant_123")
        executor_pattern = "static"
        executor_config = {"type": "role", "value": "nonexistent"}

        with patch.object(client, '_fetch_roles', new_callable=AsyncMock) as mock_roles:
            mock_roles.return_value = [
                {"id": "role_001", "name": "approver"},
                {"id": "role_002", "name": "reviewer"}
            ]

            # Act
            result = await client.validate_executor(executor_pattern, executor_config)

            # Assert
            assert result["valid"] is False
            assert "not found" in result["error"].lower()
            assert "nonexistent" in result["error"]

    @pytest.mark.asyncio
    async def test_validate_executor_static_department_exists(self):
        """
        RED: Test that validate_executor validates static department pattern

        Given: executor_pattern = "static", executor_config = {type: "department", value: "finance"}
        When: call validate_executor()
        Then: return {"valid": True} if department exists
        """
        from src.mcp_servers.bpmn_mcp import MembershipClient

        # Arrange
        client = MembershipClient(base_url="http://membership:8000", tenant_id="tenant_123")
        executor_pattern = "static"
        executor_config = {"type": "department", "value": "finance"}

        with patch.object(client, '_fetch_departments', new_callable=AsyncMock) as mock_depts:
            mock_depts.return_value = [
                {"id": "dept_001", "name": "finance"},
                {"id": "dept_002", "name": "medical"}
            ]

            # Act
            result = await client.validate_executor(executor_pattern, executor_config)

            # Assert
            assert result["valid"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
