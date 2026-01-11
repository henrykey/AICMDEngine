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
