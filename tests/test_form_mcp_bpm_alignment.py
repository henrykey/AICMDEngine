import pytest
from src.mcp_servers.form_mcp import FORM_MCP, FormValidator
from unittest.mock import AsyncMock, patch


class TestFormMCPBPMAlignment:
    """Test FORM-MCP BPM FormSchema alignment"""

    @pytest.mark.asyncio
    async def test_generate_form_produces_valid_bpm_schema(self):
        """Test that generated forms are valid BPM FormSchema"""
        mcp = FORM_MCP(membership_base_url="http://localhost:8080", use_real_llm=False)

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
                    "description": "Test form generation"
                },
                tenant_id="test"
            )

            assert result["success"] is True
            form_def = result["form_definition"]

            # 验证 BPM FormSchema 结构
            assert isinstance(form_def, dict)
            assert "formId" in form_def
            assert "version" in form_def
            assert "title" in form_def
            assert "controls" in form_def

            # 验证 controls 数组
            controls = form_def["controls"]
            assert isinstance(controls, list)

            for control in controls:
                assert "id" in control
                assert "type" in control
                assert "label" in control
                assert "props" in control

    @pytest.mark.asyncio
    async def test_all_37_control_types_supported(self):
        """Test that all 37 control types are supported"""
        validator = FormValidator()

        control_types_37 = [
            # 基础输入
            "text", "textarea", "number", "date", "time", "datetime", "password", "email",
            # 选择
            "radio", "checkbox", "select", "cascader", "tree-select", "switch",
            # 高级
            "richtext", "file-upload", "image-upload", "signature", "rating", "color", "slider",
            # 容器
            "grid", "tabs", "collapse", "flex-container",
            # 特殊
            "subform", "address", "relation", "data-table", "computed-field",
            # 业务
            "member-selector", "role-selector", "org-selector", "process-selector",
            # 展示
            "title", "description", "divider", "html"
        ]

        for control_type in control_types_37:
            assert control_type in validator.all_field_types, f"Control type '{control_type}' not supported"

    @pytest.mark.asyncio
    async def test_nested_controls_validation(self):
        """Test validation of nested controls"""
        validator = FormValidator()

        nested_form = {
            "controls": [
                {
                    "id": "grid-1",
                    "type": "grid",
                    "label": "Grid",
                    "props": {"columns": 2},
                    "children": [
                        {
                            "id": "field-1",
                            "type": "text",
                            "label": "Text",
                            "props": {},
                            "cellIndex": 0
                        }
                    ]
                }
            ]
        }

        result = await validator.validate_form("test", nested_form)
        assert result["valid"] is True
