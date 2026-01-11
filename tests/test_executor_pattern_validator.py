"""
Tests for Executor Pattern Validator.

Validates the 5 executor patterns:
1. Static (fixed role/dept/member)
2. Form-driven (user selection at start)
3. Dynamic (data-driven routing)
4. Queue-claim (first-available from role/dept)
5. Automation (MCP tool or virtual member)
"""

import pytest
from typing import Dict, Any


class TestExecutorPatternValidatorStatic:
    """Test executor pattern validator for Static pattern"""

    @pytest.mark.asyncio
    async def test_validate_static_with_role(self):
        """
        RED: Test that validator accepts static pattern with valid role

        Given: executor_pattern="static", config={type:"role", value:"approver"}
               and "approver" role exists
        When: call validate()
        Then: return {"valid": True}
        """
        from src.mcp_servers.bpmn_mcp import ExecutorPatternValidator, MembershipClient

        validator = ExecutorPatternValidator()
        membership_client = MembershipClient("http://membership:8000", "tenant_123")

        # Mock roles
        roles = [
            {"id": "role_001", "name": "approver"},
            {"id": "role_002", "name": "reviewer"}
        ]

        config = {
            "type": "role",
            "value": "approver"
        }

        result = await validator.validate(
            pattern="static",
            config=config,
            available_roles=roles
        )

        assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_validate_static_with_invalid_role(self):
        """
        RED: Test that validator rejects invalid role in static pattern

        Given: executor_pattern="static", config={type:"role", value:"nonexistent"}
        When: call validate()
        Then: return {"valid": False, "error": "..."}
        """
        from src.mcp_servers.bpmn_mcp import ExecutorPatternValidator

        validator = ExecutorPatternValidator()
        roles = [
            {"id": "role_001", "name": "approver"},
            {"id": "role_002", "name": "reviewer"}
        ]

        config = {
            "type": "role",
            "value": "nonexistent"
        }

        result = await validator.validate(
            pattern="static",
            config=config,
            available_roles=roles
        )

        assert result["valid"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_validate_static_with_department(self):
        """
        RED: Test that validator accepts static pattern with valid department

        Given: executor_pattern="static", config={type:"department", value:"finance"}
               and "finance" dept exists
        When: call validate()
        Then: return {"valid": True}
        """
        from src.mcp_servers.bpmn_mcp import ExecutorPatternValidator

        validator = ExecutorPatternValidator()
        departments = [
            {"id": "dept_001", "name": "finance"},
            {"id": "dept_002", "name": "medical"}
        ]

        config = {
            "type": "department",
            "value": "finance"
        }

        result = await validator.validate(
            pattern="static",
            config=config,
            available_departments=departments
        )

        assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_validate_static_missing_type(self):
        """
        RED: Test that validator catches missing 'type' field

        Given: config missing "type" field
        When: call validate()
        Then: return {"valid": False, "error": "..."}
        """
        from src.mcp_servers.bpmn_mcp import ExecutorPatternValidator

        validator = ExecutorPatternValidator()
        roles = [{"id": "role_001", "name": "approver"}]

        config = {
            "value": "approver"
            # Missing "type"
        }

        result = await validator.validate(
            pattern="static",
            config=config,
            available_roles=roles
        )

        assert result["valid"] is False
        assert "type" in result["error"].lower()


class TestExecutorPatternValidatorFormDriven:
    """Test executor pattern validator for Form-Driven pattern"""

    @pytest.mark.asyncio
    async def test_validate_form_driven_with_valid_form_field(self):
        """
        RED: Test that validator accepts form-driven with valid form field

        Given: executor_pattern="form_driven"
               config={form_field:"approver_selection"}
               and form field is defined in process
        When: call validate()
        Then: return {"valid": True}
        """
        from src.mcp_servers.bpmn_mcp import ExecutorPatternValidator

        validator = ExecutorPatternValidator()

        config = {
            "form_field": "approver_selection"
        }

        available_form_fields = ["approver_selection", "reviewer_selection"]

        result = await validator.validate(
            pattern="form_driven",
            config=config,
            available_form_fields=available_form_fields
        )

        assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_validate_form_driven_with_invalid_form_field(self):
        """
        RED: Test that validator rejects invalid form field

        Given: config references non-existent form field
        When: call validate()
        Then: return {"valid": False, "error": "..."}
        """
        from src.mcp_servers.bpmn_mcp import ExecutorPatternValidator

        validator = ExecutorPatternValidator()

        config = {
            "form_field": "nonexistent_field"
        }

        available_form_fields = ["approver_selection", "reviewer_selection"]

        result = await validator.validate(
            pattern="form_driven",
            config=config,
            available_form_fields=available_form_fields
        )

        assert result["valid"] is False
        assert "form field" in result["error"].lower()


class TestExecutorPatternValidatorDynamic:
    """Test executor pattern validator for Dynamic pattern"""

    @pytest.mark.asyncio
    async def test_validate_dynamic_with_valid_mcp_tool(self):
        """
        RED: Test that validator accepts dynamic with valid MCP tool

        Given: executor_pattern="dynamic"
               config={mcp_tool:"route_to_department"}
               and tool is registered
        When: call validate()
        Then: return {"valid": True}
        """
        from src.mcp_servers.bpmn_mcp import ExecutorPatternValidator

        validator = ExecutorPatternValidator()

        config = {
            "mcp_tool": "route_to_department",
            "kb_query": "Find approval dept based on: amount=${amount}"
        }

        available_mcp_tools = ["route_to_department", "get_approvers", "check_policy"]

        result = await validator.validate(
            pattern="dynamic",
            config=config,
            available_mcp_tools=available_mcp_tools
        )

        assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_validate_dynamic_with_unregistered_mcp_tool(self):
        """
        RED: Test that validator rejects unregistered MCP tool

        Given: config references unregistered MCP tool
        When: call validate()
        Then: return {"valid": False, "error": "..."}
        """
        from src.mcp_servers.bpmn_mcp import ExecutorPatternValidator

        validator = ExecutorPatternValidator()

        config = {
            "mcp_tool": "nonexistent_tool",
            "kb_query": "some query"
        }

        available_mcp_tools = ["route_to_department", "get_approvers"]

        result = await validator.validate(
            pattern="dynamic",
            config=config,
            available_mcp_tools=available_mcp_tools
        )

        assert result["valid"] is False
        assert "mcp tool" in result["error"].lower() or "not registered" in result["error"].lower()


class TestExecutorPatternValidatorQueueClaim:
    """Test executor pattern validator for Queue-Claim pattern"""

    @pytest.mark.asyncio
    async def test_validate_queue_claim_with_valid_role(self):
        """
        RED: Test that validator accepts queue-claim with valid role

        Given: executor_pattern="queue_claim"
               config={claim_group:"role", group_name:"sales"}
               and "sales" role exists
        When: call validate()
        Then: return {"valid": True}
        """
        from src.mcp_servers.bpmn_mcp import ExecutorPatternValidator

        validator = ExecutorPatternValidator()

        config = {
            "claim_group": "role",
            "group_name": "sales"
        }

        available_roles = [
            {"id": "role_001", "name": "sales"},
            {"id": "role_002", "name": "support"}
        ]

        result = await validator.validate(
            pattern="queue_claim",
            config=config,
            available_roles=available_roles
        )

        assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_validate_queue_claim_with_invalid_group(self):
        """
        RED: Test that validator rejects invalid group

        Given: config references non-existent role/department
        When: call validate()
        Then: return {"valid": False, "error": "..."}
        """
        from src.mcp_servers.bpmn_mcp import ExecutorPatternValidator

        validator = ExecutorPatternValidator()

        config = {
            "claim_group": "role",
            "group_name": "nonexistent"
        }

        available_roles = [
            {"id": "role_001", "name": "sales"},
            {"id": "role_002", "name": "support"}
        ]

        result = await validator.validate(
            pattern="queue_claim",
            config=config,
            available_roles=available_roles
        )

        assert result["valid"] is False


class TestExecutorPatternValidatorAutomation:
    """Test executor pattern validator for Automation pattern"""

    @pytest.mark.asyncio
    async def test_validate_automation_with_valid_mcp_tool(self):
        """
        RED: Test that validator accepts automation with valid MCP tool

        Given: executor_pattern="automation"
               config={automation_type:"mcp_tool", mcp_tool_name:"financial_audit"}
               and tool is registered
        When: call validate()
        Then: return {"valid": True}
        """
        from src.mcp_servers.bpmn_mcp import ExecutorPatternValidator

        validator = ExecutorPatternValidator()

        config = {
            "automation_type": "mcp_tool",
            "mcp_tool_name": "financial_audit"
        }

        available_mcp_tools = ["financial_audit", "compliance_check", "data_validation"]

        result = await validator.validate(
            pattern="automation",
            config=config,
            available_mcp_tools=available_mcp_tools
        )

        assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_validate_automation_with_virtual_member(self):
        """
        RED: Test that validator accepts automation with virtual member

        Given: executor_pattern="automation"
               config={automation_type:"virtual_member", virtual_member_name:"AI Auditor"}
        When: call validate()
        Then: return {"valid": True}
        """
        from src.mcp_servers.bpmn_mcp import ExecutorPatternValidator

        validator = ExecutorPatternValidator()

        config = {
            "automation_type": "virtual_member",
            "virtual_member_name": "AI Auditor"
        }

        result = await validator.validate(
            pattern="automation",
            config=config
        )

        assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_validate_automation_unregistered_tool(self):
        """
        RED: Test that validator rejects unregistered MCP tool in automation

        Given: config references unregistered MCP tool
        When: call validate()
        Then: return {"valid": False, "error": "..."}
        """
        from src.mcp_servers.bpmn_mcp import ExecutorPatternValidator

        validator = ExecutorPatternValidator()

        config = {
            "automation_type": "mcp_tool",
            "mcp_tool_name": "nonexistent_tool"
        }

        available_mcp_tools = ["financial_audit", "compliance_check"]

        result = await validator.validate(
            pattern="automation",
            config=config,
            available_mcp_tools=available_mcp_tools
        )

        assert result["valid"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
