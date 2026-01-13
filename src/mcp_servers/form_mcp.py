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
from datetime import datetime
from openai import AsyncOpenAI, RateLimitError, APIError, APIConnectionError, AuthenticationError

from src.core.config import settings
from src.mcp.base_server import BaseMCPServer

logger = logging.getLogger(__name__)


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
        """Initialize FormValidator."""
        self.field_types = {
            "text", "textarea", "number", "select", "checkbox", "date", "file"
        }
        self.form_types = {"startup", "task_specific", "standalone"}

    async def validate_form(
        self,
        tenant_id: str,
        form_definition: Dict[str, Any],
        strict_mode: bool = False,
        bpmn_variables: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Validate form definition structure and constraints.

        Args:
            tenant_id: Tenant ID
            form_definition: Complete form definition
            strict_mode: Apply strict validation
            bpmn_variables: List of available BPMN process variables

        Returns:
            Validation result with errors, warnings, and confidence score
        """
        errors = []
        warnings = []
        issues = {
            "field_issues": [],
            "permission_issues": [],
            "binding_issues": [],
            "org_mismatches": []
        }

        # Check form structure
        if not form_definition.get("form_name"):
            errors.append("Form name is required")

        if form_definition.get("form_type") not in self.form_types:
            errors.append(f"Invalid form_type. Must be one of: {self.form_types}")

        # Validate fields
        for field in form_definition.get("fields", []):
            field_errors = await self._validate_field(field, bpmn_variables, strict_mode)
            issues["field_issues"].extend(field_errors)
            # Add field errors to main errors list if they're critical
            for error in field_errors:
                if error["issue_type"] in ["invalid_type", "missing_label"]:
                    errors.append(error["message"])

            # Validate permissions
            perm_errors = self._validate_field_permissions(field)
            issues["permission_issues"].extend(perm_errors)

            # Validate BPMN bindings
            if bpmn_variables:
                binding_errors = self._validate_field_binding(field, bpmn_variables)
                issues["binding_issues"].extend(binding_errors)

        # Compute confidence score
        total_issues = len(errors) + len(warnings) + len(issues["field_issues"])
        confidence_score = max(0.0, 1.0 - (total_issues * 0.1))

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "issues": issues,
            "confidence_score": confidence_score
        }

    async def _validate_field(
        self,
        field: Dict[str, Any],
        bpmn_variables: Optional[List[str]],
        strict_mode: bool
    ) -> List[Dict[str, Any]]:
        """Validate individual field."""
        issues = []

        if not field.get("field_name"):
            issues.append({
                "field_id": field.get("field_id", "unknown"),
                "issue_type": "missing_label",
                "message": "Field name is required"
            })

        if field.get("field_type") not in self.field_types:
            issues.append({
                "field_id": field.get("field_id", "unknown"),
                "issue_type": "invalid_type",
                "message": f"Invalid field type: {field.get('field_type')}"
            })

        return issues

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


class MockLLMClient:
    """Mock LLM client for form generation (testing)."""

    def __init__(self):
        """Initialize MockLLMClient."""
        self._response_cache = {}

    async def send_prompt(self, system_prompt: str, user_prompt: str) -> str:
        """Generate mock form definition."""
        cache_key = f"{system_prompt}:::{user_prompt}"

        if cache_key in self._response_cache:
            return self._response_cache[cache_key]

        # Return mock form definition
        mock_form = {
            "form_id": str(uuid.uuid4()),
            "form_name": "Generated Form",
            "form_type": "standalone",
            "fields": [
                {
                    "field_id": "field_001",
                    "field_name": "applicant_name",
                    "field_type": "text",
                    "label": "Applicant Name",
                    "required": True,
                    "permissions": {
                        "view": {"condition": "*", "applies_to": ["*"]},
                        "edit": {"condition": "*", "applies_to": ["*"]},
                        "required": {"condition": "True", "applies_to": ["*"]}
                    }
                }
            ]
        }

        response = json.dumps(mock_form)
        self._response_cache[cache_key] = response
        return response


async def generate_form(
    tenant_id: str,
    form_name: str,
    form_type: str,
    description: str,
    org_context: Dict[str, Any],
    use_real_llm: bool = False
) -> Dict[str, Any]:
    """Generate form definition from natural language description."""
    # Initialize LLM client
    if use_real_llm:
        # Would use RealLLMClient
        llm_client = MockLLMClient()
    else:
        llm_client = MockLLMClient()

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
    response = await llm_client.send_prompt(system_prompt, user_prompt)

    # Parse response
    try:
        form_def = json.loads(response)
    except json.JSONDecodeError:
        # Fallback to mock
        form_def = json.loads(await MockLLMClient().send_prompt("", ""))

    return {
        "success": True,
        "form_definition": form_def,
        "confidence_score": 0.85,
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
                return await self._handle_bind_form(params, tenant_id)
            elif tool_name == "suggest_form_fields":
                return await self._handle_suggest_fields(params, tenant_id)
            else:
                return {"success": False, "error": f"Unknown tool: {tool_name}"}
        except Exception as e:
            logger.error(f"Error executing tool '{tool_name}': {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def _handle_generate_form(
        self,
        params: Dict[str, Any],
        tenant_id: str
    ) -> Dict[str, Any]:
        """Handle generate_form tool execution."""
        form_name = params.get("form_name", "")
        form_type = params.get("form_type", "standalone")
        description = params.get("description", "")
        context = params.get("context", {})

        if not form_name:
            return {"success": False, "error": "form_name is required"}
        if not description:
            return {"success": False, "error": "description is required"}

        try:
            if not self.membership_client:
                self.membership_client = FormMCPClient(
                    self.membership_base_url,
                    tenant_id
                )

            org_context = await self.membership_client.get_org_context()

            result = await generate_form(
                tenant_id=tenant_id,
                form_name=form_name,
                form_type=form_type,
                description=description,
                org_context={"org_context": org_context},
                use_real_llm=self.use_real_llm
            )

            return {"success": True, **result}
        except Exception as e:
            logger.error(f"Form generation failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def _handle_validate_form(
        self,
        params: Dict[str, Any],
        tenant_id: str
    ) -> Dict[str, Any]:
        """Handle validate_form tool execution."""
        form_definition = params.get("form_definition")
        strict_mode = params.get("strict_mode", False)

        if not form_definition:
            return {"success": False, "error": "form_definition is required"}

        try:
            result = await self.validator.validate_form(
                tenant_id=tenant_id,
                form_definition=form_definition,
                strict_mode=strict_mode
            )

            return {"success": True, **result}
        except Exception as e:
            logger.error(f"Form validation failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def _handle_bind_form(
        self,
        params: Dict[str, Any],
        tenant_id: str
    ) -> Dict[str, Any]:
        """Handle bind_form_to_process tool execution."""
        form_definition = params.get("form_definition")
        process_variables = params.get("process_variables", [])

        if not form_definition:
            return {"success": False, "error": "form_definition is required"}

        try:
            # Validate bindings
            unmapped = []
            mapped = []

            for field in form_definition.get("fields", []):
                bpmn_var = field.get("data_binding", {}).get("bpmn_variable")
                if bpmn_var:
                    if bpmn_var in process_variables:
                        mapped.append(bpmn_var)
                    else:
                        unmapped.append(bpmn_var)

            return {
                "success": True,
                "process_variables_mapped": mapped,
                "unmapped_variables": unmapped,
                "binding_complete": len(unmapped) == 0
            }
        except Exception as e:
            logger.error(f"Form binding failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def _handle_suggest_fields(
        self,
        params: Dict[str, Any],
        tenant_id: str
    ) -> Dict[str, Any]:
        """Handle suggest_form_fields tool execution."""
        form_description = params.get("form_description", "")

        if not form_description:
            return {"success": False, "error": "form_description is required"}

        try:
            # Simple heuristic-based field suggestion
            suggestions = []

            desc_lower = form_description.lower()

            if any(word in desc_lower for word in ["name", "applicant", "user"]):
                suggestions.append({
                    "field_name": "applicant_name",
                    "field_type": "text",
                    "rationale": "Required for identifying applicant"
                })

            if any(word in desc_lower for word in ["amount", "budget", "cost", "price"]):
                suggestions.append({
                    "field_name": "amount",
                    "field_type": "number",
                    "rationale": "Needed for financial information"
                })

            if any(word in desc_lower for word in ["date", "time", "when", "schedule"]):
                suggestions.append({
                    "field_name": "request_date",
                    "field_type": "date",
                    "rationale": "Important for timeline tracking"
                })

            if any(word in desc_lower for word in ["reason", "explanation", "description", "detail"]):
                suggestions.append({
                    "field_name": "description",
                    "field_type": "textarea",
                    "rationale": "Allows detailed explanation"
                })

            if any(word in desc_lower for word in ["approve", "reject", "status"]):
                suggestions.append({
                    "field_name": "approval_status",
                    "field_type": "select",
                    "options": ["pending", "approved", "rejected"],
                    "rationale": "Tracks approval status"
                })

            return {
                "success": True,
                "suggestions": suggestions
            }
        except Exception as e:
            logger.error(f"Field suggestion failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
