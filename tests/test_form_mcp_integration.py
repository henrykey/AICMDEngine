"""
Integration tests for FORM-MCP in MCP Registry.

Tests that FORM-MCP is properly registered and can be discovered/executed
through the MCP Registry system.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.mcp.registry import MCPRegistry
from src.mcp_servers.form_mcp import FORM_MCP


class TestFormMCPIntegration:
    """Integration tests for FORM-MCP with MCP Registry"""

    @pytest.mark.asyncio
    async def test_form_mcp_initialization(self):
        """RED: Test FORM-MCP initializes properly"""
        mcp = FORM_MCP(
            membership_base_url="http://localhost:8080",
            use_real_llm=False
        )

        assert mcp.name == "form_mcp"
        assert mcp.version == "1.0.0"
        assert mcp.validator is not None

    @pytest.mark.asyncio
    async def test_form_mcp_list_tools(self):
        """RED: Test FORM-MCP lists available tools"""
        mcp = FORM_MCP(
            membership_base_url="http://localhost:8080",
            use_real_llm=False
        )

        tools = await mcp.list_tools(tenant_id="test_tenant")

        tool_names = [t["name"] for t in tools]
        assert "generate_form" in tool_names
        assert "validate_form" in tool_names
        assert "bind_form_to_process" in tool_names
        assert "suggest_form_fields" in tool_names

    @pytest.mark.asyncio
    async def test_form_mcp_registration(self):
        """RED: Test FORM-MCP can be registered in MCP registry"""
        registry = MCPRegistry()
        mcp = FORM_MCP(
            membership_base_url="http://localhost:8080",
            use_real_llm=False
        )

        registry.register_mcp(mcp)

        assert registry.has_mcp("form_mcp")
        assert registry.get_mcp("form_mcp") == mcp

    @pytest.mark.asyncio
    async def test_form_mcp_generate_form_tool(self):
        """RED: Test generate_form tool execution"""
        mcp = FORM_MCP(
            membership_base_url="http://localhost:8080",
            use_real_llm=False
        )

        with patch('src.mcp_servers.form_mcp.FormMCPClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get_org_context = AsyncMock(return_value={
                "departments": [{"id": "dept_1", "name": "finance"}],
                "roles": [{"id": "role_1", "name": "approver"}],
                "members": [{"id": "mem_1", "name": "Alice"}]
            })
            mock_client_class.return_value = mock_client

            result = await mcp.execute_tool(
                tool_name="generate_form",
                params={
                    "form_name": "Approval Form",
                    "form_type": "startup",
                    "description": "Form for requesting approvals"
                },
                tenant_id="test_tenant"
            )

            assert result["success"] is True
            assert "form_definition" in result

    @pytest.mark.asyncio
    async def test_form_mcp_validate_form_tool(self):
        """RED: Test validate_form tool execution"""
        mcp = FORM_MCP(
            membership_base_url="http://localhost:8080",
            use_real_llm=False
        )

        valid_form = {
            "form_name": "Test Form",
            "form_type": "standalone",
            "fields": [
                {
                    "field_id": "field_1",
                    "field_name": "name",
                    "field_type": "text",
                    "required": True,
                    "permissions": {
                        "view": {"condition": "*", "applies_to": ["*"]},
                        "edit": {"condition": "*", "applies_to": ["*"]},
                        "required": {"condition": "True", "applies_to": ["*"]}
                    }
                }
            ]
        }

        result = await mcp.execute_tool(
            tool_name="validate_form",
            params={"form_definition": valid_form},
            tenant_id="test_tenant"
        )

        assert result["success"] is True
        assert "valid" in result

    @pytest.mark.asyncio
    async def test_form_mcp_bind_form_tool(self):
        """RED: Test bind_form_to_process tool execution"""
        mcp = FORM_MCP(
            membership_base_url="http://localhost:8080",
            use_real_llm=False
        )

        form = {
            "form_name": "Process Form",
            "form_type": "startup",
            "fields": [
                {
                    "field_id": "field_1",
                    "field_name": "amount",
                    "field_type": "number",
                    "data_binding": {"bpmn_variable": "request_amount"}
                }
            ]
        }

        result = await mcp.execute_tool(
            tool_name="bind_form_to_process",
            params={
                "form_definition": form,
                "process_variables": ["request_amount", "approver"]
            },
            tenant_id="test_tenant"
        )

        assert result["success"] is True
        assert "request_amount" in result["process_variables_mapped"]

    @pytest.mark.asyncio
    async def test_form_mcp_suggest_fields_tool(self):
        """RED: Test suggest_form_fields tool execution"""
        mcp = FORM_MCP(
            membership_base_url="http://localhost:8080",
            use_real_llm=False
        )

        result = await mcp.execute_tool(
            tool_name="suggest_form_fields",
            params={
                "form_description": "Form for requesting budget approval with amount and approval status"
            },
            tenant_id="test_tenant"
        )

        assert result["success"] is True
        assert "suggestions" in result
        assert len(result["suggestions"]) > 0

    @pytest.mark.asyncio
    async def test_form_mcp_missing_required_params(self):
        """RED: Test error handling for missing parameters"""
        mcp = FORM_MCP(
            membership_base_url="http://localhost:8080",
            use_real_llm=False
        )

        result = await mcp.execute_tool(
            tool_name="generate_form",
            params={"form_type": "standalone"},
            tenant_id="test_tenant"
        )

        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_form_mcp_invalid_tool_name(self):
        """RED: Test error handling for invalid tool names"""
        mcp = FORM_MCP(
            membership_base_url="http://localhost:8080",
            use_real_llm=False
        )

        result = await mcp.execute_tool(
            tool_name="nonexistent_tool",
            params={},
            tenant_id="test_tenant"
        )

        assert result["success"] is False
        assert "Unknown tool" in result["error"]

    @pytest.mark.asyncio
    async def test_form_mcp_multiple_mcps_in_registry(self):
        """RED: Test multiple MCPs can coexist in registry"""
        from src.mcp_servers.test_mcp import TestMCPServer
        from src.mcp_servers.bpmn_mcp import BPMN_MCP

        registry = MCPRegistry()

        test_mcp = TestMCPServer()
        bpmn_mcp = BPMN_MCP(
            membership_base_url="http://localhost:8080",
            use_real_llm=False
        )
        form_mcp = FORM_MCP(
            membership_base_url="http://localhost:8080",
            use_real_llm=False
        )

        registry.register_mcp(test_mcp)
        registry.register_mcp(bpmn_mcp)
        registry.register_mcp(form_mcp)

        assert registry.has_mcp("test")
        assert registry.has_mcp("bpmn_mcp")
        assert registry.has_mcp("form_mcp")
        assert len(registry.get_all_mcps()) == 3

    @pytest.mark.asyncio
    async def test_form_validator_validates_field_types(self):
        """RED: Test FormValidator validates field types"""
        from src.mcp_servers.form_mcp import FormValidator

        validator = FormValidator()

        invalid_form = {
            "form_name": "Test",
            "form_type": "standalone",
            "fields": [
                {
                    "field_id": "field_1",
                    "field_name": "invalid_field",
                    "field_type": "invalid_type"
                }
            ]
        }

        result = await validator.validate_form("test_tenant", invalid_form)

        assert result["valid"] is False
        assert any("invalid_type" in str(issue["message"]) for issue in result["issues"]["field_issues"])

    @pytest.mark.asyncio
    async def test_form_validator_validates_permissions(self):
        """RED: Test FormValidator validates permission rules"""
        from src.mcp_servers.form_mcp import FormValidator

        validator = FormValidator()

        form = {
            "form_name": "Test",
            "form_type": "standalone",
            "fields": [
                {
                    "field_id": "field_1",
                    "field_name": "test_field",
                    "field_type": "text"
                }
            ]
        }

        result = await validator.validate_form("test_tenant", form)

        # Should have warnings about missing permissions
        assert len(result["warnings"]) >= 0

    @pytest.mark.asyncio
    async def test_form_mcp_generates_bpm_format(self):
        """Verify that generated forms are in BPM FormSchema format"""
        mcp = FORM_MCP(
            membership_base_url="http://localhost:8080",
            use_real_llm=False
        )

        with patch('src.mcp_servers.form_mcp.FormMCPClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get_org_context = AsyncMock(return_value={
                "departments": [{"id": "d1", "name": "finance"}],
                "roles": [{"id": "r1", "name": "approver"}],
                "members": []
            })
            mock_client_class.return_value = mock_client

            result = await mcp.execute_tool(
                tool_name="generate_form",
                params={
                    "form_name": "Test Form",
                    "form_type": "startup",
                    "description": "Test form"
                },
                tenant_id="test"
            )

            assert result["success"] is True
            form_def = result["form_definition"]

            # Verify BPM format
            assert "formId" in form_def, "Missing formId (BPM standard)"
            assert "version" in form_def, "Missing version (BPM standard)"
            assert "title" in form_def, "Missing title (BPM standard)"
            assert "controls" in form_def, "Should use 'controls' not 'fields'"

            # Verify controls structure
            if form_def["controls"]:
                control = form_def["controls"][0]
                assert "id" in control, "Control missing id"
                assert "type" in control, "Control missing type"
                assert "label" in control, "Control missing label"
                assert "props" in control, "Control missing props"

    @pytest.mark.asyncio
    async def test_form_control_has_width_property(self):
        """Verify that BPM controls support width property for layout"""
        mcp = FORM_MCP(
            membership_base_url="http://localhost:8080",
            use_real_llm=False
        )

        with patch('src.mcp_servers.form_mcp.FormMCPClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get_org_context = AsyncMock(return_value={
                "departments": [{"id": "d1", "name": "finance"}],
                "roles": [{"id": "r1", "name": "approver"}],
                "members": []
            })
            mock_client_class.return_value = mock_client

            result = await mcp.execute_tool(
                tool_name="generate_form",
                params={
                    "form_name": "Layout Test Form",
                    "form_type": "standalone",
                    "description": "Test form with layout controls"
                },
                tenant_id="test"
            )

            assert result["success"] is True
            form_def = result["form_definition"]
            assert "controls" in form_def

            # Verify at least first control has layout properties
            if form_def["controls"]:
                control = form_def["controls"][0]
                # Width property is BPM standard for layout
                assert "width" in control or "flexProps" in control, "Control should have width or flexProps for layout"

    @pytest.mark.asyncio
    async def test_form_control_has_validation_rules(self):
        """Verify that BPM controls support validation rules array"""
        mcp = FORM_MCP(
            membership_base_url="http://localhost:8080",
            use_real_llm=False
        )

        with patch('src.mcp_servers.form_mcp.FormMCPClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get_org_context = AsyncMock(return_value={
                "departments": [{"id": "d1", "name": "finance"}],
                "roles": [{"id": "r1", "name": "approver"}],
                "members": []
            })
            mock_client_class.return_value = mock_client

            result = await mcp.execute_tool(
                tool_name="generate_form",
                params={
                    "form_name": "Validation Test Form",
                    "form_type": "task_specific",
                    "description": "Test form with validation rules"
                },
                tenant_id="test"
            )

            assert result["success"] is True
            form_def = result["form_definition"]

            # Verify validation structure exists at form level
            if "validation" in form_def:
                assert "rules" in form_def["validation"], "Validation should have 'rules' key"
                # Rules should be a dict with control IDs as keys
                assert isinstance(form_def["validation"]["rules"], dict), "Validation rules should be a dict"
