import pytest
from src.mcp_servers.form_mcp import FormValidator
from unittest.mock import AsyncMock, patch


class TestFormMCPBPMAlignment:
    """Test FORM-MCP BPM FormSchema alignment"""

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
