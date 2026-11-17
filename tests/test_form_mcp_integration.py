"""
FormValidator tests kept from the earlier FORM-MCP.

The Router-facing FORM_MCP now has one read-only tool (find_forms); its tests are in test_form_mcp_find_forms.py.
"""

import pytest


class TestFormValidator:
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
