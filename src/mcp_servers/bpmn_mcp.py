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
