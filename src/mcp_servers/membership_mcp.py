"""
Membership API MCP Server implementation.

This MCP server exposes Membership API commands as tools.
"""

from typing import Optional, Dict, Any
import logging
import os
import re
from datetime import datetime
from urllib.parse import urljoin

from ..mcp import BaseMCPServer, Tool, ToolResult
from ..services.http_client import HTTPClient
from ..core.config import settings

logger = logging.getLogger(__name__)


class MembershipMCPServer(BaseMCPServer):
    """
    MCP server for Membership API commands.

    Provides tools for member and role management operations.
    """

    def __init__(self, tenant_id: Optional[int] = None, auth_token: Optional[str] = None):
        """
        Initialize the Membership MCP server.

        Args:
            tenant_id: Tenant ID for API calls
            auth_token: Authorization token for API calls
        """
        super().__init__("membership", "2.0")
        self.tenant_id = tenant_id or settings.fixed_tenant_id
        self.auth_token = auth_token
        self.base_url = settings.membership_service_url
        # Pass membership_url as well so token refresh can work on 401
        self.http_client = HTTPClient(base_url=self.base_url, membership_url=self.base_url)
        self._audit_system_tokens: Dict[int, str] = {}
        self._register_tools()

    def _register_tools(self) -> None:
        """Register all Membership API tools."""
        # List members tool
        self.register_tool(Tool(
            name="list_members",
            description="List all members in the organization",
            input_schema={
                "type": "object",
                "properties": {
                    "page": {
                        "type": "integer",
                        "description": "Page number (1-indexed)",
                        "default": 1
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of items per page",
                        "default": 10
                    },
                    "search": {
                        "type": "string",
                        "description": "Search query (optional)"
                    },
                    "auth_token": {
                        "type": "string",
                        "description": "Authentication token (optional, will use default if not provided)"
                    },
                    "tenant_id": {
                        "type": "integer",
                        "description": "Tenant ID (optional, will use default if not provided)"
                    }
                }
            },
            handler=self.list_members
        ))

        # Get member tool
        self.register_tool(Tool(
            name="get_member",
            description="Get details of a specific member",
            input_schema={
                "type": "object",
                "properties": {
                    "member_id": {
                        "type": "string",
                        "description": "Member ID"
                    },
                    "auth_token": {
                        "type": "string",
                        "description": "Authentication token (optional, will use default if not provided)"
                    },
                    "tenant_id": {
                        "type": "integer",
                        "description": "Tenant ID (optional, will use default if not provided)"
                    }
                },
                "required": ["member_id"]
            },
            handler=self.get_member
        ))

        # Create member tool
        self.register_tool(Tool(
            name="create_member",
            description="Create a new member",
            input_schema={
                "type": "object",
                "properties": {
                    "username": {
                        "type": "string",
                        "description": "Username for the member"
                    },
                    "email": {
                        "type": "string",
                        "description": "Email address"
                    },
                    "password": {
                        "type": "string",
                        "description": "Password (optional, will be auto-generated if not provided)"
                    },
                    "is_virtual": {
                        "type": "boolean",
                        "description": "Whether this is a virtual user",
                        "default": True
                    },
                    "auth_token": {
                        "type": "string",
                        "description": "Authentication token (optional, will use default if not provided)"
                    },
                    "tenant_id": {
                        "type": "integer",
                        "description": "Tenant ID (optional, will use default if not provided)"
                    }
                },
                "required": ["username", "email"]
            },
            handler=self.create_member
        ))

        # Update member tool
        self.register_tool(Tool(
            name="update_member",
            description="Update a member's information",
            input_schema={
                "type": "object",
                "properties": {
                    "member_id": {
                        "type": "string",
                        "description": "Member ID"
                    },
                    "username": {
                        "type": "string",
                        "description": "New username (optional)"
                    },
                    "email": {
                        "type": "string",
                        "description": "New email (optional)"
                    },
                    "is_virtual": {
                        "type": "boolean",
                        "description": "Update virtual status (optional)"
                    },
                    "auth_token": {
                        "type": "string",
                        "description": "Authentication token (optional, will use default if not provided)"
                    },
                    "tenant_id": {
                        "type": "integer",
                        "description": "Tenant ID (optional, will use default if not provided)"
                    }
                },
                "required": ["member_id"]
            },
            handler=self.update_member
        ))

        # Delete member tool
        self.register_tool(Tool(
            name="delete_member",
            description="Delete a member",
            input_schema={
                "type": "object",
                "properties": {
                    "member_id": {
                        "type": "string",
                        "description": "Member ID"
                    },
                    "auth_token": {
                        "type": "string",
                        "description": "Authentication token (optional, will use default if not provided)"
                    },
                    "tenant_id": {
                        "type": "integer",
                        "description": "Tenant ID (optional, will use default if not provided)"
                    }
                },
                "required": ["member_id"]
            },
            handler=self.delete_member
        ))

        # Update member password tool
        self.register_tool(Tool(
            name="update_member_password",
            description="Update a member's password",
            input_schema={
                "type": "object",
                "properties": {
                    "member_id": {
                        "type": "string",
                        "description": "Member ID"
                    },
                    "password": {
                        "type": "string",
                        "description": "New password"
                    },
                    "auth_token": {
                        "type": "string",
                        "description": "Authentication token (optional, will use default if not provided)"
                    },
                    "tenant_id": {
                        "type": "integer",
                        "description": "Tenant ID (optional, will use default if not provided)"
                    }
                },
                "required": ["member_id", "password"]
            },
            handler=self.update_member_password
        ))

        # List roles tool
        self.register_tool(Tool(
            name="list_roles",
            description="List all available roles",
            input_schema={
                "type": "object",
                "properties": {
                    "page": {
                        "type": "integer",
                        "description": "Page number",
                        "default": 1
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Items per page",
                        "default": 10
                    },
                    "auth_token": {
                        "type": "string",
                        "description": "Authentication token (optional, will use default if not provided)"
                    },
                    "tenant_id": {
                        "type": "integer",
                        "description": "Tenant ID (optional, will use default if not provided)"
                    }
                }
            },
            handler=self.list_roles
        ))

        # Create role tool
        self.register_tool(Tool(
            name="create_role",
            description="Create a new role/position in an organization",
            input_schema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Role name"
                    },
                    "code": {
                        "type": "string",
                        "description": "Role code (optional, auto-generated when omitted)"
                    },
                    "org_id": {
                        "type": "integer",
                        "description": "Organization ID this role belongs to"
                    },
                    "description": {
                        "type": "string",
                        "description": "Role description (optional)"
                    },
                    "is_position": {
                        "type": "boolean",
                        "description": "Whether this is a position role",
                        "default": False
                    },
                    "active": {
                        "type": "boolean",
                        "description": "Whether role is active",
                        "default": True
                    },
                    "auth_token": {
                        "type": "string",
                        "description": "Authentication token (optional, will use default if not provided)"
                    },
                    "tenant_id": {
                        "type": "integer",
                        "description": "Tenant ID (optional, will use default if not provided)"
                    }
                },
                "required": ["name", "org_id"]
            },
            handler=self.create_role
        ))

        # Assign role tool
        self.register_tool(Tool(
            name="assign_role",
            description="Assign a role to a member",
            input_schema={
                "type": "object",
                "properties": {
                    "member_id": {
                        "type": "string",
                        "description": "Member ID"
                    },
                    "role_id": {
                        "type": "string",
                        "description": "Role ID"
                    },
                    "auth_token": {
                        "type": "string",
                        "description": "Authentication token (optional, will use default if not provided)"
                    },
                    "tenant_id": {
                        "type": "integer",
                        "description": "Tenant ID (optional, will use default if not provided)"
                    }
                },
                "required": ["member_id", "role_id"]
            },
            handler=self.assign_role
        ))

        # List organizations tool
        self.register_tool(Tool(
            name="list_orgs",
            description="List all organization units",
            input_schema={
                "type": "object",
                "properties": {
                    "page": {
                        "type": "integer",
                        "description": "Page number (1-indexed)",
                        "default": 1
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of items per page",
                        "default": 10
                    },
                    "auth_token": {
                        "type": "string",
                        "description": "Authentication token (optional, will use default if not provided)"
                    },
                    "tenant_id": {
                        "type": "integer",
                        "description": "Tenant ID (optional, will use default if not provided)"
                    }
                }
            },
            handler=self.list_orgs
        ))

        # Get organization tool
        self.register_tool(Tool(
            name="get_org",
            description="Get details of a specific organization unit",
            input_schema={
                "type": "object",
                "properties": {
                    "org_id": {
                        "type": "string",
                        "description": "Organization unit ID"
                    },
                    "auth_token": {
                        "type": "string",
                        "description": "Authentication token (optional, will use default if not provided)"
                    },
                    "tenant_id": {
                        "type": "integer",
                        "description": "Tenant ID (optional, will use default if not provided)"
                    }
                },
                "required": ["org_id"]
            },
            handler=self.get_org
        ))

        # Create organization tool
        self.register_tool(Tool(
            name="create_org",
            description="Create a new organization unit",
            input_schema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of the organization unit"
                    },
                    "type": {
                        "type": "string",
                        "enum": ["company", "dept", "team", "committee", "project", "taskforce"],
                        "description": "Type of organization unit (optional, auto-inferred if omitted)"
                    },
                    "parent_id": {
                        "type": "integer",
                        "description": "Parent organization ID (optional)"
                    },
                    "description": {
                        "type": "string",
                        "description": "Description (optional)"
                    },
                    "is_temporary": {
                        "type": "boolean",
                        "description": "Whether this is a temporary unit",
                        "default": False
                    },
                    "valid_until": {
                        "type": "string",
                        "format": "date-time",
                        "description": "Expiration date for temporary units (optional)"
                    },
                    "force_create": {
                        "type": "boolean",
                        "description": "Force create even when similar organization names already exist",
                        "default": False
                    },
                    "auth_token": {
                        "type": "string",
                        "description": "Authentication token (optional, will use default if not provided)"
                    },
                    "tenant_id": {
                        "type": "integer",
                        "description": "Tenant ID (optional, will use default if not provided)"
                    }
                },
                "required": ["name"]
            },
            handler=self.create_org
        ))

        # Update organization tool
        self.register_tool(Tool(
            name="update_org",
            description="Update an organization unit",
            input_schema={
                "type": "object",
                "properties": {
                    "org_id": {
                        "type": "string",
                        "description": "Organization unit ID"
                    },
                    "name": {
                        "type": "string",
                        "description": "New name (optional)"
                    },
                    "description": {
                        "type": "string",
                        "description": "New description (optional)"
                    },
                    "is_temporary": {
                        "type": "boolean",
                        "description": "Update temporary status (optional)"
                    },
                    "valid_until": {
                        "type": "string",
                        "format": "date-time",
                        "description": "Update expiration date (optional)"
                    },
                    "auth_token": {
                        "type": "string",
                        "description": "Authentication token (optional, will use default if not provided)"
                    },
                    "tenant_id": {
                        "type": "integer",
                        "description": "Tenant ID (optional, will use default if not provided)"
                    }
                },
                "required": ["org_id"]
            },
            handler=self.update_org
        ))

        # Delete organization tool
        self.register_tool(Tool(
            name="delete_org",
            description="Delete/archive an organization unit",
            input_schema={
                "type": "object",
                "properties": {
                    "org_id": {
                        "type": "string",
                        "description": "Organization unit ID"
                    },
                    "auth_token": {
                        "type": "string",
                        "description": "Authentication token (optional, will use default if not provided)"
                    },
                    "tenant_id": {
                        "type": "integer",
                        "description": "Tenant ID (optional, will use default if not provided)"
                    }
                },
                "required": ["org_id"]
            },
            handler=self.delete_org
        ))

        # Assign member to organization tool
        self.register_tool(Tool(
            name="assign_member_to_org",
            description="Assign a member to an organization unit",
            input_schema={
                "type": "object",
                "properties": {
                    "member_id": {
                        "type": "string",
                        "description": "Member ID"
                    },
                    "org_id": {
                        "type": "string",
                        "description": "Organization unit ID"
                    },
                    "auth_token": {
                        "type": "string",
                        "description": "Authentication token (optional, will use default if not provided)"
                    },
                    "tenant_id": {
                        "type": "integer",
                        "description": "Tenant ID (optional, will use default if not provided)"
                    }
                },
                "required": ["member_id", "org_id"]
            },
            handler=self.assign_member_to_org
        ))

        # Get member organizations tool
        self.register_tool(Tool(
            name="get_member_orgs",
            description="Get all organizations a member belongs to",
            input_schema={
                "type": "object",
                "properties": {
                    "member_id": {
                        "type": "string",
                        "description": "Member ID"
                    },
                    "auth_token": {
                        "type": "string",
                        "description": "Authentication token (optional, will use default if not provided)"
                    },
                    "tenant_id": {
                        "type": "integer",
                        "description": "Tenant ID (optional, will use default if not provided)"
                    }
                },
                "required": ["member_id"]
            },
            handler=self.get_member_orgs
        ))

        # Remove member from organization tool
        self.register_tool(Tool(
            name="remove_member_from_org",
            description="Remove a member from an organization unit",
            input_schema={
                "type": "object",
                "properties": {
                    "member_id": {
                        "type": "string",
                        "description": "Member ID"
                    },
                    "org_id": {
                        "type": "string",
                        "description": "Organization unit ID"
                    },
                    "auth_token": {
                        "type": "string",
                        "description": "Authentication token (optional, will use default if not provided)"
                    },
                    "tenant_id": {
                        "type": "integer",
                        "description": "Tenant ID (optional, will use default if not provided)"
                    }
                },
                "required": ["member_id", "org_id"]
            },
            handler=self.remove_member_from_org
        ))

        # Get organization hierarchy tool
        self.register_tool(Tool(
            name="get_org_hierarchy",
            description="Get the hierarchical relationships (ancestors/descendants) of an organization unit",
            input_schema={
                "type": "object",
                "properties": {
                    "org_id": {
                        "type": "string",
                        "description": "Organization unit ID"
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["ancestors", "descendants", "both"],
                        "description": "Query direction (ancestors=parent organizations, descendants=child organizations, both=both)",
                        "default": "both"
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "Maximum hierarchy depth (1-10)",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 10
                    },
                    "auth_token": {
                        "type": "string",
                        "description": "Authentication token (optional, will use default if not provided)"
                    },
                    "tenant_id": {
                        "type": "integer",
                        "description": "Tenant ID (optional, will use default if not provided)"
                    }
                },
                "required": ["org_id"]
            },
            handler=self.get_org_hierarchy
        ))

        # Submit audit event tool
        self.register_tool(Tool(
            name="submit_audit_event",
            description="Submit a single audit event to the membership audit service",
            input_schema={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["AUTH", "SYSTEM", "DATA", "WORKFLOW", "API"],
                        "description": "Event category"
                    },
                    "action": {
                        "type": "string",
                        "description": "Event action (e.g., USER_LOGIN, MCP_CLIENT_CONNECT)"
                    },
                    "tenant_id": {
                        "type": "integer",
                        "description": "Tenant ID"
                    },
                    "actor": {
                        "type": "object",
                        "description": "Event actor (who performed the action)",
                        "properties": {
                            "memberId": {
                                "type": "integer",
                                "description": "Member ID (use memberId XOR systemCode)"
                            },
                            "systemCode": {
                                "type": "string",
                                "description": "System/application code (use memberId XOR systemCode)"
                            },
                            "ip": {
                                "type": "string",
                                "description": "Actor IP address"
                            }
                        }
                    },
                    "target": {
                        "type": "object",
                        "description": "Event target (what was acted upon)",
                        "properties": {
                            "type": {
                                "type": "string",
                                "description": "Target type (e.g., user, mcp_connection, document)"
                            },
                            "id": {
                                "type": "string",
                                "description": "Target ID"
                            }
                        }
                    },
                    "metadata": {
                        "type": "object",
                        "description": "Additional metadata"
                    },
                    "occurred_at": {
                        "type": "string",
                        "format": "date-time",
                        "description": "Event timestamp (optional, defaults to now)"
                    },
                    "auth_token": {
                        "type": "string",
                        "description": "Authentication token (optional, will use default if not provided)"
                    }
                },
                "required": ["category", "action", "tenant_id", "actor"]
            },
            handler=self.submit_audit_event
        ))

        # Submit batch audit events tool
        self.register_tool(Tool(
            name="submit_audit_events_batch",
            description="Submit multiple audit events to the membership audit service",
            input_schema={
                "type": "object",
                "properties": {
                    "events": {
                        "type": "array",
                        "description": "List of audit events",
                        "items": {
                            "type": "object",
                            "properties": {
                                "category": {
                                    "type": "string",
                                    "enum": ["AUTH", "SYSTEM", "DATA", "WORKFLOW", "API"]
                                },
                                "action": {"type": "string"},
                                "tenant_id": {"type": "integer"},
                                "actor": {"type": "object"},
                                "target": {"type": "object"},
                                "metadata": {"type": "object"},
                                "occurred_at": {"type": "string", "format": "date-time"}
                            },
                            "required": ["category", "action", "tenant_id", "actor"]
                        },
                        "minItems": 1,
                        "maxItems": 100
                    },
                    "auth_token": {
                        "type": "string",
                        "description": "Authentication token (optional, will use default if not provided)"
                    }
                },
                "required": ["events"]
            },
            handler=self.submit_audit_events_batch
        ))

    async def list_members(
        self,
        page: int = 1,
        limit: int = 10,
        search: Optional[str] = None,
        auth_token: Optional[str] = None,
        tenant_id: Optional[int] = None
    ) -> ToolResult:
        """List members."""
        try:
            # Determine which auth_token and tenant_id to use
            effective_token = auth_token or self.auth_token
            effective_tenant = tenant_id or self.tenant_id

            # Validate that we have the required authentication
            if not effective_token:
                logger.error("list_members called without auth_token")
                return ToolResult.error(
                    content="Authentication required. Please provide auth_token parameter.",
                    error_code="AUTH_REQUIRED"
                )

            # If no tenant_id, use default (for superadmin or system users)
            if not effective_tenant:
                logger.info("No tenant_id provided, using default tenant_id=1")
                effective_tenant = 1

            # Log for debugging
            logger.debug(f"list_members called with token: {effective_token[:20] if effective_token else 'None'}..., tenant: {effective_tenant}")

            params = {
                "query": {
                    "page": max(1, page),
                    "limit": max(1, min(100, limit))
                }
            }
            if search:
                params["query"]["search"] = search

            response = await self.http_client.execute(
                command="GET /v2/members",
                params=params,
                auth_token=effective_token,
                tenant_id=effective_tenant
            )

            members = response.get("data", [])
            count = len(members)

            # Format human-readable summary
            summary_lines = [f"Found {count} members"]
            if members:
                summary_lines.append("\nMembers:")
                for member in members[:5]:  # Show first 5 members
                    name = member.get("fullName", member.get("username", "Unknown"))
                    status = member.get("status", "unknown")
                    summary_lines.append(f"  • {name} ({status})")
                if count > 5:
                    summary_lines.append(f"  ... and {count - 5} more")

            content = "\n".join(summary_lines)
            return ToolResult.success(
                content=content,
                data=response
            )
        except Exception as e:
            logger.error(f"Error listing members: {e}")
            return ToolResult.error(
                content=f"Failed to list members: {str(e)}",
                error_code="LIST_MEMBERS_FAILED"
            )

    async def get_member(self, member_id: str, auth_token: Optional[str] = None, tenant_id: Optional[int] = None) -> ToolResult:
        """Get member details."""
        try:
            params = {
                "path": {
                    "member_id": member_id
                }
            }
            response = await self.http_client.execute(
                command="GET /v2/members/{member_id}",
                params=params,
                auth_token=auth_token or self.auth_token,
                tenant_id=tenant_id or self.tenant_id
            )

            # Format human-readable member details
            member = response.get("member", response)
            summary_lines = [
                f"Member: {member.get('fullName', member.get('username', 'Unknown'))}",
                f"ID: {member.get('id', 'N/A')}",
                f"Email: {member.get('email', 'N/A')}",
                f"Status: {member.get('status', 'unknown')}"
            ]
            content = "\n".join(summary_lines)

            return ToolResult.success(
                content=content,
                data=response
            )
        except Exception as e:
            logger.error(f"Error getting member {member_id}: {e}")
            return ToolResult.error(
                content=f"Failed to get member: {str(e)}",
                error_code="GET_MEMBER_FAILED"
            )

    async def create_member(
        self,
        username: str,
        email: str,
        password: Optional[str] = None,
        is_virtual: bool = True,
        auth_token: Optional[str] = None,
        tenant_id: Optional[int] = None
    ) -> ToolResult:
        """Create a new member."""
        try:
            payload = {
                "username": username,
                "email": email,
                "is_virtual": is_virtual
            }
            if password:
                payload["password"] = password

            params = {
                "body": payload
            }
            response = await self.http_client.execute(
                command="POST /v2/members",
                params=params,
                auth_token=auth_token or self.auth_token,
                tenant_id=tenant_id or self.tenant_id
            )

            return ToolResult.success(
                content=f"Created member {username}",
                data=response
            )
        except Exception as e:
            logger.error(f"Error creating member {username}: {e}")
            return ToolResult.error(
                content=f"Failed to create member: {str(e)}",
                error_code="CREATE_MEMBER_FAILED"
            )

    async def update_member(
        self,
        member_id: str,
        username: Optional[str] = None,
        email: Optional[str] = None,
        is_virtual: Optional[bool] = None,
        auth_token: Optional[str] = None,
        tenant_id: Optional[int] = None
    ) -> ToolResult:
        """Update member information."""
        try:
            payload = {}
            if username:
                payload["username"] = username
            if email:
                payload["email"] = email
            if is_virtual is not None:
                payload["is_virtual"] = is_virtual

            if not payload:
                return ToolResult.error(
                    content="No fields to update",
                    error_code="INVALID_UPDATE"
                )

            params = {
                "path": {
                    "member_id": member_id
                },
                "body": payload
            }
            response = await self.http_client.execute(
                command="PUT /v2/members/{member_id}",
                params=params,
                auth_token=auth_token or self.auth_token,
                tenant_id=tenant_id or self.tenant_id
            )

            return ToolResult.success(
                content=f"Updated member {member_id}",
                data=response
            )
        except Exception as e:
            logger.error(f"Error updating member {member_id}: {e}")
            return ToolResult.error(
                content=f"Failed to update member: {str(e)}",
                error_code="UPDATE_MEMBER_FAILED"
            )

    async def delete_member(self, member_id: str, auth_token: Optional[str] = None, tenant_id: Optional[int] = None) -> ToolResult:
        """Delete a member."""
        try:
            params = {
                "path": {
                    "member_id": member_id
                }
            }
            response = await self.http_client.execute(
                command="DELETE /v2/members/{member_id}",
                params=params,
                auth_token=auth_token or self.auth_token,
                tenant_id=tenant_id or self.tenant_id
            )

            return ToolResult.success(
                content=f"Deleted member {member_id}",
                data=response
            )
        except Exception as e:
            logger.error(f"Error deleting member {member_id}: {e}")
            return ToolResult.error(
                content=f"Failed to delete member: {str(e)}",
                error_code="DELETE_MEMBER_FAILED"
            )

    async def update_member_password(
        self,
        member_id: str,
        password: str,
        auth_token: Optional[str] = None,
        tenant_id: Optional[int] = None
    ) -> ToolResult:
        """Update a member's password."""
        try:
            if not password:
                return ToolResult.error(
                    content="Password cannot be empty",
                    error_code="INVALID_PASSWORD"
                )

            params = {
                "path": {
                    "member_id": member_id
                },
                "body": {
                    "password": password
                }
            }
            response = await self.http_client.execute(
                command="POST /v2/members/{member_id}/password",
                params=params,
                auth_token=auth_token or self.auth_token,
                tenant_id=tenant_id or self.tenant_id
            )

            return ToolResult.success(
                content=f"Updated password for member {member_id}",
                data=response
            )
        except Exception as e:
            logger.error(f"Error updating password for member {member_id}: {e}")
            return ToolResult.error(
                content=f"Failed to update password: {str(e)}",
                error_code="UPDATE_PASSWORD_FAILED"
            )

    async def list_roles(self, page: int = 1, limit: int = 10, auth_token: Optional[str] = None, tenant_id: Optional[int] = None) -> ToolResult:
        """List available roles."""
        try:
            params = {
                "query": {
                    "page": max(1, page),
                    "limit": max(1, min(100, limit))
                }
            }
            response = await self.http_client.execute(
                command="GET /v2/roles",
                params=params,
                auth_token=auth_token or self.auth_token,
                tenant_id=tenant_id or self.tenant_id
            )

            roles = response.get("data", response.get("roles", []))
            count = len(roles)

            # Format human-readable summary
            summary_lines = [f"Found {count} roles"]
            if roles:
                summary_lines.append("\nRoles:")
                for role in roles[:5]:  # Show first 5 roles
                    role_name = role.get("name", role.get("id", "Unknown"))
                    summary_lines.append(f"  • {role_name}")
                if count > 5:
                    summary_lines.append(f"  ... and {count - 5} more")

            content = "\n".join(summary_lines)
            return ToolResult.success(
                content=content,
                data=response
            )
        except Exception as e:
            logger.error(f"Error listing roles: {e}")
            return ToolResult.error(
                content=f"Failed to list roles: {str(e)}",
                error_code="LIST_ROLES_FAILED"
            )

    async def create_role(
        self,
        name: str,
        org_id: int,
        code: Optional[str] = None,
        description: Optional[str] = None,
        is_position: bool = False,
        active: bool = True,
        auth_token: Optional[str] = None,
        tenant_id: Optional[int] = None
    ) -> ToolResult:
        """Create a role in an organization."""
        try:
            effective_token = auth_token or self.auth_token
            effective_tenant = tenant_id or self.tenant_id
            org_id_int = int(org_id)

            # Pre-check existing roles in this org:
            # - same name => reuse directly
            # - collect existing codes for uniqueness
            roles_resp = await self.http_client.execute(
                command="GET /v2/roles",
                params={"query": {"page": 1, "limit": 200, "org_id": org_id_int}},
                auth_token=effective_token,
                tenant_id=effective_tenant
            )
            existing_roles = roles_resp.get("data", []) if isinstance(roles_resp, dict) else []

            existing_codes = set()
            for role in existing_roles:
                role_name = str(role.get("name", "")).strip().lower()
                role_org = role.get("org_id", role.get("orgId"))
                role_code = role.get("code")

                if role_code:
                    existing_codes.add(str(role_code).upper())

                if role_name == name.strip().lower() and (
                    role_org is None or str(role_org) == str(org_id_int)
                ):
                    return ToolResult.success(
                        content=f"Role already exists. Reused existing: {name}",
                        data=role
                    )

            final_code = self._build_unique_role_code(
                base_code=code or self._role_code_from_name(name),
                org_id=org_id_int,
                existing_codes=existing_codes
            )

            payload = {
                "name": name,
                "code": final_code,
                "org_id": org_id_int,
                "is_position": is_position,
                "active": active
            }
            if description:
                payload["description"] = description

            params = {
                "body": payload
            }
            response = await self.http_client.execute(
                command="POST /v2/roles",
                params=params,
                auth_token=effective_token,
                tenant_id=effective_tenant
            )

            return ToolResult.success(
                content=f"Created role {name} (code: {final_code})",
                data=response
            )
        except Exception as e:
            logger.error(f"Error creating role {name}: {e}")
            return ToolResult.error(
                content=f"Failed to create role: {str(e)}",
                error_code="CREATE_ROLE_FAILED"
            )

    async def assign_role(self, member_id: str, role_id: str, auth_token: Optional[str] = None, tenant_id: Optional[int] = None) -> ToolResult:
        """Assign a role to a member."""
        try:
            payload = {"role_id": role_id}
            params = {
                "path": {
                    "member_id": member_id
                },
                "body": payload
            }
            response = await self.http_client.execute(
                command="POST /v2/members/{member_id}/roles",
                params=params,
                auth_token=auth_token or self.auth_token,
                tenant_id=tenant_id or self.tenant_id
            )

            return ToolResult.success(
                content=f"Assigned role {role_id} to member {member_id}",
                data=response
            )
        except Exception as e:
            logger.error(f"Error assigning role: {e}")
            return ToolResult.error(
                content=f"Failed to assign role: {str(e)}",
                error_code="ASSIGN_ROLE_FAILED"
            )

    async def list_orgs(self, page: int = 1, limit: int = 10, auth_token: Optional[str] = None, tenant_id: Optional[int] = None) -> ToolResult:
        """List all organization units."""
        try:
            params = {
                "query": {
                    "page": max(1, page),
                    "limit": max(1, min(100, limit))
                }
            }
            response = await self.http_client.execute(
                command="GET /v2/orgs",
                params=params,
                auth_token=auth_token or self.auth_token,
                tenant_id=tenant_id or self.tenant_id
            )

            orgs = response.get("data", [])
            count = len(orgs)

            # Format human-readable summary
            summary_lines = [f"Found {count} organization units"]
            if orgs:
                summary_lines.append("\nOrganizations:")
                for org in orgs[:5]:  # Show first 5 orgs
                    org_name = org.get("name", org.get("id", "Unknown"))
                    summary_lines.append(f"  • {org_name}")
                if count > 5:
                    summary_lines.append(f"  ... and {count - 5} more")

            content = "\n".join(summary_lines)
            return ToolResult.success(
                content=content,
                data=response
            )
        except Exception as e:
            logger.error(f"Error listing organizations: {e}")
            return ToolResult.error(
                content=f"Failed to list organizations: {str(e)}",
                error_code="LIST_ORGS_FAILED"
            )

    async def get_org(self, org_id: str, auth_token: Optional[str] = None, tenant_id: Optional[int] = None) -> ToolResult:
        """Get organization unit details."""
        try:
            params = {
                "path": {
                    "org_id": org_id
                }
            }
            response = await self.http_client.execute(
                command="GET /v2/orgs/{org_id}",
                params=params,
                auth_token=auth_token or self.auth_token,
                tenant_id=tenant_id or self.tenant_id
            )

            return ToolResult.success(
                content=f"Retrieved organization {org_id}",
                data=response
            )
        except Exception as e:
            logger.error(f"Error getting organization {org_id}: {e}")
            return ToolResult.error(
                content=f"Failed to get organization: {str(e)}",
                error_code="GET_ORG_FAILED"
            )

    async def get_org_hierarchy(
        self,
        org_id: str,
        direction: str = "both",
        max_depth: int = 5,
        auth_token: Optional[str] = None,
        tenant_id: Optional[int] = None
    ) -> ToolResult:
        """Get organization hierarchy (ancestors/descendants) by querying all orgs and building tree."""
        try:
            # Validate and convert org_id to integer
            try:
                org_id_int = int(org_id)
            except (ValueError, TypeError):
                return ToolResult.error(
                    content=f"Invalid org_id: {org_id}. Must be an integer.",
                    error_code="INVALID_ORG_ID"
                )
            
            # Validate parameters
            if direction not in ["ancestors", "descendants", "both"]:
                direction = "both"
            if max_depth < 1 or max_depth > 10:
                max_depth = 5

            # Query all organizations
            try:
                orgs_response = await self.http_client.execute(
                    command="GET /v2/orgs",
                    params={"query": {}},
                    auth_token=auth_token or self.auth_token,
                    tenant_id=tenant_id or self.tenant_id
                )
                
                # Extract org list from response
                org_list = []
                if isinstance(orgs_response, dict):
                    org_list = orgs_response.get("data", [])
                
                # Build org lookup map
                org_map = {org.get("id"): org for org in org_list if org.get("id")}
                
                # Find target org
                target_org = org_map.get(org_id_int)
                if not target_org:
                    return ToolResult.error(
                        content=f"Organization {org_id} not found",
                        error_code="ORG_NOT_FOUND"
                    )
                
                # Build hierarchy
                ancestors = []
                descendants = []
                
                # Get ancestors by walking up parent_id chain
                if direction in ["ancestors", "both"]:
                    current = target_org
                    depth = 0
                    while current and depth < max_depth:
                        parent_id = current.get("parentId")
                        if not parent_id or parent_id == current.get("id"):
                            break
                        parent = org_map.get(parent_id)
                        if not parent:
                            break
                        ancestors.insert(0, parent)  # Insert at beginning to maintain order
                        current = parent
                        depth += 1
                
                # Get descendants by finding all orgs with parentId pointing to org_id_int
                if direction in ["descendants", "both"]:
                    def find_descendants(parent_id, depth):
                        if depth >= max_depth:
                            return []
                        children = [org for org in org_list if org.get("parentId") == parent_id]
                        result = list(children)
                        for child in children:
                            result.extend(find_descendants(child.get("id"), depth + 1))
                        return result
                    
                    descendants = find_descendants(org_id_int, 0)
                
                # Format response
                summary_lines = [f"Organization Hierarchy for ID {org_id_int}: {target_org.get('name', 'Unknown')}"]
                
                # Process ancestors if present
                if ancestors:
                    summary_lines.append(f"\n👤 Parent Organizations ({len(ancestors)}):")
                    for ancestor in ancestors:
                        name = ancestor.get("name", ancestor.get("id", "Unknown"))
                        org_type = ancestor.get("type", "")
                        summary_lines.append(f"  • {name} ({org_type})")
                
                # Process descendants if present
                if descendants:
                    summary_lines.append(f"\n👥 Child Organizations ({len(descendants)}):")
                    for descendant in descendants[:20]:  # Limit display
                        name = descendant.get("name", descendant.get("id", "Unknown"))
                        org_type = descendant.get("type", "")
                        summary_lines.append(f"  • {name} ({org_type})")
                    if len(descendants) > 20:
                        summary_lines.append(f"  ... and {len(descendants) - 20} more")
                
                if not ancestors and not descendants:
                    summary_lines.append("\nNo hierarchical relationships found.")
                
                content = "\n".join(summary_lines)
                
                # Return structured response
                response_data = {
                    "org_id": org_id_int,
                    "ancestors": ancestors,
                    "descendants": descendants
                }
                
                return ToolResult.success(
                    content=content,
                    data=response_data
                )
            
            except Exception as e:
                logger.error(f"Error querying organizations: {e}")
                raise
                
        except Exception as e:
            logger.error(f"Error getting organization hierarchy for {org_id}: {e}")
            return ToolResult.error(
                content=f"Failed to get organization hierarchy: {str(e)}",
                error_code="GET_ORG_HIERARCHY_FAILED"
            )

    async def create_org(
        self,
        name: str,
        type: Optional[str] = None,
        parent_id: Optional[int] = None,
        description: Optional[str] = None,
        is_temporary: bool = False,
        valid_until: Optional[str] = None,
        force_create: bool = False,
        auth_token: Optional[str] = None,
        tenant_id: Optional[int] = None
    ) -> ToolResult:
        """Create a new organization unit with semantic dedup safeguards."""
        try:
            effective_token = auth_token or self.auth_token
            effective_tenant = tenant_id or self.tenant_id

            # Infer org type when omitted: root defaults to company, child defaults to dept
            inferred_type = type or ("company" if parent_id is None else "dept")

            # Pre-check existing orgs to avoid semantic duplicates
            orgs_resp = await self.http_client.execute(
                command="GET /v2/orgs",
                params={"query": {"page": 1, "limit": 200}},
                auth_token=effective_token,
                tenant_id=effective_tenant
            )
            existing_orgs = orgs_resp.get("data", []) if isinstance(orgs_resp, dict) else []

            target_key = self._org_name_semantic_key(name)
            target_parent = parent_id

            # 1) Exact semantic match under same parent -> reuse
            for org in existing_orgs:
                org_name = str(org.get("name", ""))
                org_parent = org.get("parentId")
                if org_parent != target_parent:
                    continue
                if self._org_name_semantic_key(org_name) == target_key:
                    return ToolResult.success(
                        content=f"Organization already exists. Reused existing: {org_name}",
                        data=org
                    )

            # 2) Ambiguous similar names -> require explicit confirmation
            if not force_create:
                similar = []
                for org in existing_orgs:
                    org_name = str(org.get("name", ""))
                    org_parent = org.get("parentId")
                    if org_parent != target_parent:
                        continue
                    score = self._org_name_similarity(name, org_name)
                    if score >= 0.75:
                        similar.append({
                            "id": org.get("id"),
                            "name": org_name,
                            "similarity": round(score, 3)
                        })

                if similar:
                    similar_sorted = sorted(similar, key=lambda x: x["similarity"], reverse=True)[:5]
                    return ToolResult.error(
                        content=(
                            "Found similar existing organization names. "
                            "Please confirm reuse vs force create. Candidates: "
                            f"{similar_sorted}"
                        ),
                        error_code="AMBIGUOUS_ORG_MATCH"
                    )

            payload = {
                "name": name,
                "type": inferred_type,
                "isTemporary": is_temporary
            }
            if parent_id is not None:
                payload["parentId"] = parent_id
            if description:
                payload["description"] = description
            if valid_until:
                payload["validUntil"] = valid_until

            params = {"body": payload}
            response = await self.http_client.execute(
                command="POST /v2/orgs",
                params=params,
                auth_token=effective_token,
                tenant_id=effective_tenant
            )

            return ToolResult.success(
                content=f"Created organization {name}",
                data=response
            )
        except Exception as e:
            logger.error(f"Error creating organization {name}: {e}")
            return ToolResult.error(
                content=f"Failed to create organization: {str(e)}",
                error_code="CREATE_ORG_FAILED"
            )


    async def update_org(
        self,
        org_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        is_temporary: Optional[bool] = None,
        valid_until: Optional[str] = None,
        auth_token: Optional[str] = None,
        tenant_id: Optional[int] = None
    ) -> ToolResult:
        """Update an organization unit."""
        try:
            payload = {}
            if name:
                payload["name"] = name
            if description:
                payload["description"] = description
            if is_temporary is not None:
                payload["isTemporary"] = is_temporary
            if valid_until:
                payload["validUntil"] = valid_until

            if not payload:
                return ToolResult.error(
                    content="No fields to update",
                    error_code="INVALID_UPDATE"
                )

            params = {
                "path": {
                    "org_id": org_id
                },
                "body": payload
            }
            response = await self.http_client.execute(
                command="PATCH /v2/orgs/{org_id}",
                params=params,
                auth_token=auth_token or self.auth_token,
                tenant_id=tenant_id or self.tenant_id
            )

            return ToolResult.success(
                content=f"Updated organization {org_id}",
                data=response
            )
        except Exception as e:
            logger.error(f"Error updating organization {org_id}: {e}")
            return ToolResult.error(
                content=f"Failed to update organization: {str(e)}",
                error_code="UPDATE_ORG_FAILED"
            )

    async def delete_org(self, org_id: str, auth_token: Optional[str] = None, tenant_id: Optional[int] = None) -> ToolResult:
        """Delete/archive an organization unit."""
        try:
            params = {
                "path": {
                    "org_id": org_id
                }
            }
            response = await self.http_client.execute(
                command="DELETE /v2/orgs/{org_id}",
                params=params,
                auth_token=auth_token or self.auth_token,
                tenant_id=tenant_id or self.tenant_id
            )

            return ToolResult.success(
                content=f"Deleted organization {org_id}",
                data=response
            )
        except Exception as e:
            logger.error(f"Error deleting organization {org_id}: {e}")
            return ToolResult.error(
                content=f"Failed to delete organization: {str(e)}",
                error_code="DELETE_ORG_FAILED"
            )

    async def assign_member_to_org(self, member_id: str, org_id: str, auth_token: Optional[str] = None, tenant_id: Optional[int] = None) -> ToolResult:
        """Assign a member to an organization unit."""
        try:
            payload = {"org_id": org_id}
            params = {
                "path": {
                    "member_id": member_id
                },
                "body": payload
            }
            response = await self.http_client.execute(
                command="POST /v2/members/{member_id}/orgs",
                params=params,
                auth_token=auth_token or self.auth_token,
                tenant_id=tenant_id or self.tenant_id
            )

            return ToolResult.success(
                content=f"Assigned member {member_id} to organization {org_id}",
                data=response
            )
        except Exception as e:
            logger.error(f"Error assigning member to organization: {e}")
            return ToolResult.error(
                content=f"Failed to assign member to organization: {str(e)}",
                error_code="ASSIGN_MEMBER_TO_ORG_FAILED"
            )

    async def get_member_orgs(self, member_id: str, auth_token: Optional[str] = None, tenant_id: Optional[int] = None) -> ToolResult:
        """Get all organizations a member belongs to."""
        try:
            params = {
                "path": {
                    "member_id": member_id
                }
            }
            response = await self.http_client.execute(
                command="GET /v2/members/{member_id}/orgs",
                params=params,
                auth_token=auth_token or self.auth_token,
                tenant_id=tenant_id or self.tenant_id
            )

            count = len(response.get("data", []))
            return ToolResult.success(
                content=f"Found {count} organizations for member {member_id}",
                data=response
            )
        except Exception as e:
            logger.error(f"Error getting member organizations: {e}")
            return ToolResult.error(
                content=f"Failed to get member organizations: {str(e)}",
                error_code="GET_MEMBER_ORGS_FAILED"
            )

    async def remove_member_from_org(self, member_id: str, org_id: str, auth_token: Optional[str] = None, tenant_id: Optional[int] = None) -> ToolResult:
        """Remove a member from an organization unit."""
        try:
            params = {
                "path": {
                    "member_id": member_id,
                    "org_id": org_id
                }
            }
            response = await self.http_client.execute(
                command="DELETE /v2/members/{member_id}/orgs/{org_id}",
                params=params,
                auth_token=auth_token or self.auth_token,
                tenant_id=tenant_id or self.tenant_id
            )

            return ToolResult.success(
                content=f"Removed member {member_id} from organization {org_id}",
                data=response
            )
        except Exception as e:
            logger.error(f"Error removing member from organization: {e}")
            return ToolResult.error(
                content=f"Failed to remove member from organization: {str(e)}",
                error_code="REMOVE_MEMBER_FROM_ORG_FAILED"
            )

    def _org_name_semantic_key(self, name: str) -> str:
        """Build a normalized semantic key for organization names."""
        if not name:
            return ""
        normalized = re.sub(r"[^a-z0-9\s]", " ", name.lower()).strip()
        normalized = re.sub(r"\s+", " ", normalized)
        stopwords = {"company", "co", "corp", "corporation", "inc", "llc", "ltd", "limited", "the"}
        tokens = [t for t in normalized.split(" ") if t and t not in stopwords]
        return " ".join(tokens)

    def _org_name_similarity(self, a: str, b: str) -> float:
        """Token-set similarity for organization names (0~1)."""
        a_tokens = set(self._org_name_semantic_key(a).split())
        b_tokens = set(self._org_name_semantic_key(b).split())
        if not a_tokens or not b_tokens:
            return 0.0
        inter = len(a_tokens & b_tokens)
        union = len(a_tokens | b_tokens)
        return inter / union if union else 0.0

    def _role_code_from_name(self, name: str) -> str:
        """Generate a normalized role code from role name."""
        raw = re.sub(r"[^A-Za-z0-9]+", "_", (name or "").strip().upper()).strip("_")
        return raw or "ROLE"

    def _build_unique_role_code(self, base_code: str, org_id: int, existing_codes: set) -> str:
        """
        Build unique role code under global-unique constraints.
        Tries BASE -> BASE_{org_id} -> BASE_{org_id}_{n}.
        """
        def shrink(code: str) -> str:
            return code[:64]

        normalized_base = shrink(re.sub(r"[^A-Za-z0-9_]+", "_", (base_code or "ROLE").upper()).strip("_") or "ROLE")
        if normalized_base not in existing_codes:
            return normalized_base

        by_org = shrink(f"{normalized_base}_{org_id}")
        if by_org not in existing_codes:
            return by_org

        for i in range(2, 1000):
            candidate = shrink(f"{normalized_base}_{org_id}_{i}")
            if candidate not in existing_codes:
                return candidate

        # Last resort: timestamp suffix
        suffix = datetime.utcnow().strftime("%H%M%S")
        return shrink(f"{normalized_base}_{org_id}_{suffix}")

    def _get_headers(self) -> Dict[str, str]:
        """Get HTTP headers with tenant and auth information."""
        headers = {"Content-Type": "application/json"}

        if self.tenant_id:
            headers["X-Tenant-ID"] = str(self.tenant_id)

        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        return headers

    async def _resolve_audit_auth_token(self, tenant_id: int, user_token: Optional[str]) -> Optional[str]:
        """Resolve a long-lived system token for audit submission, falling back to the user token."""
        cached = self._audit_system_tokens.get(tenant_id)
        if cached and not self.http_client._is_token_expired(cached):
            return cached

        source_token = user_token or self.auth_token
        if not source_token:
            return None

        if self.http_client._is_token_expired(source_token):
            logger.warning("Audit source token already expired before system token exchange; skipping audit submit")
            return None

        try:
            exchange_url = urljoin(self.base_url, f"/v2/auth/system-token?tenantId={tenant_id}")
            response = await self.http_client.client.post(
                exchange_url,
                headers={
                    "Authorization": f"Bearer {source_token}",
                    "X-Tenant-ID": str(tenant_id),
                    "Content-Type": "application/json"
                },
                timeout=10,
            )
            if response.status_code == 200:
                data = response.json()
                system_token = data.get("access_token")
                if system_token:
                    self._audit_system_tokens[tenant_id] = system_token
                    return system_token
                logger.warning("System token exchange succeeded but access_token was missing")
            else:
                logger.warning(
                    "System token exchange failed for audit submission: status=%s body=%s",
                    response.status_code,
                    response.text,
                )
        except Exception as exc:
            logger.warning("System token exchange failed for audit submission: %s", exc)

        return source_token

    async def submit_audit_event(
        self,
        category: str,
        action: str,
        tenant_id: int,
        actor: Dict[str, Any],
        target: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        occurred_at: Optional[str] = None,
        auth_token: Optional[str] = None
    ) -> ToolResult:
        """Submit a single audit event."""
        try:
            # Build event payload according to new API spec
            payload = {
                "category": category.upper(),
                "action": action,
                "tenantId": tenant_id,
                "actor": actor
            }

            if target:
                payload["target"] = target
            if metadata:
                payload["metadata"] = metadata
            if occurred_at:
                payload["occurredAt"] = occurred_at

            params = {
                "body": payload
            }

            audit_auth_token = await self._resolve_audit_auth_token(tenant_id, auth_token)
            if not audit_auth_token:
                logger.warning("Skipping audit event submit because no valid audit auth token is available")
                return ToolResult.success(
                    content=f"Audit event skipped (no valid auth token): {action}",
                    data={"skipped": True, "reason": "NO_VALID_AUDIT_TOKEN"}
                )
            response = await self.http_client.execute(
                command="POST /v2/audit/events",
                params=params,
                auth_token=audit_auth_token,
                tenant_id=tenant_id
            )

            return ToolResult.success(
                content=f"Audit event accepted: {action}",
                data=response
            )
        except Exception as e:
            logger.error(f"Error submitting audit event: {e}")
            return ToolResult.error(
                content=f"Failed to submit audit event: {str(e)}",
                error_code="AUDIT_SUBMIT_FAILED"
            )

    async def submit_audit_events_batch(
        self,
        events: list,
        auth_token: Optional[str] = None
    ) -> ToolResult:
        """Submit multiple audit events."""
        try:
            # Build batch payload
            payload = {
                "events": events
            }

            params = {
                "body": payload
            }

            # Use tenant_id from first event
            first_event_tenant = events[0].get("tenant_id") if events else self.tenant_id

            audit_auth_token = await self._resolve_audit_auth_token(first_event_tenant, auth_token)
            if not audit_auth_token:
                logger.warning("Skipping audit events batch submit because no valid audit auth token is available")
                return ToolResult.success(
                    content="Audit events batch skipped (no valid auth token)",
                    data={"skipped": True, "reason": "NO_VALID_AUDIT_TOKEN", "count": len(events)}
                )
            response = await self.http_client.execute(
                command="POST /v2/audit/events/batch",
                params=params,
                auth_token=audit_auth_token,
                tenant_id=first_event_tenant
            )

            count = len(events)
            return ToolResult.success(
                content=f"Submitted {count} audit events",
                data=response
            )
        except Exception as e:
            logger.error(f"Error submitting audit events batch: {e}")
            return ToolResult.error(
                content=f"Failed to submit audit events: {str(e)}",
                error_code="AUDIT_BATCH_SUBMIT_FAILED"
            )
