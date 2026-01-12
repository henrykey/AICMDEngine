"""
BPMN-MCP Server Implementation

Generates BPMN 2.0 process definitions from natural language requirements.
Integrates with Membership for organizational structure and validation.
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import logging
import aiohttp
import json
import xml.etree.ElementTree as ET
from datetime import datetime
from openai import AsyncOpenAI, RateLimitError, APIError, APIConnectionError, AuthenticationError
from src.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class OrgContext:
    """Organizational context: departments, roles, members"""
    departments: List[Dict[str, Any]]
    roles: List[Dict[str, Any]]
    members: List[Dict[str, Any]]


class MembershipClient:
    """
    Client for interacting with Membership API.
    Responsible for fetching organizational structure and validating executors.
    """

    def __init__(self, base_url: str, tenant_id: str, auth_token: Optional[str] = None):
        """
        Initialize MembershipClient.

        Args:
            base_url: Base URL of Membership service (e.g., "http://membership:8000")
            tenant_id: Tenant ID for multi-tenant isolation
            auth_token: Optional auth token; if not provided, will use request context
        """
        self.base_url = base_url
        self.tenant_id = tenant_id
        self.auth_token = auth_token
        self._cache = {}
        self._cache_ttl = 300  # 5 minutes

    async def get_org_context(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Fetch organizational context: departments, roles, members.

        Returns:
            Dict with keys: departments, roles, members
            Each value is a list of dicts with id, name, and other metadata

        Example:
            {
                "departments": [{"id": "dept_001", "name": "finance"}, ...],
                "roles": [{"id": "role_001", "name": "approver"}, ...],
                "members": [{"id": "mem_001", "name": "Alice", "roles": ["approver"]}, ...]
            }
        """
        departments = await self._fetch_departments()
        roles = await self._fetch_roles()
        members = await self._fetch_members()

        return {
            "departments": departments,
            "roles": roles,
            "members": members
        }

    async def validate_executor(
        self,
        executor_pattern: str,
        executor_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Validate executor pattern configuration against organizational structure.

        Args:
            executor_pattern: One of: static, form_driven, dynamic, queue_claim, automation
            executor_config: Pattern-specific configuration dict

        Returns:
            Dict with keys:
            - valid: bool - whether executor is valid
            - error: str (optional) - error message if invalid
            - warnings: list (optional) - list of warnings

        Examples:
            # Static pattern with role
            validate_executor("static", {
                "type": "role",
                "value": "approver"
            })
            → {"valid": True}

            # Static pattern with department
            validate_executor("static", {
                "type": "department",
                "value": "finance"
            })
            → {"valid": True}

            # Invalid role
            validate_executor("static", {
                "type": "role",
                "value": "nonexistent"
            })
            → {"valid": False, "error": "Role not found: nonexistent"}
        """
        if executor_pattern == "static":
            return await self._validate_static_executor(executor_config)
        elif executor_pattern == "form_driven":
            return await self._validate_form_driven_executor(executor_config)
        elif executor_pattern == "dynamic":
            return await self._validate_dynamic_executor(executor_config)
        elif executor_pattern == "queue_claim":
            return await self._validate_queue_claim_executor(executor_config)
        elif executor_pattern == "automation":
            return await self._validate_automation_executor(executor_config)
        else:
            return {
                "valid": False,
                "error": f"Unknown executor pattern: {executor_pattern}"
            }

    async def _validate_static_executor(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Validate static executor pattern (fixed dept/role/member)"""
        exec_type = config.get("type")
        value = config.get("value")

        if not exec_type or not value:
            return {
                "valid": False,
                "error": "Static executor requires: type (role|department|member) and value"
            }

        if exec_type == "role":
            roles = await self._fetch_roles()
            if any(r["name"] == value for r in roles):
                return {"valid": True}
            else:
                return {
                    "valid": False,
                    "error": f"Role not found: {value}"
                }

        elif exec_type == "department":
            departments = await self._fetch_departments()
            if any(d["name"] == value for d in departments):
                return {"valid": True}
            else:
                return {
                    "valid": False,
                    "error": f"Department not found: {value}"
                }

        elif exec_type == "member":
            members = await self._fetch_members()
            if any(m["id"] == value or m["name"] == value for m in members):
                return {"valid": True}
            else:
                return {
                    "valid": False,
                    "error": f"Member not found: {value}"
                }

        else:
            return {
                "valid": False,
                "error": f"Unknown static executor type: {exec_type}. Must be: role, department, or member"
            }

    async def _validate_form_driven_executor(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Validate form-driven executor pattern (user selection at start)"""
        # TODO: Implement form-driven validation
        return {"valid": True}

    async def _validate_dynamic_executor(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Validate dynamic executor pattern (data-driven routing)"""
        # TODO: Implement dynamic validation
        return {"valid": True}

    async def _validate_queue_claim_executor(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Validate queue-claim executor pattern (first-available from role/dept)"""
        # TODO: Implement queue-claim validation
        return {"valid": True}

    async def _validate_automation_executor(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Validate automation executor pattern (MCP tool or virtual member)"""
        # TODO: Implement automation validation
        return {"valid": True}

    async def _fetch_departments(self) -> List[Dict[str, Any]]:
        """Fetch departments from Membership API"""
        cache_key = f"departments_{self.tenant_id}"
        # TODO: Implement actual HTTP call to Membership API
        # For now, return empty list (to be mocked in tests)
        return []

    async def _fetch_roles(self) -> List[Dict[str, Any]]:
        """Fetch roles from Membership API"""
        cache_key = f"roles_{self.tenant_id}"
        # TODO: Implement actual HTTP call to Membership API
        # For now, return empty list (to be mocked in tests)
        return []

    async def _fetch_members(self) -> List[Dict[str, Any]]:
        """Fetch members from Membership API"""
        cache_key = f"members_{self.tenant_id}"
        # TODO: Implement actual HTTP call to Membership API
        # For now, return empty list (to be mocked in tests)
        return []


class BPMNValidator:
    """
    Validates BPMN 2.0 XML for correctness and Flowable compatibility.

    Validation includes:
    1. XML structure and parsing
    2. BPMN 2.0 required elements (startEvent, endEvent, etc.)
    3. Sequence flow connections (no broken references)
    4. Executor pattern validation
    5. Confidence score calculation
    """

    BPMN_NAMESPACE = {"bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL"}

    async def validate_bpmn(
        self,
        tenant_id: str,
        bpmn_xml: str,
        strict_mode: bool = False
    ) -> Dict[str, Any]:
        """
        Validate BPMN XML structure and content.

        Args:
            tenant_id: Tenant ID for context
            bpmn_xml: BPMN XML string
            strict_mode: If True, enforce stricter validation

        Returns:
            Dict with keys:
            - valid: bool - whether BPMN is valid
            - errors: list - critical errors (if any)
            - warnings: list - warnings (if any)
            - confidence_score: float - 0.0-1.0
        """
        errors = []
        warnings = []
        confidence_score = 1.0

        # Step 1: Parse XML
        try:
            root = ET.fromstring(bpmn_xml)
        except ET.ParseError as e:
            return {
                "valid": False,
                "errors": [f"XML parsing error: {str(e)}"],
                "warnings": [],
                "confidence_score": 0.0
            }

        # Step 2: Validate BPMN structure
        structure_errors = self._validate_bpmn_structure(root)
        errors.extend(structure_errors)
        if structure_errors:
            confidence_score -= 0.3

        # Step 3: Validate sequence flows
        flow_errors = self._validate_sequence_flows(root)
        errors.extend(flow_errors)
        if flow_errors:
            confidence_score -= 0.3

        # Step 4: Validate executor patterns (if present)
        pattern_warnings = self._validate_executor_patterns(root)
        warnings.extend(pattern_warnings)
        if pattern_warnings:
            confidence_score -= 0.1

        # Ensure confidence score is within bounds
        confidence_score = max(0.0, min(1.0, confidence_score))

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "confidence_score": confidence_score
        }

    def _validate_bpmn_structure(self, root: ET.Element) -> List[str]:
        """Validate basic BPMN 2.0 structure"""
        errors = []

        # Find process element
        process = root.find("bpmn:process", self.BPMN_NAMESPACE)
        if process is None:
            errors.append("Missing required <bpmn:process> element")
            return errors

        # Check for startEvent
        start_events = process.findall("bpmn:startEvent", self.BPMN_NAMESPACE)
        if not start_events:
            errors.append("Missing required <bpmn:startEvent> element")

        # Check for endEvent
        end_events = process.findall("bpmn:endEvent", self.BPMN_NAMESPACE)
        if not end_events:
            errors.append("Missing required <bpmn:endEvent> element")

        return errors

    def _validate_sequence_flows(self, root: ET.Element) -> List[str]:
        """Validate sequence flow connections"""
        errors = []

        process = root.find("bpmn:process", self.BPMN_NAMESPACE)
        if process is None:
            return errors

        # Get all element IDs
        all_elements = process.findall("bpmn:*", self.BPMN_NAMESPACE)
        element_ids = {elem.get("id") for elem in all_elements if elem.get("id")}

        # Validate sequence flows
        flows = process.findall("bpmn:sequenceFlow", self.BPMN_NAMESPACE)
        for flow in flows:
            source_ref = flow.get("sourceRef")
            target_ref = flow.get("targetRef")

            if source_ref and source_ref not in element_ids:
                errors.append(f"Sequence flow references non-existent source: {source_ref}")

            if target_ref and target_ref not in element_ids:
                errors.append(f"Sequence flow references non-existent target: {target_ref}")

        return errors

    def _validate_executor_patterns(self, root: ET.Element) -> List[str]:
        """Validate executor pattern documentation"""
        warnings = []

        process = root.find("bpmn:process", self.BPMN_NAMESPACE)
        if process is None:
            return warnings

        # Find all userTasks with documentation
        user_tasks = process.findall("bpmn:userTask", self.BPMN_NAMESPACE)
        for task in user_tasks:
            doc = task.find("bpmn:documentation", self.BPMN_NAMESPACE)
            if doc is not None and doc.text:
                try:
                    executor_config = json.loads(doc.text)
                    pattern = executor_config.get("executor_pattern")
                    if not pattern:
                        warnings.append(
                            f"User task {task.get('id')} missing executor_pattern in documentation"
                        )
                except json.JSONDecodeError:
                    warnings.append(
                        f"User task {task.get('id')} has invalid JSON in documentation"
                    )

        return warnings


class ExecutorPatternValidator:
    """
    Validates executor pattern configurations for all 5 patterns:
    1. Static (fixed role/dept/member)
    2. Form-driven (user selection at start)
    3. Dynamic (data-driven routing)
    4. Queue-claim (first-available)
    5. Automation (MCP tool or virtual member)
    """

    async def validate(
        self,
        pattern: str,
        config: Dict[str, Any],
        available_roles: Optional[List[Dict[str, Any]]] = None,
        available_departments: Optional[List[Dict[str, Any]]] = None,
        available_members: Optional[List[Dict[str, Any]]] = None,
        available_form_fields: Optional[List[str]] = None,
        available_mcp_tools: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Validate executor pattern configuration.

        Args:
            pattern: One of: static, form_driven, dynamic, queue_claim, automation
            config: Pattern-specific configuration dict
            available_*: Lists of available entities for validation

        Returns:
            Dict with keys:
            - valid: bool
            - error: str (optional, if invalid)
            - warnings: list (optional)
        """
        if pattern == "static":
            return await self._validate_static(config, available_roles, available_departments, available_members)
        elif pattern == "form_driven":
            return await self._validate_form_driven(config, available_form_fields)
        elif pattern == "dynamic":
            return await self._validate_dynamic(config, available_mcp_tools)
        elif pattern == "queue_claim":
            return await self._validate_queue_claim(config, available_roles, available_departments)
        elif pattern == "automation":
            return await self._validate_automation(config, available_mcp_tools)
        else:
            return {
                "valid": False,
                "error": f"Unknown executor pattern: {pattern}"
            }

    async def _validate_static(
        self,
        config: Dict[str, Any],
        roles: Optional[List[Dict[str, Any]]],
        departments: Optional[List[Dict[str, Any]]],
        members: Optional[List[Dict[str, Any]]]
    ) -> Dict[str, Any]:
        """Validate static executor pattern"""
        exec_type = config.get("type")
        value = config.get("value")

        if not exec_type:
            return {
                "valid": False,
                "error": "Static executor requires 'type' field (role, department, or member)"
            }

        if not value:
            return {
                "valid": False,
                "error": f"Static executor requires 'value' field for type '{exec_type}'"
            }

        if exec_type == "role":
            if not roles:
                return {"valid": False, "error": "No roles provided for validation"}
            if any(r["name"] == value for r in roles):
                return {"valid": True}
            else:
                return {"valid": False, "error": f"Role not found: {value}"}

        elif exec_type == "department":
            if not departments:
                return {"valid": False, "error": "No departments provided for validation"}
            if any(d["name"] == value for d in departments):
                return {"valid": True}
            else:
                return {"valid": False, "error": f"Department not found: {value}"}

        elif exec_type == "member":
            if not members:
                return {"valid": False, "error": "No members provided for validation"}
            if any(m["id"] == value or m["name"] == value for m in members):
                return {"valid": True}
            else:
                return {"valid": False, "error": f"Member not found: {value}"}

        else:
            return {
                "valid": False,
                "error": f"Unknown static type: {exec_type}. Must be: role, department, or member"
            }

    async def _validate_form_driven(
        self,
        config: Dict[str, Any],
        form_fields: Optional[List[str]]
    ) -> Dict[str, Any]:
        """Validate form-driven executor pattern"""
        form_field = config.get("form_field")

        if not form_field:
            return {
                "valid": False,
                "error": "Form-driven executor requires 'form_field' key"
            }

        if not form_fields:
            return {"valid": False, "error": "No form fields provided for validation"}

        if form_field in form_fields:
            return {"valid": True}
        else:
            return {
                "valid": False,
                "error": f"Form field not found in process: {form_field}"
            }

    async def _validate_dynamic(
        self,
        config: Dict[str, Any],
        mcp_tools: Optional[List[str]]
    ) -> Dict[str, Any]:
        """Validate dynamic executor pattern"""
        mcp_tool = config.get("mcp_tool")

        if not mcp_tool:
            return {
                "valid": False,
                "error": "Dynamic executor requires 'mcp_tool' key"
            }

        if not mcp_tools:
            return {"valid": False, "error": "No MCP tools provided for validation"}

        if mcp_tool in mcp_tools:
            return {"valid": True}
        else:
            return {
                "valid": False,
                "error": f"MCP tool not registered: {mcp_tool}"
            }

    async def _validate_queue_claim(
        self,
        config: Dict[str, Any],
        roles: Optional[List[Dict[str, Any]]],
        departments: Optional[List[Dict[str, Any]]]
    ) -> Dict[str, Any]:
        """Validate queue-claim executor pattern"""
        claim_group = config.get("claim_group")
        group_name = config.get("group_name")

        if not claim_group or not group_name:
            return {
                "valid": False,
                "error": "Queue-claim executor requires 'claim_group' and 'group_name' keys"
            }

        if claim_group == "role":
            if not roles:
                return {"valid": False, "error": "No roles provided for validation"}
            if any(r["name"] == group_name for r in roles):
                return {"valid": True}
            else:
                return {"valid": False, "error": f"Role not found for queue-claim: {group_name}"}

        elif claim_group == "department":
            if not departments:
                return {"valid": False, "error": "No departments provided for validation"}
            if any(d["name"] == group_name for d in departments):
                return {"valid": True}
            else:
                return {"valid": False, "error": f"Department not found for queue-claim: {group_name}"}

        else:
            return {
                "valid": False,
                "error": f"Unknown queue-claim group: {claim_group}. Must be: role or department"
            }

    async def _validate_automation(
        self,
        config: Dict[str, Any],
        mcp_tools: Optional[List[str]]
    ) -> Dict[str, Any]:
        """Validate automation executor pattern"""
        automation_type = config.get("automation_type")

        if not automation_type:
            return {
                "valid": False,
                "error": "Automation executor requires 'automation_type' key (mcp_tool or virtual_member)"
            }

        if automation_type == "mcp_tool":
            mcp_tool_name = config.get("mcp_tool_name")
            if not mcp_tool_name:
                return {
                    "valid": False,
                    "error": "MCP tool automation requires 'mcp_tool_name' key"
                }

            if not mcp_tools:
                return {"valid": False, "error": "No MCP tools provided for validation"}

            if mcp_tool_name in mcp_tools:
                return {"valid": True}
            else:
                return {
                    "valid": False,
                    "error": f"MCP tool not registered: {mcp_tool_name}"
                }

        elif automation_type == "virtual_member":
            virtual_member_name = config.get("virtual_member_name")
            if not virtual_member_name:
                return {
                    "valid": False,
                    "error": "Virtual member automation requires 'virtual_member_name' key"
                }
            return {"valid": True}

        else:
            return {
                "valid": False,
                "error": f"Unknown automation type: {automation_type}. Must be: mcp_tool or virtual_member"
            }


# ============================================================================
# Task 4: LLM Prompt Engineering
# ============================================================================

async def build_system_prompt() -> str:
    """
    Build system prompt for BPMN generation using Claude LLM.

    Returns:
        System prompt string containing BPMN guidance and executor patterns
    """
    prompt = """You are an expert BPMN (Business Process Model and Notation) 2.0 XML generator.

Your task is to generate valid BPMN 2.0 XML process definitions based on natural language requirements.

EXECUTOR PATTERNS:
You must understand and apply these 5 executor assignment patterns:

1. **Static**: Fixed assignment to a role, department, or specific member
   - Example: "Always route to Finance Department"
   - Use for processes with predetermined handlers

2. **Form-Driven**: User selects executor at process start
   - Example: "User selects approver from dropdown"
   - Use for flexible processes where human input drives routing

3. **Dynamic**: Data-driven routing based on organizational context
   - Example: "Route to department based on amount"
   - Use for intelligent, context-aware routing

4. **Queue-Claim**: First-available from a role or department queue
   - Example: "Assign to next available sales person"
   - Use for load-balanced task distribution

5. **Automation**: MCP tool or virtual AI member handles the task
   - Example: "Use AI Auditor for financial review"
   - Use for automated workflows

BPMN STRUCTURE:
- Generate valid XML with proper BPMN namespaces
- Include startEvent, endEvent, and task elements
- Use sequenceFlow for connections
- Add bpmn:documentation elements with executor pattern JSON

OUTPUT FORMAT:
Return ONLY the XML, nothing else. No explanation, no markdown, just raw BPMN XML.

Each user task must include documentation with executor pattern configuration:
```json
{
  "executor_pattern": "static|form_driven|dynamic|queue_claim|automation",
  "executor_config": {...pattern-specific config...}
}
```

Guidelines:
- Process ID should describe the business process
- Use clear, descriptive names for tasks and events
- Ensure all references are connected (no broken flows)
- Include proper attributes for all elements"""

    return prompt


async def get_few_shot_examples() -> List[Dict[str, str]]:
    """
    Get few-shot examples for BPMN generation using Mock LLM.

    Returns:
        List of examples with 'input' (requirements) and 'output' (BPMN XML)
    """
    examples = [
        {
            "input": "Create an approval process where all purchase orders over $5000 must be approved by the Finance Manager.",
            "output": """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Definitions_1">
  <bpmn:process id="PurchaseApproval" isExecutable="true">
    <bpmn:startEvent id="Start" name="PO Submitted"/>
    <bpmn:userTask id="ApproveTask" name="Approve Purchase Order">
      <bpmn:incoming>Flow1</bpmn:incoming>
      <bpmn:outgoing>Flow2</bpmn:outgoing>
      <bpmn:documentation>{"executor_pattern": "static", "executor_config": {"type": "role", "value": "finance_manager"}}</bpmn:documentation>
    </bpmn:userTask>
    <bpmn:endEvent id="End" name="Process Complete"/>
    <bpmn:sequenceFlow id="Flow1" sourceRef="Start" targetRef="ApproveTask"/>
    <bpmn:sequenceFlow id="Flow2" sourceRef="ApproveTask" targetRef="End"/>
  </bpmn:process>
</bpmn:definitions>"""
        },
        {
            "input": "Create a claim review process where a user submits a claim and selects which reviewer should handle it.",
            "output": """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Definitions_1">
  <bpmn:process id="ClaimReview" isExecutable="true">
    <bpmn:startEvent id="Start" name="Claim Submitted"/>
    <bpmn:userTask id="ReviewTask" name="Review Claim">
      <bpmn:incoming>Flow1</bpmn:incoming>
      <bpmn:outgoing>Flow2</bpmn:outgoing>
      <bpmn:documentation>{"executor_pattern": "form_driven", "executor_config": {"form_field": "reviewer_selection"}}</bpmn:documentation>
    </bpmn:userTask>
    <bpmn:endEvent id="End" name="Review Complete"/>
    <bpmn:sequenceFlow id="Flow1" sourceRef="Start" targetRef="ReviewTask"/>
    <bpmn:sequenceFlow id="Flow2" sourceRef="ReviewTask" targetRef="End"/>
  </bpmn:process>
</bpmn:definitions>"""
        },
        {
            "input": "Create an invoice routing process where invoices are automatically routed to the appropriate department based on the vendor code.",
            "output": """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Definitions_1">
  <bpmn:process id="InvoiceRouting" isExecutable="true">
    <bpmn:startEvent id="Start" name="Invoice Received"/>
    <bpmn:userTask id="ApproveTask" name="Approve Invoice">
      <bpmn:incoming>Flow1</bpmn:incoming>
      <bpmn:outgoing>Flow2</bpmn:outgoing>
      <bpmn:documentation>{"executor_pattern": "dynamic", "executor_config": {"mcp_tool": "route_by_vendor", "kb_query": "Find department for vendor: ${vendor_code}"}}</bpmn:documentation>
    </bpmn:userTask>
    <bpmn:endEvent id="End" name="Approved"/>
    <bpmn:sequenceFlow id="Flow1" sourceRef="Start" targetRef="ApproveTask"/>
    <bpmn:sequenceFlow id="Flow2" sourceRef="ApproveTask" targetRef="End"/>
  </bpmn:process>
</bpmn:definitions>"""
        }
    ]

    return examples


async def build_input_context(
    tenant_id: str,
    description: str,
    org_context: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Build input context for LLM BPMN generation.

    Args:
        tenant_id: Tenant ID for process ownership
        description: Natural language process description
        org_context: Organizational context with departments, roles, members

    Returns:
        Formatted context dict for LLM prompt
    """
    context = {
        "description": description,
        "org_context": {
            "departments": org_context.get("departments", []),
            "roles": org_context.get("roles", []),
            "members": org_context.get("members", [])
        },
        "available_executor_patterns": [
            "static",
            "form_driven",
            "dynamic",
            "queue_claim",
            "automation"
        ]
    }

    return context


class MockLLMClient:
    """
    Mock LLM client for testing prompt engineering without API calls.
    Returns predetermined BPMN responses based on input.
    """

    def __init__(self):
        """Initialize Mock LLM client."""
        self._response_cache = {}

    async def send_prompt(self, system_prompt: str, user_prompt: str) -> str:
        """
        Send prompt to Mock LLM and return predetermined response.

        Args:
            system_prompt: System context prompt
            user_prompt: User's process description

        Returns:
            Mock BPMN XML response
        """
        # Create cache key from prompts
        cache_key = f"{system_prompt}:::{user_prompt}"

        # Return cached response if available
        if cache_key in self._response_cache:
            return self._response_cache[cache_key]

        # Generate mock BPMN response
        response = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Definitions_Mock">
  <bpmn:process id="MockProcess" isExecutable="true">
    <bpmn:startEvent id="MockStart" name="Start"/>
    <bpmn:userTask id="MockTask" name="Task">
      <bpmn:incoming>MockFlow1</bpmn:incoming>
      <bpmn:outgoing>MockFlow2</bpmn:outgoing>
      <bpmn:documentation>{"executor_pattern": "static", "executor_config": {"type": "role", "value": "approver"}}</bpmn:documentation>
    </bpmn:userTask>
    <bpmn:endEvent id="MockEnd" name="End"/>
    <bpmn:sequenceFlow id="MockFlow1" sourceRef="MockStart" targetRef="MockTask"/>
    <bpmn:sequenceFlow id="MockFlow2" sourceRef="MockTask" targetRef="MockEnd"/>
  </bpmn:process>
</bpmn:definitions>"""

        # Cache and return response
        self._response_cache[cache_key] = response
        return response


class RealLLMClient:
    """
    Real LLM client for BPMN generation using OpenAI-compatible API.
    Implements multi-provider fallback mechanism consistent with src/services/llm_client.py.

    Configuration priority:
    1. Custom parameters (base_url, api_key, model) if provided
    2. Environment variables via settings (deepseek_* or openai_*)

    Fallback strategy: Tries providers in order, switches on rate limit/connection errors.
    """

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None, model: Optional[str] = None):
        """
        Initialize Real LLM client with multi-provider fallback.

        Args:
            base_url: Optional custom base URL (uses settings if not provided)
            api_key: Optional API key (uses settings if not provided)
            model: Optional model name (uses settings if not provided)
        """
        # Define provider list (consistent with src/services/llm_client.py)
        self.providers = [
            {
                'name': 'deepseek',
                'base_url': base_url or settings.deepseek_base_url,
                'api_key': api_key or settings.deepseek_api_key,
                'model': model or settings.deepseek_model_name
            },
            {
                'name': 'openai',
                'base_url': settings.openai_base_url,
                'api_key': settings.openai_api_key,
                'model': settings.openai_model_name
            }
        ]

        # Filter out providers without API key configured
        self.providers = [p for p in self.providers if p['api_key']]
        if not self.providers:
            raise ValueError("Missing required LLM configuration (no provider with API key configured)")

        # Initialize clients for all providers
        self._clients = {}
        for provider in self.providers:
            self._clients[provider['name']] = AsyncOpenAI(
                api_key=provider['api_key'],
                base_url=provider['base_url']
            )

        # Current provider index for fallback
        self.current_provider_index = 0
        self._response_cache = {}

        logger.info(f"RealLLMClient initialized with {len(self.providers)} provider(s): "
                   f"{', '.join(p['name'] for p in self.providers)}")

    async def send_prompt(self, system_prompt: str, user_prompt: str) -> str:
        """
        Send prompt to OpenAI-compatible API with automatic provider fallback.

        Args:
            system_prompt: System context prompt
            user_prompt: User's process description

        Returns:
            BPMN XML response from LLM

        Raises:
            RuntimeError: If all providers fail or returns invalid response
        """
        # Create cache key from prompts
        cache_key = f"{system_prompt}:::{user_prompt}"

        # Return cached response if available
        if cache_key in self._response_cache:
            return self._response_cache[cache_key]

        last_error = None

        # Try all providers with fallback
        for attempt in range(len(self.providers)):
            current_provider = self.providers[self.current_provider_index]
            client = self._clients[current_provider['name']]

            try:
                logger.info(f"Attempting LLM call with provider='{current_provider['name']}', "
                           f"model='{current_provider['model']}', "
                           f"base_url='{current_provider['base_url']}'")

                # Call OpenAI-compatible API
                response = await client.chat.completions.create(
                    model=current_provider['model'],
                    messages=[
                        {
                            "role": "system",
                            "content": system_prompt
                        },
                        {
                            "role": "user",
                            "content": user_prompt
                        }
                    ],
                    temperature=0.3,
                    max_tokens=4096
                )

                # Extract response text
                text_response = response.choices[0].message.content
                logger.info(f"Successfully got response from provider='{current_provider['name']}'")

                # Cache and return response
                self._response_cache[cache_key] = text_response
                return text_response

            except RateLimitError as e:
                last_error = e
                logger.warning(f"Rate limit error with provider='{current_provider['name']}': {e}")
                self._switch_to_next_provider()

            except AuthenticationError as e:
                last_error = e
                logger.error(f"Authentication error with provider='{current_provider['name']}': {e}")
                self._switch_to_next_provider()

            except APIConnectionError as e:
                last_error = e
                logger.warning(f"Connection error with provider='{current_provider['name']}': {e}")
                self._switch_to_next_provider()

            except APIError as e:
                last_error = e
                logger.warning(f"API error with provider='{current_provider['name']}': {e}")
                if self._is_recoverable_api_error(e):
                    self._switch_to_next_provider()
                else:
                    raise RuntimeError(f"LLM API error: {str(e)}") from e

            except Exception as e:
                last_error = e
                logger.error(f"Unexpected error with provider='{current_provider['name']}': {e}", exc_info=True)
                self._switch_to_next_provider()

        # All providers failed
        error_msg = f"All LLM providers failed. Last error: {last_error}"
        logger.error(error_msg)
        raise RuntimeError(error_msg) from last_error

    def _switch_to_next_provider(self):
        """Switch to next available provider for fallback."""
        self.current_provider_index = (self.current_provider_index + 1) % len(self.providers)
        next_provider = self.providers[self.current_provider_index]
        logger.info(f"Switched to provider='{next_provider['name']}' (index={self.current_provider_index})")

    def _is_recoverable_api_error(self, error: APIError) -> bool:
        """Check if API error indicates we should switch providers."""
        error_message = str(error).lower()

        # Rate limit/quota errors should trigger provider switch
        if any(keyword in error_message for keyword in ['rate limit', 'quota', 'limit', 'throttled', 'exceeded']):
            return True

        # Server errors may be recoverable with different provider
        if any(keyword in error_message for keyword in ['internal server error', 'timeout', 'service unavailable']):
            return True

        return False


async def validate_prompt_response(response: str) -> Dict[str, Any]:
    """
    Validate LLM response for BPMN correctness.

    Args:
        response: Response string from LLM

    Returns:
        Validation result with valid flag, errors, and confidence score
    """
    errors = []
    warnings = []

    # Try to parse XML
    try:
        root = ET.fromstring(response)
    except ET.ParseError as e:
        return {
            "valid": False,
            "errors": [f"XML parse error: {str(e)}"],
            "confidence": 0.0
        }

    # Check for required BPMN elements
    ns = {"bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL"}

    # Check for process element
    processes = root.findall(".//bpmn:process", ns)
    if not processes:
        errors.append("Missing bpmn:process element")

    # Check for startEvent
    start_events = root.findall(".//bpmn:startEvent", ns)
    if not start_events:
        errors.append("Missing bpmn:startEvent element")

    # Check for endEvent
    end_events = root.findall(".//bpmn:endEvent", ns)
    if not end_events:
        errors.append("Missing bpmn:endEvent element")

    # Calculate confidence
    if errors:
        confidence = 0.5
    else:
        confidence = 0.9

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "confidence": confidence
    }


# ============================================================================
# Task 5: generate_process Tool Implementation
# ============================================================================

async def generate_process(
    tenant_id: str,
    description: str,
    org_context: Dict[str, Any],
    use_real_llm: bool = False,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generate BPMN process from natural language description.

    Main entry point for BPMN generation workflow:
    1. Build system prompt + input context
    2. Get few-shot examples
    3. Send to Mock LLM (Task 5) / Real LLM (Task 6)
    4. Validate response using BPMNValidator
    5. Return result with confidence score

    Args:
        tenant_id: Tenant ID for process ownership
        description: Natural language process description
        org_context: Organizational context with departments, roles, members
        use_real_llm: If True, use Claude API; if False, use MockLLMClient
        api_key: Optional Anthropic API key (uses ANTHROPIC_API_KEY env var if not provided)

    Returns:
        Result dict with:
        - bpmn_xml: Generated BPMN 2.0 XML string
        - valid: Whether BPMN is valid
        - confidence_score: 0.0-1.0 quality indicator
        - errors: List of validation errors (if any)
        - metadata: Process generation metadata
    """
    # Initialize components
    membership_client = MembershipClient("http://membership:8000", tenant_id)
    validator = BPMNValidator()

    # Use either Real or Mock LLM client
    if use_real_llm:
        llm_client = RealLLMClient(api_key=api_key)
    else:
        llm_client = MockLLMClient()

    # Build prompts
    system_prompt = await build_system_prompt()
    few_shot_examples = await get_few_shot_examples()
    input_context = await build_input_context(tenant_id, description, org_context)

    # Format few-shot examples for LLM
    few_shot_text = "\n\n".join([
        f"Example {i+1}:\nRequirement: {ex['input']}\n\nBPMN Output:\n{ex['output']}"
        for i, ex in enumerate(few_shot_examples)
    ])

    # Build final user prompt
    user_prompt = f"""Few-shot examples:

{few_shot_text}

Now generate BPMN for this requirement:
Requirement: {description}

Organization Context:
- Departments: {input_context['org_context']['departments']}
- Roles: {input_context['org_context']['roles']}
- Members: {input_context['org_context']['members']}

Generate the BPMN XML (no explanation, just raw XML):"""

    # Send to LLM (Mock or Real based on use_real_llm flag)
    bpmn_response = await llm_client.send_prompt(system_prompt, user_prompt)

    # Validate response
    validation_result = await validator.validate_bpmn(tenant_id, bpmn_response)

    # Return result
    return {
        "bpmn_xml": bpmn_response,
        "valid": validation_result.get("valid", False),
        "confidence_score": validation_result.get("confidence_score", 0.5),
        "errors": validation_result.get("errors", []),
        "warnings": validation_result.get("warnings", []),
        "metadata": {
            "tenant_id": tenant_id,
            "description": description,
            "pattern": "bpmn_generation",
            "timestamp": datetime.now().isoformat()
        }
    }


class GenerateProcessTool:
    """
    MCP Tool wrapper for generate_process function.
    Handles tool registration and schema definition.
    """

    def __init__(self):
        """Initialize GenerateProcessTool."""
        self.name = "generate_process"
        self.description = "Generate BPMN 2.0 process definitions from natural language requirements"
        self.schema = {
            "tenant_id": {
                "type": "string",
                "description": "Tenant ID for process ownership"
            },
            "description": {
                "type": "string",
                "description": "Natural language process description"
            },
            "org_context": {
                "type": "object",
                "description": "Organizational context with departments, roles, members",
                "properties": {
                    "departments": {
                        "type": "array",
                        "items": {"type": "object"}
                    },
                    "roles": {
                        "type": "array",
                        "items": {"type": "object"}
                    },
                    "members": {
                        "type": "array",
                        "items": {"type": "object"}
                    }
                }
            }
        }

    async def execute(
        self,
        tenant_id: str,
        description: str,
        org_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute the generate_process tool.

        Args:
            tenant_id: Tenant ID
            description: Process description
            org_context: Org context

        Returns:
            Generated BPMN result
        """
        return await generate_process(tenant_id, description, org_context)
