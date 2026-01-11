"""
BPMN-MCP Server Implementation

Generates BPMN 2.0 process definitions from natural language requirements.
Integrates with Membership for organizational structure and validation.
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import logging
import aiohttp
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
