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
from src.mcp.result import ToolResult
from src.mcp.tool import Tool
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


class FormsIncomplete(Exception):
    """The Membership form list could not be read completely."""


class FORM_MCP(BaseMCPServer):
    """
    Read-only form tool for Membership, reached only through the MCP Router.

    ``find_forms`` lists the forms that already exist in the caller's own tenant (optionally narrowed by a name or key) with a plain
    summary of each form's fields. A caller drafting a leave-request form uses it to see whether the tenant already has a suitable
    form before proposing a new one.

    It reads Membership's ``GET /v2/forms`` with the caller's own token and tenant, which the Router binds into every call. It has
    no default identity and no fallback: without both, it fails. Membership decides what the caller may read (``workflow.read``);
    this tool neither widens nor re-implements that, and it validates and generates nothing.
    """

    FORMS_COMMAND = "GET /v2/forms"
    PAGE_SIZE = 100
    MAX_PAGES = 20
    MAX_QUERY = 200
    MAX_RESULTS = 20

    def __init__(self, membership_base_url: Optional[str] = None):
        super().__init__(name="form_mcp", version="2.0.0")
        from src.services.http_client import HTTPClient
        self.membership_base_url = membership_base_url or settings.membership_service_url
        self.http_client = HTTPClient(base_url=self.membership_base_url, membership_url=self.membership_base_url)
        self.description = "Read-only access to the caller's tenant forms in Membership"
        self._register_tools()

    def _register_tools(self) -> None:
        self.register_tool(Tool(
            name="find_forms",
            description="List the forms that already exist in the caller's tenant, optionally narrowed by a name or key, with a summary of each form's fields",
            semantic_description="查找当前租户已有的表单（例如请假表单），返回表单标识、名称、状态和字段概要，便于在设计新表单前复用已有表单。只读。",
            use_cases=["设计请假流程前查看租户是否已有请假表单", "按名称或标识查找已有表单"],
            natural_language_examples=["有没有请假表单？", "list the leave request forms"],
            output_description="JSON：total（租户表单总数）、matched（匹配数）、forms（最多 20 个，含 formKey、formName、status、version、fields）。字段概要只来自表单本身的 schema，不是校验结果。",
            tags=["form", "lookup", "read_only"],
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Optional text to match against the form key or form name (case-insensitive). Omit to list the tenant's forms."
                    },
                    "auth_token": {"type": "string", "description": "Bound by the MCP Router from the authenticated caller"},
                    "tenant_id": {"type": "integer", "description": "Bound by the MCP Router from the authenticated caller"},
                },
            },
            handler=self.find_forms,
        ))

    @staticmethod
    def _identity(auth_token: Any, tenant_id: Any):
        if not isinstance(auth_token, str) or not auth_token.strip():
            raise ValueError("authentication token required")
        if isinstance(tenant_id, bool) or tenant_id is None or not str(tenant_id).isdigit() or int(tenant_id) <= 0:
            raise ValueError("tenant required")
        return auth_token, int(tenant_id)

    async def _read_forms(self, token: str, tenant: int) -> List[Dict[str, Any]]:
        """Every form of the tenant, page by page. Anything short of the reported total is an error, never a partial answer."""
        seen: Dict[Any, Dict[str, Any]] = {}
        total: Optional[int] = None
        for page in range(1, self.MAX_PAGES + 1):
            response = await self.http_client.execute(
                command=self.FORMS_COMMAND,
                params={"query": {"page": page, "page_size": self.PAGE_SIZE}},
                auth_token=token,
                tenant_id=tenant,
            )
            raw = response.get("data") if isinstance(response, dict) else None
            meta = response.get("meta") if isinstance(response, dict) else None
            reported = meta.get("total") if isinstance(meta, dict) else None
            if not isinstance(raw, list) or isinstance(reported, bool) or not isinstance(reported, int) or reported < 0:
                raise FormsIncomplete("the list has no readable total")
            if total is not None and reported != total:
                raise FormsIncomplete("the total changed while the list was read")
            total = reported
            fresh = [f for f in raw if isinstance(f, dict) and f.get("formKey") not in seen]
            for form in fresh:
                seen[form.get("formKey")] = form
            if len(seen) >= total:
                return list(seen.values())
            if not fresh:
                raise FormsIncomplete("the endpoint returned nothing new before the total was reached")
        raise FormsIncomplete("the page bound was reached before the total")

    @staticmethod
    def _fields(form: Dict[str, Any]) -> List[Dict[str, Any]]:
        schema = form.get("formSchema")
        properties = schema.get("properties") if isinstance(schema, dict) else None
        required = set(schema.get("required") or []) if isinstance(schema, dict) and isinstance(schema.get("required"), list) else set()
        out: List[Dict[str, Any]] = []
        if isinstance(properties, dict):
            for key, spec in properties.items():
                spec = spec if isinstance(spec, dict) else {}
                item = {"key": key, "title": spec.get("title"), "type": spec.get("type"), "required": key in required}
                if spec.get("format"):
                    item["format"] = spec.get("format")
                out.append(item)
        return out

    async def find_forms(self, query: Optional[str] = None, auth_token: Any = None, tenant_id: Any = None) -> ToolResult:
        if query is not None and (not isinstance(query, str) or len(query.strip()) > self.MAX_QUERY):
            return ToolResult.error(f"query must be a text of at most {self.MAX_QUERY} characters", error_code="INVALID_PARAMS")
        try:
            token, tenant = self._identity(auth_token, tenant_id)
        except ValueError as e:
            return ToolResult.error(f"Caller identity is required: {e}", error_code="IDENTITY_REQUIRED")
        try:
            forms = await self._read_forms(token, tenant)
        except FormsIncomplete as e:
            logger.warning("Form list is incomplete: %s", e)
            return ToolResult.error("The tenant's form list could not be read completely, so no answer is given", error_code="FORMS_INCOMPLETE")
        except ValueError:
            return ToolResult.error("Caller identity is required", error_code="IDENTITY_REQUIRED")
        except Exception as e:
            status_code = getattr(getattr(e, "response", None), "status_code", None)
            logger.error("Reading the forms failed: %s", type(e).__name__)
            if status_code in (401, 403):
                return ToolResult.error("Not allowed to read forms", error_code="FORBIDDEN")
            return ToolResult.error("Failed to read forms", error_code="FORMS_FAILED")

        wanted = (query or "").strip().lower()
        matched = [f for f in forms
                   if not wanted or wanted in str(f.get("formKey", "")).lower() or wanted in str(f.get("formName", "")).lower()]
        matched.sort(key=lambda f: str(f.get("formKey", "")))
        payload = {
            "total": len(forms),
            "matched": len(matched),
            "forms": [
                {"formKey": f.get("formKey"), "formName": f.get("formName"), "status": f.get("status"),
                 "version": f.get("version"), "fields": self._fields(f)}
                for f in matched[:self.MAX_RESULTS]
            ],
        }
        return ToolResult.success(content=json.dumps(payload, ensure_ascii=False, separators=(",", ":")), data=payload)
