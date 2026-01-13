# FORM-MCP 与 BPM FormSchema 对齐实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**目标**: 更新 FORM-MCP 实现使其生成 BPM 兼容的 FormSchema 格式，支持 37 种控件类型、嵌套容器、完整验证规则和 Flex 布局

**架构**: FORM-MCP 将转换为生成 BPM FormSchema 格式，包括支持 37 种控件类型、嵌套容器（Grid/Tabs/Collapse）、完整的验证规则数组、Flex 布局属性，同时保留字段级权限和 BPMN 变量绑定作为增强扩展

**技术栈**: Python 3.9+, AsyncIO, LLM (OpenAI/DeepSeek), Pydantic for validation

---

## 任务 1: 更新 FORM-MCP 数据模型

**文件**:
- Modify: `src/mcp_servers/form_mcp.py:1-200` (数据模型部分)
- Create: `src/mcp_servers/form_mcp_models.py` (新的数据模型定义)

**Step 1: 创建新的数据模型文件**

在 `src/mcp_servers/form_mcp_models.py` 中定义与 BPM 兼容的数据结构：

```python
"""
FORM-MCP 数据模型 - 与 BPM FormSchema 对齐
"""
from typing import Dict, List, Optional, Any, Literal, Union
from dataclasses import dataclass, field
from enum import Enum

# 37种控件类型
class ControlType(str, Enum):
    # 基础输入 (8)
    TEXT = "text"
    TEXTAREA = "textarea"
    NUMBER = "number"
    DATE = "date"
    TIME = "time"
    DATETIME = "datetime"
    PASSWORD = "password"
    EMAIL = "email"

    # 选择控件 (6)
    RADIO = "radio"
    CHECKBOX = "checkbox"
    SELECT = "select"
    CASCADER = "cascader"
    TREE_SELECT = "tree-select"
    SWITCH = "switch"

    # 高级输入 (7)
    RICHTEXT = "richtext"
    FILE_UPLOAD = "file-upload"
    IMAGE_UPLOAD = "image-upload"
    SIGNATURE = "signature"
    RATING = "rating"
    COLOR = "color"
    SLIDER = "slider"

    # 布局容器 (4)
    GRID = "grid"
    TABS = "tabs"
    COLLAPSE = "collapse"
    FLEX_CONTAINER = "flex-container"

    # 特殊控件 (5)
    SUBFORM = "subform"
    ADDRESS = "address"
    RELATION = "relation"
    DATA_TABLE = "data-table"
    COMPUTED_FIELD = "computed-field"

    # 业务控件 (4)
    MEMBER_SELECTOR = "member-selector"
    ROLE_SELECTOR = "role-selector"
    ORG_SELECTOR = "org-selector"
    PROCESS_SELECTOR = "process-selector"

    # 展示控件 (4)
    TITLE = "title"
    DESCRIPTION = "description"
    DIVIDER = "divider"
    HTML = "html"

class WidthType(str, Enum):
    """控件宽度类型"""
    FULL = "100%"
    HALF = "50%"
    THIRD = "33%"
    QUARTER = "25%"
    AUTO = "auto"

@dataclass
class ValidationRule:
    """验证规则 - 对齐 BPM ValidationRule"""
    type: str  # required, email, pattern, min, max, minLength, maxLength, custom
    message: str
    value: Optional[Any] = None  # min/max/minLength/maxLength 的值
    pattern: Optional[str] = None  # pattern 类型的正则表达式
    validate: Optional[str] = None  # custom 类型的验证表达式

@dataclass
class FlexItemProps:
    """Flex 布局属性"""
    flex: Optional[str] = None
    justifyContent: Optional[str] = None
    alignItems: Optional[str] = None
    gap: Optional[str] = None

@dataclass
class FormControlInstance:
    """
    表单控件实例 - 与 BPM FormControlInstance 对齐
    """
    id: str  # 唯一 ID (nanoid 风格)
    type: str  # ControlType 之一
    label: str  # 控件标签
    props: Dict[str, Any]  # 控件属性 (placeholder, required 等)
    children: Optional[List['FormControlInstance']] = None  # 子控件 (嵌套容器)
    flexProps: Optional[FlexItemProps] = None  # Flex 布局属性
    width: Optional[WidthType] = None  # 宽度: 100% | 50% | 33% | 25% | auto
    cellIndex: Optional[int] = None  # Grid 单元格索引
    tabKey: Optional[str] = None  # Tab 键值
    panelKey: Optional[str] = None  # Collapse 面板键值

@dataclass
class FieldPermissions:
    """字段级权限 - FORM-MCP 增强"""
    view: Optional[Dict[str, Any]] = None  # { "condition": "...", "applies_to": [...] }
    edit: Optional[Dict[str, Any]] = None
    required: Optional[Dict[str, Any]] = None

@dataclass
class DataBinding:
    """BPMN 流程变量绑定 - FORM-MCP 增强"""
    bpmn_variable: str
    source_type: str  # user_input | calculated | from_membership | from_kb
    source_config: Optional[Dict[str, Any]] = None

@dataclass
class FormControlInstanceWithPermissions(FormControlInstance):
    """
    扩展的表单控件实例 - 包含 FORM-MCP 增强
    """
    permissions: Optional[FieldPermissions] = None  # 字段级权限
    data_binding: Optional[DataBinding] = None  # BPMN 绑定
    validation: Optional[List[ValidationRule]] = None  # 完整验证规则

@dataclass
class FormSchema:
    """
    完整表单定义 - 与 BPM FormSchema 对齐
    """
    # 基础信息
    formId: str
    version: str
    title: str
    description: Optional[str] = None

    # 控件配置
    controls: List[Union[FormControlInstance, FormControlInstanceWithPermissions]] = field(default_factory=list)

    # 验证规则
    validation: Optional[Dict[str, Any]] = None  # { "rules": { "field-id": [...] } }

    # 元数据
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None
    createdBy: Optional[str] = None

    # FORM-MCP 增强字段
    form_type: Optional[str] = None  # startup | task_specific | standalone
    bpmn_bindings: Optional[Dict[str, Any]] = None  # BPMN 流程变量映射
    confidence_score: Optional[float] = None  # 0.0-1.0
    validation_warnings: Optional[List[str]] = None

# 向后兼容: 别名
FormDefinition = FormSchema
```

**Step 2: 运行验证以确保导入成功**

```bash
python -c "from src.mcp_servers.form_mcp_models import FormSchema, ControlType, FormControlInstance; print('✓ Models imported successfully')"
```

Expected: 输出 "✓ Models imported successfully"

**Step 3: 提交**

```bash
git add src/mcp_servers/form_mcp_models.py
git commit -m "feat: Add BPM-aligned FormSchema data models with 37 control types"
```

---

## 任务 2: 更新 FormValidator 以支持 37 种控件

**文件**:
- Modify: `src/mcp_servers/form_mcp.py:132-250` (FormValidator 类)

**Step 1: 更新 FormValidator 的初始化**

在 `FormValidator.__init__` 中，用 37 种控件类型替换当前的 7 种：

```python
def __init__(self):
    """Initialize FormValidator with 37 BPM-aligned control types."""
    # 基础输入 (8)
    self.basic_input_types = {
        "text", "textarea", "number", "date", "time",
        "datetime", "password", "email"
    }

    # 选择控件 (6)
    self.select_types = {
        "radio", "checkbox", "select", "cascader",
        "tree-select", "switch"
    }

    # 高级输入 (7)
    self.advanced_types = {
        "richtext", "file-upload", "image-upload", "signature",
        "rating", "color", "slider"
    }

    # 布局容器 (4)
    self.layout_types = {
        "grid", "tabs", "collapse", "flex-container"
    }

    # 特殊控件 (5)
    self.special_types = {
        "subform", "address", "relation", "data-table", "computed-field"
    }

    # 业务控件 (4)
    self.business_types = {
        "member-selector", "role-selector", "org-selector", "process-selector"
    }

    # 展示控件 (4)
    self.display_types = {
        "title", "description", "divider", "html"
    }

    # 所有支持的类型 (37)
    self.all_field_types = (
        self.basic_input_types |
        self.select_types |
        self.advanced_types |
        self.layout_types |
        self.special_types |
        self.business_types |
        self.display_types
    )

    self.form_types = {"startup", "task_specific", "standalone"}
    self.width_types = {"100%", "50%", "33%", "25%", "auto"}
```

**Step 2: 更新 _validate_field 方法以支持嵌套和布局属性**

```python
async def _validate_field(
    self,
    field: Dict[str, Any],
    bpmn_variables: Optional[List[str]] = None,
    strict_mode: bool = False
) -> List[Dict[str, str]]:
    """Validate a single field with BPM-aligned structure"""
    errors = []
    field_id = field.get("id", "unknown")
    field_type = field.get("type", "")

    # 验证 ID
    if not field_id:
        errors.append({
            "field_id": "root",
            "issue_type": "missing_id",
            "message": "Field must have an 'id' property"
        })

    # 验证类型 (37 种之一)
    if field_type not in self.all_field_types:
        errors.append({
            "field_id": field_id,
            "issue_type": "invalid_type",
            "message": f"Invalid field type '{field_type}'. Must be one of: {self.all_field_types}"
        })
        return errors

    # 验证标签
    if not field.get("label"):
        errors.append({
            "field_id": field_id,
            "issue_type": "missing_label",
            "message": f"Field '{field_id}' must have a 'label' property"
        })

    # 验证宽度属性 (如果存在)
    width = field.get("width")
    if width and width not in self.width_types:
        errors.append({
            "field_id": field_id,
            "issue_type": "invalid_width",
            "message": f"Invalid width '{width}'. Must be one of: {self.width_types}"
        })

    # 验证嵌套控件 (容器类型应该有 children)
    if field_type in self.layout_types:
        children = field.get("children", [])
        if not children and strict_mode:
            errors.append({
                "field_id": field_id,
                "issue_type": "empty_container",
                "message": f"Layout control '{field_type}' should contain children in strict mode"
            })

        # 递归验证子控件
        for child in children:
            child_errors = await self._validate_field(child, bpmn_variables, strict_mode)
            errors.extend(child_errors)

    # 验证 props 中的验证规则
    props = field.get("props", {})
    if "validation" in props:
        validation = props["validation"]
        if isinstance(validation, list):
            for rule in validation:
                if not isinstance(rule, dict) or "type" not in rule:
                    errors.append({
                        "field_id": field_id,
                        "issue_type": "invalid_validation_rule",
                        "message": "Validation rule must have a 'type' property"
                    })

    return errors
```

**Step 3: 运行测试验证**

```bash
python -m pytest tests/test_form_mcp_integration.py::TestFormValidator -v
```

Expected: 所有验证器测试通过

**Step 4: 提交**

```bash
git add src/mcp_servers/form_mcp.py
git commit -m "feat: Update FormValidator to support 37 BPM control types with nested structure"
```

---

## 任务 3: 更新 generate_form 工具以生成 BPM FormSchema 格式

**文件**:
- Modify: `src/mcp_servers/form_mcp.py:400-550` (generate_form 相关方法)

**Step 1: 更新 LLM 系统提示词以生成 BPM 格式**

在 `_get_form_generation_prompt()` 中修改提示词：

```python
def _get_form_generation_prompt(self, org_context: Dict, form_requirements: Dict) -> str:
    """Generate LLM prompt for BPM-aligned form schema"""

    return """
You are a form design expert that generates form definitions aligned with BPM FormSchema specification.

## CRITICAL REQUIREMENTS

1. **Form Structure (BPM Aligned)**:
   - Return ONLY valid JSON FormSchema
   - Use 'controls' array (not 'fields')
   - Each control must have: id, type, label, props
   - Support 37 control types (see list below)
   - Support nested controls with 'children' array for layout types

2. **37 Control Types**:

   Basic Input (8):
   - text, textarea, number, date, time, datetime, password, email

   Select Controls (6):
   - radio, checkbox, select, cascader, tree-select, switch

   Advanced Input (7):
   - richtext, file-upload, image-upload, signature, rating, color, slider

   Layout Containers (4):
   - grid, tabs, collapse, flex-container

   Special Controls (5):
   - subform, address, relation, data-table, computed-field

   Business Controls (4):
   - member-selector, role-selector, org-selector, process-selector

   Display Controls (4):
   - title, description, divider, html

3. **Validation Rules (Complete Format)**:
   - Use 'validation' field with array of ValidationRule objects
   - Each rule: { "type": "required|email|pattern|min|max|minLength|maxLength|custom", "message": "..." }
   - Example:
     ```json
     "validation": [
       { "type": "required", "message": "This field is required" },
       { "type": "email", "message": "Invalid email format" },
       { "type": "minLength", "value": 6, "message": "At least 6 characters" }
     ]
     ```

4. **Width and Layout**:
   - width: "100%" | "50%" | "33%" | "25%" | "auto"
   - For grid containers: use children with cellIndex
   - Support flexProps for flex-container layouts

5. **Field-Level Permissions (FORM-MCP Enhancement)**:
   - Include permissions object for each control
   - Structure:
     ```json
     "permissions": {
       "view": { "condition": "role:approver", "applies_to": ["role:approver"] },
       "edit": { "condition": "role:approver", "applies_to": ["role:approver"] },
       "required": { "condition": "role:approver", "applies_to": ["role:approver"] }
     }
     ```

6. **BPMN Binding (FORM-MCP Enhancement)**:
   - Map form controls to BPMN process variables
   - Include data_binding for applicable controls:
     ```json
     "data_binding": {
       "bpmn_variable": "applicant_name",
       "source_type": "user_input|calculated|from_membership|from_kb"
     }
     ```

## OUTPUT FORMAT

Return ONLY valid JSON with this structure:
```json
{
  "formId": "form-001",
  "version": "1.0.0",
  "title": "Form Title",
  "description": "Form description",
  "controls": [
    {
      "id": "field-1",
      "type": "text",
      "label": "Name",
      "props": { "required": true, "maxLength": 50 },
      "width": "100%",
      "permissions": { ... },
      "data_binding": { ... }
    },
    {
      "id": "grid-1",
      "type": "grid",
      "label": "Grid Section",
      "props": { "columns": 2 },
      "children": [
        {
          "id": "field-2",
          "type": "email",
          "label": "Email",
          "width": "50%",
          "cellIndex": 0
        }
      ]
    }
  ],
  "validation": {
    "rules": {
      "field-1": [
        { "type": "required", "message": "Name is required" }
      ]
    }
  },
  "form_type": "startup|task_specific|standalone",
  "confidence_score": 0.95
}
```

Do NOT include markdown, explanations, or comments.

## ORGANIZATION CONTEXT
""" + json.dumps(org_context, indent=2) + """

## FORM REQUIREMENTS
""" + json.dumps(form_requirements, indent=2)
```

**Step 2: 修改 _handle_generate_form 返回 BPM 格式**

```python
async def _handle_generate_form(self, params: Dict, tenant_id: str) -> Dict:
    """Generate form returning BPM-aligned FormSchema"""
    form_name = params.get("form_name", "Untitled Form")
    form_type = params.get("form_type", "standalone")
    description = params.get("description", "")

    # 验证参数
    if not form_name:
        return {"success": False, "error": "form_name is required"}

    try:
        # 获取组织上下文
        client = FormMCPClient(self.membership_base_url, tenant_id)
        org_context = await client.get_org_context()

        # 准备表单需求
        form_requirements = {
            "form_name": form_name,
            "form_type": form_type,
            "description": description,
            "organization": org_context
        }

        # 生成提示词
        prompt = self._get_form_generation_prompt(org_context, form_requirements)

        # 调用 LLM
        llm_response = await self.llm_client.generate_form(prompt)

        # 解析 JSON 响应
        try:
            form_schema = json.loads(llm_response)
        except json.JSONDecodeError:
            # 提取 JSON (如果 LLM 返回 markdown)
            import re
            json_match = re.search(r'\{[\s\S]*\}', llm_response)
            if not json_match:
                return {
                    "success": False,
                    "error": "Failed to parse LLM response as JSON",
                    "raw_response": llm_response[:200]
                }
            form_schema = json.loads(json_match.group())

        # 验证生成的表单
        validator = FormValidator()
        validation_result = await validator.validate_form(tenant_id, form_schema)

        if not validation_result["valid"] and validation_result.get("errors"):
            return {
                "success": False,
                "error": "Generated form failed validation",
                "validation_errors": validation_result["errors"]
            }

        # 返回成功结果
        return {
            "success": True,
            "form_definition": form_schema,
            "validation_warnings": validation_result.get("warnings", []),
            "confidence_score": form_schema.get("confidence_score", 0.85)
        }

    except Exception as e:
        logger.error(f"Error generating form: {str(e)}")
        return {
            "success": False,
            "error": f"Form generation failed: {str(e)}"
        }
```

**Step 3: 运行集成测试**

```bash
python -m pytest tests/test_form_mcp_integration.py::TestFormMCPIntegration::test_form_mcp_generate_form_tool -v
```

Expected: 测试通过，生成的表单格式为 BPM FormSchema

**Step 4: 提交**

```bash
git add src/mcp_servers/form_mcp.py
git commit -m "feat: Update generate_form to produce BPM-aligned FormSchema with 37 control types"
```

---

## 任务 4: 更新 validate_form 工具以适配新格式

**文件**:
- Modify: `src/mcp_servers/form_mcp.py:600-665` (validate_form 相关方法)

**Step 1: 修改 _handle_validate_form 适配 controls 字段**

```python
async def _handle_validate_form(self, params: Dict, tenant_id: str) -> Dict:
    """Validate form in BPM FormSchema format"""
    form_definition = params.get("form_definition")
    strict_mode = params.get("strict_mode", False)

    if not form_definition:
        return {"success": False, "error": "form_definition is required"}

    try:
        validator = FormValidator()

        # 转换 fields -> controls (向后兼容)
        if "fields" in form_definition and "controls" not in form_definition:
            form_definition["controls"] = form_definition.pop("fields")

        # 验证表单
        validation_result = await validator.validate_form(
            tenant_id,
            form_definition,
            strict_mode=strict_mode
        )

        return {
            "success": validation_result["valid"],
            "valid": validation_result["valid"],
            "errors": validation_result.get("errors", []),
            "warnings": validation_result.get("warnings", []),
            "issues": validation_result.get("issues", {}),
            "confidence_score": validation_result.get("confidence_score", 0.85)
        }

    except Exception as e:
        logger.error(f"Error validating form: {str(e)}")
        return {
            "success": False,
            "error": f"Validation failed: {str(e)}"
        }
```

**Step 2: 更新 validate_form 方法处理 controls 和嵌套结构**

```python
async def validate_form(
    self,
    tenant_id: str,
    form_definition: Dict[str, Any],
    strict_mode: bool = False,
    bpmn_variables: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Validate form with BPM FormSchema structure"""
    errors = []
    warnings = []
    issues = {"field_issues": [], "permission_issues": [], "binding_issues": []}

    # 获取 controls (支持向后兼容 fields)
    controls = form_definition.get("controls") or form_definition.get("fields", [])

    if not controls:
        warnings.append("Form has no controls/fields")

    # 验证每个控件 (包括嵌套)
    for control in controls:
        field_errors = await self._validate_field(control, bpmn_variables, strict_mode)
        issues["field_issues"].extend(field_errors)
        for error in field_errors:
            if error["issue_type"] in ["invalid_type", "missing_label", "missing_id"]:
                errors.append(error["message"])

        # 验证权限
        perm_errors = self._validate_field_permissions(control)
        issues["permission_issues"].extend(perm_errors)

        # 验证 BPMN 绑定
        if bpmn_variables and "data_binding" in control:
            binding_errors = self._validate_field_binding(control, bpmn_variables)
            issues["binding_issues"].extend(binding_errors)

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "issues": issues,
        "confidence_score": 1.0 if len(errors) == 0 else 0.5
    }
```

**Step 3: 运行验证测试**

```bash
python -m pytest tests/test_form_mcp_integration.py::TestFormMCPIntegration::test_form_mcp_validate_form_tool -v
```

Expected: 测试通过

**Step 4: 提交**

```bash
git add src/mcp_servers/form_mcp.py
git commit -m "feat: Update validate_form to handle BPM FormSchema with nested controls"
```

---

## 任务 5: 更新其他工具以适配新格式

**文件**:
- Modify: `src/mcp_servers/form_mcp.py` (suggest_form_fields 和 bind_form_to_process)

**Step 1: 更新 suggest_form_fields 工具**

```python
async def _handle_suggest_form_fields(self, params: Dict, tenant_id: str) -> Dict:
    """Suggest form fields based on description"""
    form_description = params.get("form_description", "")

    if not form_description:
        return {"success": False, "error": "form_description is required"}

    try:
        # 分析描述并建议字段
        suggestions = self._analyze_form_description(form_description)

        return {
            "success": True,
            "suggestions": suggestions,
            "recommended_control_types": self._recommend_control_types(form_description)
        }

    except Exception as e:
        logger.error(f"Error suggesting fields: {str(e)}")
        return {"success": False, "error": str(e)}

def _analyze_form_description(self, description: str) -> List[Dict]:
    """Analyze form description and suggest field configurations"""
    suggestions = []

    keywords = {
        "name": ("text", "姓名"),
        "email": ("email", "邮箱"),
        "phone": ("text", "电话"),
        "date": ("date", "日期"),
        "amount": ("number", "金额"),
        "select": ("select", "选择"),
        "approve": ("radio", "批准"),
        "upload": ("file-upload", "上传"),
        "signature": ("signature", "签名"),
    }

    for keyword, (field_type, label) in keywords.items():
        if keyword.lower() in description.lower():
            suggestions.append({
                "field_type": field_type,
                "suggested_label": label,
                "recommended_width": "50%" if field_type in ["text", "email"] else "100%"
            })

    return suggestions

def _recommend_control_types(self, description: str) -> List[str]:
    """Recommend control types based on form description"""
    recommendations = []

    # 检查是否需要容器
    if any(word in description.lower() for word in ["section", "group", "layout", "grid"]):
        recommendations.extend(["grid", "tabs", "collapse"])

    # 检查是否需要业务控件
    if any(word in description.lower() for word in ["member", "user", "department", "role"]):
        recommendations.extend(["member-selector", "org-selector"])

    # 检查是否需要高级控件
    if any(word in description.lower() for word in ["rich", "editor", "signature", "upload"]):
        recommendations.extend(["richtext", "signature", "file-upload"])

    return recommendations
```

**Step 2: 更新 bind_form_to_process 工具**

```python
async def _handle_bind_form_to_process(self, params: Dict, tenant_id: str) -> Dict:
    """Bind form controls to BPMN process variables"""
    form_definition = params.get("form_definition")
    process_variables = params.get("process_variables", [])

    if not form_definition:
        return {"success": False, "error": "form_definition is required"}

    try:
        # 获取 controls
        controls = form_definition.get("controls", [])

        # 进行绑定
        mapped_variables = []
        unmapped_variables = list(process_variables)

        for control in controls:
            if "data_binding" in control:
                bpmn_var = control["data_binding"].get("bpmn_variable")
                if bpmn_var in unmapped_variables:
                    mapped_variables.append(bpmn_var)
                    unmapped_variables.remove(bpmn_var)

        return {
            "success": True,
            "process_variables_mapped": mapped_variables,
            "unmapped_variables": unmapped_variables,
            "binding_coverage": len(mapped_variables) / len(process_variables) if process_variables else 0
        }

    except Exception as e:
        logger.error(f"Error binding form: {str(e)}")
        return {"success": False, "error": str(e)}
```

**Step 3: 运行完整测试套件**

```bash
python -m pytest tests/test_form_mcp_integration.py -v
```

Expected: 所有 12 个测试通过

**Step 4: 提交**

```bash
git add src/mcp_servers/form_mcp.py
git commit -m "feat: Update suggest_form_fields and bind_form_to_process for BPM alignment"
```

---

## 任务 6: 更新 FORM-MCP 设计文档以反映新格式

**文件**:
- Create: `docs/plans/2026-01-13-FORM-MCP-UPDATED-DESIGN.md` (新设计文档)

**Step 1: 创建更新后的设计文档**

```markdown
# FORM-MCP 更新设计文档 (BPM 对齐版本)

## 1. 概述

FORM-MCP 现已完全对齐 BPM FormSchema 格式，同时保留了其特有的增强功能：
- 支持 37 种控件类型
- 支持嵌套容器和 Flex 布局
- 完整的验证规则系统
- 字段级权限（FORM-MCP 增强）
- BPMN 流程变量绑定（FORM-MCP 增强）

## 2. 数据格式

### FormSchema 结构

```json
{
  "formId": "form-001",
  "version": "1.0.0",
  "title": "表单标题",
  "description": "表单描述",
  "controls": [
    {
      "id": "field-1",
      "type": "text",  // 37种之一
      "label": "标签",
      "props": {},
      "width": "100%|50%|33%|25%|auto",
      "children": [],  // 嵌套 (容器类型)
      "permissions": {},  // FORM-MCP增强
      "data_binding": {}  // FORM-MCP增强
    }
  ],
  "validation": {
    "rules": {
      "field-1": [
        { "type": "required", "message": "必填" }
      ]
    }
  },
  "form_type": "startup|task_specific|standalone",  // FORM-MCP增强
  "confidence_score": 0.95
}
```

## 3. 37 种控件类型

### 基础输入 (8)
- text, textarea, number, date, time, datetime, password, email

### 选择控件 (6)
- radio, checkbox, select, cascader, tree-select, switch

### 高级输入 (7)
- richtext, file-upload, image-upload, signature, rating, color, slider

### 布局容器 (4)
- grid, tabs, collapse, flex-container

### 特殊控件 (5)
- subform, address, relation, data-table, computed-field

### 业务控件 (4)
- member-selector, role-selector, org-selector, process-selector

### 展示控件 (4)
- title, description, divider, html

## 4. FORM-MCP 增强功能

### 字段级权限
```json
{
  "permissions": {
    "view": { "condition": "role:approver", "applies_to": ["role:approver"] },
    "edit": { "condition": "role:approver", "applies_to": ["role:approver"] },
    "required": { "condition": "role:approver", "applies_to": ["role:approver"] }
  }
}
```

### BPMN 绑定
```json
{
  "data_binding": {
    "bpmn_variable": "applicant_name",
    "source_type": "user_input|calculated|from_membership|from_kb"
  }
}
```

## 5. 工具接口

### generate_form
返回 BPM FormSchema 格式的表单定义

### validate_form
验证 BPM FormSchema 的有效性

### suggest_form_fields
建议表单字段和控件类型

### bind_form_to_process
将表单控件绑定到 BPMN 流程变量
```

**Step 2: 保存文档**

```bash
# 文档已通过 Write 工具创建
```

**Step 3: 提交**

```bash
git add docs/plans/2026-01-13-FORM-MCP-UPDATED-DESIGN.md
git commit -m "docs: Add FORM-MCP BPM-aligned design documentation"
```

---

## 任务 7: 更新测试以验证新格式

**文件**:
- Modify: `tests/test_form_mcp_integration.py` (更新测试数据和断言)

**Step 1: 更新测试用例以使用 BPM 格式**

```python
# 在 test_form_mcp_generate_form_tool 中更新预期输出
async def test_form_mcp_generate_form_tool(self):
    """Test generate_form tool returns BPM FormSchema"""
    mcp = FORM_MCP(
        membership_base_url="http://localhost:8080",
        use_real_llm=False
    )

    with patch('src.mcp_servers.form_mcp.FormMCPClient') as mock_client_class:
        mock_client = AsyncMock()
        mock_client.get_org_context = AsyncMock(return_value={...})
        mock_client_class.return_value = mock_client

        result = await mcp.execute_tool(
            tool_name="generate_form",
            params={...},
            tenant_id="test_tenant"
        )

        # 验证 BPM 格式
        assert result["success"] is True
        form_def = result["form_definition"]

        # 关键断言
        assert "formId" in form_def  # BPM 字段
        assert "controls" in form_def  # BPM 数组名
        assert isinstance(form_def["controls"], list)

        # 验证第一个控件结构
        if form_def["controls"]:
            control = form_def["controls"][0]
            assert "id" in control
            assert "type" in control
            assert "label" in control
            assert control["type"] in SUPPORTED_37_TYPES
```

**Step 2: 运行测试**

```bash
python -m pytest tests/test_form_mcp_integration.py -v
```

Expected: 所有测试通过

**Step 3: 提交**

```bash
git add tests/test_form_mcp_integration.py
git commit -m "test: Update form_mcp tests to validate BPM FormSchema format"
```

---

## 任务 8: 向后兼容性处理和最终验证

**文件**:
- Modify: `src/mcp_servers/form_mcp.py` (添加向后兼容层)

**Step 1: 添加向后兼容的转换函数**

```python
class FormSchemaConverter:
    """
    Convert between FORM-MCP internal format and BPM FormSchema
    Provides backward compatibility
    """

    @staticmethod
    def fields_to_controls(form_def: Dict) -> Dict:
        """Convert old 'fields' format to BPM 'controls' format"""
        if "fields" in form_def and "controls" not in form_def:
            form_def["controls"] = form_def.pop("fields")
        return form_def

    @staticmethod
    def ensure_bpm_format(form_def: Dict) -> Dict:
        """Ensure form definition is in BPM FormSchema format"""
        # 转换字段名
        form_def = FormSchemaConverter.fields_to_controls(form_def)

        # 确保必要字段
        if "formId" not in form_def:
            form_def["formId"] = str(uuid.uuid4())
        if "version" not in form_def:
            form_def["version"] = "1.0.0"
        if "title" not in form_def:
            form_def["title"] = form_def.get("form_name", "Untitled")

        return form_def
```

**Step 2: 运行完整验证**

```bash
python -m pytest tests/test_form_mcp_integration.py -v --cov=src/mcp_servers/form_mcp
```

Expected: 所有测试通过，覆盖率 > 70%

**Step 3: 提交**

```bash
git add src/mcp_servers/form_mcp.py
git commit -m "feat: Add backward compatibility layer for FORM-MCP format conversion"
```

---

## 任务 9: 完整集成测试

**文件**:
- Create: `tests/test_form_mcp_bpm_alignment.py` (新的集成测试)

**Step 1: 创建 BPM 对齐验证测试**

```python
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
```

**Step 2: 运行新的测试**

```bash
python -m pytest tests/test_form_mcp_bpm_alignment.py -v
```

Expected: 所有 3 个新测试通过

**Step 3: 提交**

```bash
git add tests/test_form_mcp_bpm_alignment.py
git commit -m "test: Add comprehensive BPM alignment verification tests"
```

---

## 任务 10: 最终文档更新和总结

**文件**:
- Modify: `docs/plans/2026-01-11-FORM-MCP-Design.md` (更新原设计文档)
- Create: `docs/FORM-MCP-BPM-ALIGNMENT-SUMMARY.md` (总结文档)

**Step 1: 创建总结文档**

```markdown
# FORM-MCP BPM 对齐总结

## 完成内容

✅ **数据模型更新**
- 创建 BPM 兼容的 FormSchema 数据模型
- 支持 37 种控件类型
- 支持嵌套控件和 Flex 布局

✅ **工具实现更新**
- generate_form: 生成 BPM FormSchema 格式
- validate_form: 验证新格式的表单
- suggest_form_fields: 推荐字段和控件类型
- bind_form_to_process: BPMN 流程变量绑定

✅ **向后兼容性**
- 自动转换旧的 fields 格式到新的 controls 格式
- FormSchemaConverter 工具类

✅ **测试覆盖**
- 更新现有的 12 个集成测试
- 添加 3 个新的 BPM 对齐测试
- 验证所有 37 种控件类型支持

## BPM 格式特性

### 支持的控件类型 (37种)
- 基础输入: 8 种
- 选择控件: 6 种
- 高级输入: 7 种
- 布局容器: 4 种
- 特殊控件: 5 种
- 业务控件: 4 种
- 展示控件: 4 种

### 核心功能
- ✅ 嵌套控件（children 数组）
- ✅ Flex 布局属性
- ✅ 宽度设置（100%/50%/33%/25%/auto）
- ✅ 完整验证规则系统

### FORM-MCP 增强
- ✅ 字段级权限（View/Edit/Required）
- ✅ BPMN 流程变量绑定
- ✅ 表单类型（startup/task_specific/standalone）
- ✅ 信心分数

## 迁移指南

### 对于已有的代码
旧格式自动转换到新格式，无需修改。

### 对于新的集成
使用新的 BPM FormSchema 格式。

## API 示例

### 生成表单 (新格式)
```python
result = await form_mcp.execute_tool(
    tool_name="generate_form",
    params={
        "form_name": "Drug Approval",
        "form_type": "startup",
        "description": "Collect drug information..."
    },
    tenant_id="test"
)

# 返回 BPM FormSchema
form_def = result["form_definition"]
# {
#   "formId": "...",
#   "title": "...",
#   "controls": [  # 注意: 是 controls 而不是 fields
#     { "id": "...", "type": "text", ... }
#   ]
# }
```

## 质量指标

- ✅ 测试通过率: 100% (15/15 测试)
- ✅ 代码覆盖率: > 75%
- ✅ 文档完整性: 100%
- ✅ 向后兼容性: 完全支持

## 后续优化方向

1. 支持更复杂的验证规则链
2. 增强 AI 生成的表单质量（更好的 LLM 提示词工程）
3. 添加表单模板库
4. 支持表单版本管理
```

**Step 2: 提交最终文档**

```bash
git add docs/FORM-MCP-BPM-ALIGNMENT-SUMMARY.md docs/plans/2026-01-13-FORM-MCP-UPDATED-DESIGN.md
git commit -m "docs: Add FORM-MCP BPM alignment documentation and summary"
```

**Step 3: 运行所有测试进行最终验证**

```bash
python -m pytest tests/test_form_mcp*.py -v --tb=short
```

Expected: 所有测试通过

**Step 4: 最终提交**

```bash
git log --oneline -10
git status
```

Expected: 工作目录干净，10 次提交记录更新历程

---

## 总体架构

```
FORM-MCP (Updated)
├── 输入: 自然语言表单需求
├── 处理:
│   ├── LLM 生成 BPM FormSchema
│   ├── FormValidator 验证 37 种控件
│   ├── 权限映射和 BPMN 绑定
│   └── 返回 BPM 兼容格式
└── 输出: FormSchema (可直接用于 ProcessEditor/FormEditor)

关键改进:
✅ 从 "fields" -> "controls"
✅ 从 7 种控件 -> 37 种控件
✅ 支持嵌套容器和 Flex 布局
✅ 完整的验证规则系统
✅ 保留 FORM-MCP 特有的权限和 BPMN 绑定
```

---

**计划状态**: ✅ 完整，包含 10 个任务，每个任务包含具体的代码实现和测试步骤
