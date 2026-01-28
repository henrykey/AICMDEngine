"""
Membership API MCP Server implementation.

This MCP server exposes Membership API commands as tools.
"""

from typing import Optional, Dict, Any
import logging
import os
from datetime import datetime

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
        self.http_client = HTTPClient(base_url=self.base_url)
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
                        "description": "Type of organization unit"
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
                    "auth_token": {
                        "type": "string",
                        "description": "Authentication token (optional, will use default if not provided)"
                    },
                    "tenant_id": {
                        "type": "integer",
                        "description": "Tenant ID (optional, will use default if not provided)"
                    }
                },
                "required": ["name", "type"]
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
                        "default": "descendants"
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

            if not effective_tenant:
                logger.error("list_members called without tenant_id")
                return ToolResult.error(
                    content="Tenant ID required. Please provide tenant_id parameter.",
                    error_code="TENANT_REQUIRED"
                )

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

            roles = response.get("roles", [])
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
        direction: str = "descendants",
        max_depth: int = 5,
        auth_token: Optional[str] = None,
        tenant_id: Optional[int] = None
    ) -> ToolResult:
        """Get organization hierarchy (ancestors/descendants)."""
        try:
            # Validate parameters
            if direction not in ["ancestors", "descendants", "both"]:
                direction = "descendants"
            if max_depth < 1 or max_depth > 10:
                max_depth = 5

            params = {
                "path": {
                    "org_id": org_id
                },
                "query": {
                    "direction": direction,
                    "max_depth": max_depth
                }
            }
            response = await self.http_client.execute(
                command="GET /v2/orgs/{org_id}/hierarchy",
                params=params,
                auth_token=auth_token or self.auth_token,
                tenant_id=tenant_id or self.tenant_id
            )

            # Format hierarchical data for readability
            summary_lines = [f"Organization Hierarchy for ID {org_id}:"]
            
            # Process ancestors if present
            ancestors = response.get("ancestors", [])
            if ancestors:
                summary_lines.append(f"\n👤 Parent Organizations ({len(ancestors)}):")
                for ancestor in ancestors:
                    name = ancestor.get("name", ancestor.get("id", "Unknown"))
                    org_type = ancestor.get("type", "")
                    summary_lines.append(f"  • {name} ({org_type})")
            
            # Process descendants if present
            descendants = response.get("descendants", [])
            if descendants:
                summary_lines.append(f"\n👥 Child Organizations ({len(descendants)}):")
                for descendant in descendants:
                    name = descendant.get("name", descendant.get("id", "Unknown"))
                    org_type = descendant.get("type", "")
                    summary_lines.append(f"  • {name} ({org_type})")
            
            if not ancestors and not descendants:
                summary_lines.append("\nNo hierarchical relationships found.")

            content = "\n".join(summary_lines)
            return ToolResult.success(
                content=content,
                data=response
            )
        except Exception as e:
            logger.error(f"Error getting organization hierarchy for {org_id}: {e}")
            return ToolResult.error(
                content=f"Failed to get organization hierarchy: {str(e)}",
                error_code="GET_ORG_HIERARCHY_FAILED"
            )

    async def create_org(
        self,
        name: str,
        type: str,
        description: Optional[str] = None,
        is_temporary: bool = False,
        valid_until: Optional[str] = None,
        auth_token: Optional[str] = None,
        tenant_id: Optional[int] = None
    ) -> ToolResult:
        """Create a new organization unit."""
        try:
            payload = {
                "name": name,
                "type": type,
                "isTemporary": is_temporary
            }
            if description:
                payload["description"] = description
            if valid_until:
                payload["validUntil"] = valid_until

            params = {
                "body": payload
            }
            response = await self.http_client.execute(
                command="POST /v2/orgs",
                params=params,
                auth_token=auth_token or self.auth_token,
                tenant_id=tenant_id or self.tenant_id
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

    def _get_headers(self) -> Dict[str, str]:
        """Get HTTP headers with tenant and auth information."""
        headers = {"Content-Type": "application/json"}

        if self.tenant_id:
            headers["X-Tenant-ID"] = str(self.tenant_id)

        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        return headers
