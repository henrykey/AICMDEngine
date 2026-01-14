"""
FORM-MCP Server Implementation

Generates dynamic forms tightly integrated with BPMN processes and Membership's
organizational structure.

Key Features:
- Natural language form generation via LLM
- Field-level permission mapping from Membership RBAC
- BPMN process variable binding
- Form validation with permission checks
- Knowledge Base integration for field templates
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
import logging
import aiohttp
import json
import uuid
import re
from datetime import datetime

from src.core.config import settings
from src.mcp.base_server import BaseMCPServer
from src.services.llm_client import llm_client
from src.mcp_servers.llm_integration import (
    get_llm_client,
    LLMClientFactory,
    MockLLMClient,
    RealLLMClient,
    extract_json_from_response
)

logger = logging.getLogger(__name__)


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


@dataclass
class OrgContext:
    """Organizational context: departments, roles, members"""
    departments: List[Dict[str, Any]]
    roles: List[Dict[str, Any]]
    members: List[Dict[str, Any]]


class FormMCPClient:
    """
    Client for interacting with Membership API and fetching organizational context.
    Provides form-specific org data for permission mapping.
    """

    def __init__(self, base_url: str, tenant_id: str, auth_token: Optional[str] = None):
        """Initialize FormMCPClient."""
        self.base_url = base_url
        self.tenant_id = tenant_id
        self.auth_token = auth_token
        self._cache = {}
        self._cache_ttl = 300

    async def get_org_context(self) -> Dict[str, List[Dict[str, Any]]]:
        """Fetch organizational context for form generation."""
        departments = await self._fetch_departments()
        roles = await self._fetch_roles()
        members = await self._fetch_members()

        return {
            "departments": departments,
            "roles": roles,
            "members": members
        }

    async def validate_form_permissions(
        self,
        form_definition: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate form permissions against organizational structure."""
        org_context = await self.get_org_context()
        errors = []
        warnings = []

        # Validate field permissions reference valid roles/departments
        for field in form_definition.get("fields", []):
            field_perms = field.get("permissions", {})

            for perm_type in ["view", "edit", "required"]:
                perm = field_perms.get(perm_type, {})
                applies_to = perm.get("applies_to", [])

                for entity in applies_to:
                    if entity == "*":
                        continue

                    # Check if entity exists in org
                    found = False
                    for role in org_context["roles"]:
                        if role["name"] == entity:
                            found = True
                            break
                    for dept in org_context["departments"]:
                        if dept["name"] == entity:
                            found = True
                            break

                    if not found:
                        errors.append(f"Field '{field['field_name']}': Unknown role/department '{entity}' in {perm_type} permissions")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings
        }

    async def _fetch_departments(self) -> List[Dict[str, Any]]:
        """Fetch departments from Membership API."""
        # Mock implementation
        return [
            {"id": "dept_001", "name": "finance", "description": "Finance Department"},
            {"id": "dept_002", "name": "hr", "description": "Human Resources"},
            {"id": "dept_003", "name": "engineering", "description": "Engineering"},
        ]

    async def _fetch_roles(self) -> List[Dict[str, Any]]:
        """Fetch roles from Membership API."""
        # Mock implementation
        return [
            {"id": "role_001", "name": "approver", "description": "Can approve requests"},
            {"id": "role_002", "name": "reviewer", "description": "Can review submissions"},
            {"id": "role_003", "name": "manager", "description": "Manager role"},
        ]

    async def _fetch_members(self) -> List[Dict[str, Any]]:
        """Fetch members from Membership API."""
        # Mock implementation
        return [
            {"id": "mem_001", "name": "Alice", "roles": ["approver"], "departments": ["finance"]},
            {"id": "mem_002", "name": "Bob", "roles": ["reviewer"], "departments": ["engineering"]},
        ]


class FormValidator:
    """
    Validates form definitions, field constraints, and permission rules.
    """

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
        issues = {
            "field_issues": [],
            "permission_issues": [],
            "binding_issues": []
        }

        # Get controls (support backward compatible fields)
        controls = form_definition.get("controls") or form_definition.get("fields", [])

        if not controls:
            warnings.append("Form has no controls/fields")

        # Validate each control (including nested)
        for control in controls:
            field_errors = await self._validate_field(control, bpmn_variables, strict_mode)
            issues["field_issues"].extend(field_errors)
            for error in field_errors:
                if error["issue_type"] in ["invalid_type", "missing_label", "missing_id"]:
                    errors.append(error["message"])

            # Validate permissions
            perm_errors = self._validate_field_permissions(control)
            issues["permission_issues"].extend(perm_errors)

            # Validate BPMN binding
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

    async def _validate_field(
        self,
        field: Dict[str, Any],
        bpmn_variables: Optional[List[str]] = None,
        strict_mode: bool = False
    ) -> List[Dict[str, str]]:
        """Validate a single field with BPM-aligned structure"""
        errors = []

        # Support both old (field_id, field_type, field_name) and new (id, type, label) formats
        field_id = field.get("id") or field.get("field_id", "unknown")
        field_type = field.get("type") or field.get("field_type", "")
        field_label = field.get("label") or field.get("field_name", "")

        # 验证 ID
        if not field_id or field_id == "unknown":
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
        if not field_label:
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

    def _validate_field_permissions(self, field: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Validate field permission rules."""
        issues = []
        perms = field.get("permissions", {})

        for perm_type in ["view", "edit", "required"]:
            if perm_type not in perms:
                issues.append({
                    "field_id": field.get("field_id"),
                    "issue": f"Missing {perm_type} permission rule"
                })

        return issues

    def _validate_field_binding(
        self,
        field: Dict[str, Any],
        bpmn_variables: List[str]
    ) -> List[Dict[str, Any]]:
        """Validate BPMN variable binding."""
        issues = []
        binding = field.get("data_binding", {})
        bpmn_var = binding.get("bpmn_variable")

        if bpmn_var and bpmn_var not in bpmn_variables:
            issues.append({
                "field_id": field.get("field_id"),
                "issue": f"BPMN variable '{bpmn_var}' not found in process"
            })

        return issues


# Note: MockLLMClient and RealLLMClient are now imported from llm_integration module


async def generate_form(
    tenant_id: str,
    form_name: str,
    form_type: str,
    description: str,
    org_context: Dict[str, Any],
    use_real_llm: bool = False
) -> Dict[str, Any]:
    """Generate form definition from natural language description."""
    # Initialize LLM client using unified module
    form_llm_client = get_llm_client(use_real_llm=use_real_llm)

    # Build system prompt
    system_prompt = f"""You are a form generation expert. Generate form definitions in JSON format.
Form generation requirements:
1. Create fields that match the natural language description
2. Assign field types (text, textarea, number, select, checkbox, date, file)
3. Include field-level permissions (view, edit, required)
4. Map permissions to organizational roles: {', '.join(r['name'] for r in org_context['org_context'].get('roles', []))}
5. Include BPMN variable bindings if applicable
6. Return only valid JSON, no explanation"""

    # Build user prompt
    org_depts = ', '.join(d['name'] for d in org_context['org_context'].get('departments', []))
    org_roles = ', '.join(r['name'] for r in org_context['org_context'].get('roles', []))

    user_prompt = f"""Generate form definition for:
Form Name: {form_name}
Form Type: {form_type}
Description: {description}

Organization Context:
- Departments: {org_depts}
- Roles: {org_roles}

Requirements:
1. Generate 3-5 fields appropriate for this form
2. Ensure permission rules follow org structure
3. Include validation rules where appropriate
4. Return complete JSON form definition"""

    # Call LLM
    response = await form_llm_client.send_prompt(system_prompt, user_prompt)

    # Parse response using unified extraction utility
    form_def = extract_json_from_response(response)

    if form_def is None:
        # Fallback to mock client response
        mock_client = MockLLMClient()
        mock_response = await mock_client.send_prompt("", "")
        form_def = json.loads(mock_response)

    return {
        "success": True,
        "form_definition": form_def,
        "confidence_score": form_def.get("confidence_score", 0.85),
        "validation_warnings": []
    }


class FORM_MCP(BaseMCPServer):
    """
    MCP Server for dynamic form generation and validation.

    Provides tools for:
    - Generating forms from natural language
    - Validating form definitions and permissions
    - Binding forms to BPMN processes
    - Suggesting form fields based on context
    """

    def __init__(
        self,
        membership_base_url: str = None,
        use_real_llm: bool = False,
        kb_base_url: str = None
    ):
        """Initialize FORM-MCP server."""
        super().__init__(name="form_mcp", version="1.0.0")

        self.membership_base_url = membership_base_url or settings.membership_service_url
        self.kb_base_url = kb_base_url or settings.kb_base_url
        self.use_real_llm = use_real_llm

        # Initialize components
        self.validator = FormValidator()
        self.membership_client = None

        logger.info(f"FORM-MCP initialized: membership_url={self.membership_base_url}, use_real_llm={use_real_llm}")

    async def list_tools(self, tenant_id: str) -> List[Dict[str, Any]]:
        """List available FORM tools."""
        return [
            {
                "name": "generate_form",
                "description": "Generate form definition from natural language requirement",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "form_name": {
                            "type": "string",
                            "description": "Name of the form (e.g., 'Drug Approval Application')"
                        },
                        "form_type": {
                            "type": "string",
                            "enum": ["startup", "task_specific", "standalone"],
                            "description": "Type of form"
                        },
                        "description": {
                            "type": "string",
                            "description": "Natural language form description"
                        },
                        "context": {
                            "type": "object",
                            "description": "Optional context including BPMN binding"
                        }
                    },
                    "required": ["form_name", "form_type", "description"]
                }
            },
            {
                "name": "validate_form",
                "description": "Validate form definition and permission rules",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "form_definition": {
                            "type": "object",
                            "description": "Complete form definition to validate"
                        },
                        "strict_mode": {
                            "type": "boolean",
                            "description": "Apply strict validation"
                        }
                    },
                    "required": ["form_definition"]
                }
            },
            {
                "name": "bind_form_to_process",
                "description": "Bind form fields to BPMN process variables",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "form_definition": {
                            "type": "object",
                            "description": "Form definition"
                        },
                        "process_variables": {
                            "type": "array",
                            "description": "List of BPMN process variables"
                        }
                    },
                    "required": ["form_definition", "process_variables"]
                }
            },
            {
                "name": "suggest_form_fields",
                "description": "Suggest form fields based on context",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "form_description": {
                            "type": "string",
                            "description": "Description of form requirements"
                        },
                        "context": {
                            "type": "object",
                            "description": "Optional context"
                        }
                    },
                    "required": ["form_description"]
                }
            }
        ]

    async def execute_tool(
        self,
        tool_name: str,
        params: Dict[str, Any],
        tenant_id: str
    ) -> Dict[str, Any]:
        """Execute a FORM tool."""
        try:
            if tool_name == "generate_form":
                return await self._handle_generate_form(params, tenant_id)
            elif tool_name == "validate_form":
                return await self._handle_validate_form(params, tenant_id)
            elif tool_name == "bind_form_to_process":
                return await self._handle_bind_form_to_process(params, tenant_id)
            elif tool_name == "suggest_form_fields":
                return await self._handle_suggest_form_fields(params, tenant_id)
            else:
                return {"success": False, "error": f"Unknown tool: {tool_name}"}
        except Exception as e:
            logger.error(f"Error executing tool '{tool_name}': {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def _get_form_generation_prompt(self, org_context: Dict, form_requirements: Dict) -> str:
        """Generate LLM prompt for BPM-aligned form schema"""

        return """You are a form design expert that generates form definitions aligned with BPM FormSchema specification.

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

    async def _handle_generate_form(
        self,
        params: Dict[str, Any],
        tenant_id: str
    ) -> Dict[str, Any]:
        """Generate form returning BPM-aligned FormSchema"""
        form_name = params.get("form_name", "")
        form_type = params.get("form_type", "standalone")
        description = params.get("description", "")

        # Validate parameters
        if not form_name:
            return {"success": False, "error": "form_name is required"}

        try:
            # Get organizational context
            if not self.membership_client:
                self.membership_client = FormMCPClient(
                    self.membership_base_url,
                    tenant_id
                )

            org_context = await self.membership_client.get_org_context()

            # Prepare form requirements
            form_requirements = {
                "form_name": form_name,
                "form_type": form_type,
                "description": description,
                "organization": org_context
            }

            # Generate prompt
            prompt = self._get_form_generation_prompt(org_context, form_requirements)

            # Call LLM using unified module
            form_llm_client = get_llm_client(use_real_llm=self.use_real_llm)
            llm_response = await form_llm_client.send_prompt(
                system_prompt="You are a form generation expert. Generate form definitions in BPM FormSchema JSON format.",
                user_prompt=prompt
            )

            # Parse JSON response using unified extraction utility
            form_schema = extract_json_from_response(llm_response)

            if form_schema is None:
                return {
                    "success": False,
                    "error": "Failed to parse LLM response as JSON",
                    "raw_response": llm_response[:200] if llm_response else "Empty response"
                }

            # Validate generated form
            validator = FormValidator()
            validation_result = await validator.validate_form(tenant_id, form_schema)

            if not validation_result["valid"] and validation_result.get("errors"):
                return {
                    "success": False,
                    "error": "Generated form failed validation",
                    "validation_errors": validation_result["errors"]
                }

            # Return success result
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

    async def _handle_validate_form(
        self,
        params: Dict[str, Any],
        tenant_id: str
    ) -> Dict[str, Any]:
        """Validate form in BPM FormSchema format"""
        form_definition = params.get("form_definition")
        strict_mode = params.get("strict_mode", False)

        if not form_definition:
            return {"success": False, "error": "form_definition is required"}

        try:
            validator = FormValidator()

            # Convert fields -> controls (backward compatibility)
            if "fields" in form_definition and "controls" not in form_definition:
                form_definition["controls"] = form_definition.pop("fields")

            # Validate form
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

    async def _handle_bind_form_to_process(
        self,
        params: Dict[str, Any],
        tenant_id: str
    ) -> Dict[str, Any]:
        """Bind form controls to BPMN process variables"""
        form_definition = params.get("form_definition")
        process_variables = params.get("process_variables", [])

        if not form_definition:
            return {"success": False, "error": "form_definition is required"}

        try:
            # Get controls (support both old "fields" and new "controls" format)
            controls = form_definition.get("controls") or form_definition.get("fields", [])

            # Perform binding
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

    async def _handle_suggest_form_fields(
        self,
        params: Dict[str, Any],
        tenant_id: str
    ) -> Dict[str, Any]:
        """Suggest form fields based on description"""
        form_description = params.get("form_description", "")

        if not form_description:
            return {"success": False, "error": "form_description is required"}

        try:
            # Analyze description and suggest fields
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

        # Check if containers are needed
        if any(word in description.lower() for word in ["section", "group", "layout", "grid"]):
            recommendations.extend(["grid", "tabs", "collapse"])

        # Check if business controls are needed
        if any(word in description.lower() for word in ["member", "user", "department", "role"]):
            recommendations.extend(["member-selector", "org-selector"])

        # Check if advanced controls are needed
        if any(word in description.lower() for word in ["rich", "editor", "signature", "upload"]):
            recommendations.extend(["richtext", "signature", "file-upload"])

        return recommendations

    async def _handle_suggest_fields(
        self,
        params: Dict[str, Any],
        tenant_id: str
    ) -> Dict[str, Any]:
        """Handle suggest_form_fields tool execution (legacy name)."""
        return await self._handle_suggest_form_fields(params, tenant_id)
