"""
Membership API MCP Server implementation.

This MCP server exposes Membership API commands as tools.
"""

from typing import Optional, Dict, Any, List
import logging
import os
import re
import json
from datetime import datetime
from urllib.parse import urljoin

from ..mcp import BaseMCPServer, Tool, ToolResult
from ..services.http_client import HTTPClient
from ..core.config import settings
from ..services.llm_client import llm_client

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
            semantic_description="获取成员列表，可用于查找成员、定位 member_id，或作为后续成员详情和权限查询的候选集来源。",
            use_cases=[
                "查找成员",
                "显示成员详情前先定位成员",
                "查询成员权限前先获取成员候选集",
            ],
            natural_language_examples=[
                "admin 是哪个成员？",
                "显示用户 admin 的详细信息",
                "王维宏有哪些访问权？",
            ],
            output_description="返回成员对象数组，常见字段包括 id、username、fullName、email、status。",
            tags=["membership", "member", "lookup", "list", "task_tool"],
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
            description="Get details of a specific member by member ID or by query such as username, full name, or email",
            semantic_description="获取成员详细信息。支持直接给 member_id，也支持根据用户名、姓名、邮箱等线索先自动解析成员再查详情。",
            use_cases=[
                "显示成员详细信息",
                "根据用户名查看成员档案",
            ],
            natural_language_examples=[
                "显示用户 admin 的详细信息",
                "查看 kehongwei 的成员信息",
            ],
            output_description="返回成员详细信息，并包含 resolved_member_id、resolved_member 等解析结果。",
            tags=["membership", "member", "profile", "lookup", "task_tool"],
            input_schema={
                "type": "object",
                "properties": {
                    "member_id": {
                        "type": "string",
                        "description": "Member ID"
                    },
                    "query": {
                        "type": "string",
                        "description": "Member lookup text such as username, full name, or email"
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
            handler=self.get_member
        ))

        # Resolve member ID tool
        self.register_tool(Tool(
            name="get_member_id",
            description="Resolve a member ID from member details such as username, full name, email, nickname, or alias",
            semantic_description="根据用户名、姓名、邮箱、昵称等线索解析唯一成员 ID。可直接接收完整成员数组，也可内部自动查询成员列表。",
            use_cases=[
                "根据自然语言线索获取成员 ID",
                "为成员详情、权限、组织查询提供 member_id",
            ],
            natural_language_examples=[
                "admin 的成员 ID 是多少？",
                "王维宏对应的成员是谁？",
            ],
            output_description="返回 status、member_id、matched_member、candidates，用于后续步骤继续执行。",
            tags=["membership", "member", "id_resolution", "lookup", "task_tool"],
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The username, full name, email, nickname, or other identifying text to match"
                    },
                    "members": {
                        "type": "array",
                        "description": "Optional full member objects from a previous list_members step"
                    },
                    "match_fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional fields to match against. Defaults to username/fullName/email/nickname/alias/name"
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
                "required": ["query"]
            },
            handler=self.get_member_id
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
            semantic_description="获取角色列表，可用于按角色名称、编码定位角色，也可作为后续角色权限查询和成员赋角色的候选集来源。",
            use_cases=[
                "查找角色",
                "给成员赋角色前先定位角色",
                "查看角色权限前先获取角色候选集",
            ],
            natural_language_examples=[
                "管理员角色对应哪个 role？",
                "显示 System Administrator 角色的权限",
            ],
            output_description="返回角色对象数组，常见字段包括 id、name、code、org_id、description。",
            tags=["membership", "role", "lookup", "list", "task_tool"],
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
                    "search": {
                        "type": "string",
                        "description": "Optional role search query"
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

        self.register_tool(Tool(
            name="lookup_role",
            description="Resolve a role ID from role details such as name, code, or description",
            semantic_description="根据角色名称、编码或描述解析唯一角色 ID。可直接接收完整角色数组，也可内部自动查询角色列表。",
            use_cases=[
                "根据自然语言线索获取角色 ID",
                "为角色权限查询和成员赋角色提供 role_id",
            ],
            natural_language_examples=[
                "System Administrator 的角色 ID 是多少？",
                "管理员角色对应哪个 role？",
            ],
            output_description="返回 status、role_id、matched_role、candidates，用于后续步骤继续执行。",
            tags=["membership", "role", "id_resolution", "lookup", "task_tool"],
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The role name, code, or descriptive text to match"
                    },
                    "roles": {
                        "type": "array",
                        "description": "Optional full role objects from a previous list_roles step"
                    },
                    "match_fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional fields to match against. Defaults to name/code/description"
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
                "required": ["query"]
            },
            handler=self.lookup_role
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
            description="Assign a role to a member by IDs or by member/role query",
            semantic_description="让成员具备某个角色。支持直接传 member_id/role_id，也支持按成员名称和角色名称自动解析后完成赋权。",
            use_cases=[
                "给成员赋角色",
                "根据自然语言指定成员和角色完成关联",
            ],
            natural_language_examples=[
                "给 kehongwei 赋予管理员角色",
                "让 admin 具有 System Administrator 角色",
            ],
            output_description="返回 member_id、role_id、resolved_member、resolved_role 以及赋权结果。",
            tags=["membership", "member", "role", "assignment", "task_tool"],
            input_schema={
                "type": "object",
                "properties": {
                    "member_id": {
                        "type": "string",
                        "description": "Member ID"
                    },
                    "member_query": {
                        "type": "string",
                        "description": "Member lookup text such as username, full name, or email"
                    },
                    "role_id": {
                        "type": "string",
                        "description": "Role ID"
                    },
                    "role_query": {
                        "type": "string",
                        "description": "Role lookup text such as role name or code"
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
            handler=self.assign_role
        ))

        # List organizations tool
        self.register_tool(Tool(
            name="list_orgs",
            description="List all organization units",
            semantic_description="获取组织列表，可用于按名称或编码定位组织，也可作为创建下级组织、成员入组织等任务的候选集来源。",
            use_cases=[
                "查找组织",
                "在创建或关联前定位组织",
            ],
            natural_language_examples=[
                "研发部对应哪个组织？",
                "把某成员加入工程部之前先找工程部",
            ],
            output_description="返回组织对象数组，常见字段包括 id、name、code、type、parentId。",
            tags=["membership", "org", "lookup", "list", "task_tool"],
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
                        "description": "Optional organization search query"
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
            description="Get details of a specific organization unit by organization ID or by query such as name or code",
            semantic_description="获取组织详细信息。支持直接给 org_id，也支持根据组织名称或编码先自动解析组织再查详情。",
            use_cases=[
                "显示组织详细信息",
                "根据组织名称查看组织档案",
            ],
            natural_language_examples=[
                "显示研发部的详细信息",
                "查看 Engineering 组织信息",
            ],
            output_description="返回组织详细信息，并包含 resolved_org_id、resolved_org 等解析结果。",
            tags=["membership", "org", "profile", "lookup", "task_tool"],
            input_schema={
                "type": "object",
                "properties": {
                    "org_id": {
                        "type": "string",
                        "description": "Organization unit ID"
                    },
                    "query": {
                        "type": "string",
                        "description": "Organization lookup text such as name or code"
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

        self.register_tool(Tool(
            name="lookup_resource",
            description="Resolve a resource ID from resource details such as name or system code",
            semantic_description="根据资源名称、系统代码、描述或类型解析唯一资源 ID。可直接接收完整资源数组，也可内部自动查询资源列表。",
            use_cases=[
                "根据自然语言线索获取资源 ID",
                "为授权、权限检查和资源详情查询提供 resource_id",
            ],
            natural_language_examples=[
                "HOST_LOGIN 这个资源的 ID 是多少？",
                "查找系统 APP 的主机登录资源",
            ],
            output_description="返回 status、resource_id、matched_resource、candidates，用于后续步骤继续执行。",
            tags=["membership", "resource", "id_resolution", "lookup", "task_tool"],
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The resource name, system code, description, or type text to match"
                    },
                    "resources": {
                        "type": "array",
                        "description": "Optional full resource objects from a previous list query"
                    },
                    "system_code": {
                        "type": "string",
                        "description": "Optional system code filter when loading resources from API"
                    },
                    "resource_type": {
                        "type": "string",
                        "description": "Optional resource type filter when loading resources from API"
                    },
                    "match_fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional fields to match against. Defaults to name/system_code/description/type"
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
                "required": ["query"]
            },
            handler=self.lookup_resource
        ))

        self.register_tool(Tool(
            name="get_subject_permissions",
            description="Get permissions directly assigned to a subject such as a member or role",
            semantic_description="获取主体自身被授予的权限。member 返回 direct permissions，role 返回 role 自身权限；org 由于公开 API 缺失会返回限制说明。",
            use_cases=[
                "查看成员自身直接权限",
                "查看角色自身权限",
                "为成员有效权限汇总提供基础权限来源",
            ],
            natural_language_examples=[
                "admin 自身有哪些直接权限？",
                "System Administrator 角色有什么权限？",
            ],
            output_description="返回 subject_type、subject_id、permissions，以及可选 limitations。",
            tags=["membership", "permission", "subject", "task_tool"],
            input_schema={
                "type": "object",
                "properties": {
                    "subject_type": {
                        "type": "string",
                        "enum": ["member", "role", "org"],
                        "description": "Subject type to inspect"
                    },
                    "subject_id": {
                        "type": "string",
                        "description": "Direct subject ID"
                    },
                    "query": {
                        "type": "string",
                        "description": "Lookup text for the subject when subject_id is not provided"
                    },
                    "org_id": {
                        "type": "integer",
                        "description": "Optional org scope when querying member permissions"
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
                "required": ["subject_type"]
            },
            handler=self.get_subject_permissions
        ))

        self.register_tool(Tool(
            name="get_member_effective_permissions",
            description="Get a member's effective permissions by combining direct member permissions, role permissions, and organizational context",
            semantic_description="汇总成员的有效权限。会解析 member、自身直接权限、角色权限、所属组织和上级组织上下文；若 org 权限公开 API 不可用，会明确返回限制说明而不伪造结果。",
            use_cases=[
                "查看成员有哪些访问权",
                "分析成员为什么能访问某个资源",
            ],
            natural_language_examples=[
                "王维宏有哪些访问权？",
                "admin 的有效权限是什么？",
            ],
            output_description="返回 member、direct_permissions、role_permissions、effective_permissions、member_roles、member_orgs、ancestor_orgs，以及 limitations。",
            tags=["membership", "member", "permission", "effective_permission", "task_tool"],
            input_schema={
                "type": "object",
                "properties": {
                    "member_id": {
                        "type": "string",
                        "description": "Member ID"
                    },
                    "query": {
                        "type": "string",
                        "description": "Member lookup text such as username, full name, or email"
                    },
                    "org_id": {
                        "type": "integer",
                        "description": "Optional org scope for member permission API"
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
            handler=self.get_member_effective_permissions
        ))

        self.register_tool(Tool(
            name="create_resource",
            description="Create a new resource",
            semantic_description="创建资源，用于后续权限点和访问控制。适合先创建 application/system 下的 function 或 data 资源。",
            use_cases=[
                "创建应用资源",
                "为授权准备新的资源对象",
            ],
            natural_language_examples=[
                "创建 APP 系统下的 HOST_LOGIN 资源",
                "新增一个 data 类型资源",
            ],
            output_description="返回创建后的资源对象，常见字段包括 id、system_code、name、type、access_mode。",
            tags=["membership", "resource", "create", "task_tool"],
            input_schema={
                "type": "object",
                "properties": {
                    "system_code": {
                        "type": "string",
                        "description": "System code for the resource"
                    },
                    "name": {
                        "type": "string",
                        "description": "Resource name"
                    },
                    "type": {
                        "type": "string",
                        "enum": ["function", "data"],
                        "description": "Resource type"
                    },
                    "description": {
                        "type": "string",
                        "description": "Resource description (optional)"
                    },
                    "access_mode": {
                        "type": "string",
                        "enum": ["whitelist", "blacklist"],
                        "description": "Access mode",
                        "default": "whitelist"
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
                "required": ["system_code", "name", "type"]
            },
            handler=self.create_resource
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

            members = response.get("data", response.get("members", []))
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

    def _normalize_member_lookup_value(self, value: Any) -> str:
        return str(value or "").strip().casefold()

    def _normalize_lookup_value(self, value: Any) -> str:
        return str(value or "").strip().casefold()

    def _resolve_member_matches(
        self,
        members: List[Dict[str, Any]],
        query: str,
        match_fields: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        normalized_query = self._normalize_member_lookup_value(query)
        fields = match_fields or ["username", "fullName", "email", "nickname", "alias", "name"]

        exact_matches = [
            member
            for member in members
            if any(self._normalize_member_lookup_value(member.get(field)) == normalized_query for field in fields)
        ]
        if exact_matches:
            return exact_matches

        contains_matches = [
            member
            for member in members
            if any(
                normalized_query and normalized_query in self._normalize_member_lookup_value(member.get(field))
                for field in fields
            )
        ]
        return contains_matches

    def _resolve_generic_matches(
        self,
        items: List[Dict[str, Any]],
        query: str,
        match_fields: List[str],
    ) -> List[Dict[str, Any]]:
        normalized_query = self._normalize_lookup_value(query)
        exact_matches = [
            item
            for item in items
            if any(self._normalize_lookup_value(item.get(field)) == normalized_query for field in match_fields)
        ]
        if exact_matches:
            return exact_matches

        contains_matches = [
            item
            for item in items
            if any(
                normalized_query and normalized_query in self._normalize_lookup_value(item.get(field))
                for field in match_fields
            )
        ]
        return contains_matches

    async def _resolve_role_id(
        self,
        role_id: Optional[str],
        role_query: Optional[str],
        auth_token: Optional[str],
        tenant_id: Optional[int],
    ) -> tuple[str, Optional[Dict[str, Any]]]:
        if role_id:
            return str(role_id), None
        if not role_query:
            raise ValueError("Either role_id or role_query is required")

        response = await self.http_client.execute(
            command="GET /v2/roles",
            params={"query": {"page": 1, "limit": 100, "search": role_query}},
            auth_token=auth_token or self.auth_token,
            tenant_id=tenant_id or self.tenant_id,
        )
        roles = response.get("data", response.get("roles", []))
        candidates = [item for item in roles if isinstance(item, dict)]
        matches = self._resolve_generic_matches(candidates, role_query, ["name", "code", "description"])
        if len(matches) == 1:
            role = matches[0]
            resolved_role_id = role.get("id")
            if resolved_role_id is None:
                raise ValueError(f"Resolved role '{role_query}' but no id was returned")
            return str(resolved_role_id), role
        if not matches:
            raise ValueError(f"No role matched query '{role_query}'")
        raise ValueError(f"Multiple roles matched query '{role_query}'")

    async def _resolve_resource_id(
        self,
        resource_id: Optional[str],
        query: Optional[str],
        auth_token: Optional[str],
        tenant_id: Optional[int],
        system_code: Optional[str] = None,
        resource_type: Optional[str] = None,
    ) -> tuple[str, Optional[Dict[str, Any]]]:
        if resource_id:
            return str(resource_id), None
        if not query:
            raise ValueError("Either resource_id or query is required")

        params: Dict[str, Any] = {"query": {"page": 1, "page_size": 100}}
        if system_code:
            params["query"]["system_code"] = system_code
        if resource_type:
            params["query"]["type"] = resource_type

        response = await self.http_client.execute(
            command="GET /v2/resources",
            params=params,
            auth_token=auth_token or self.auth_token,
            tenant_id=tenant_id or self.tenant_id,
        )
        resources = response.get("data", response.get("resources", []))
        candidates = [item for item in resources if isinstance(item, dict)]
        matches = self._resolve_generic_matches(candidates, query, ["name", "system_code", "description", "type"])
        if len(matches) == 1:
            resource = matches[0]
            resolved_resource_id = resource.get("id")
            if resolved_resource_id is None:
                raise ValueError(f"Resolved resource '{query}' but no id was returned")
            return str(resolved_resource_id), resource
        if not matches:
            raise ValueError(f"No resource matched query '{query}'")
        raise ValueError(f"Multiple resources matched query '{query}'")

    async def _resolve_org_id(
        self,
        org_id: Optional[str],
        query: Optional[str],
        auth_token: Optional[str],
        tenant_id: Optional[int],
    ) -> tuple[str, Optional[Dict[str, Any]]]:
        if org_id:
            return str(org_id), None
        if not query:
            raise ValueError("Either org_id or query is required")

        response = await self.http_client.execute(
            command="GET /v2/orgs",
            params={"query": {"page": 1, "limit": 100, "search": query}},
            auth_token=auth_token or self.auth_token,
            tenant_id=tenant_id or self.tenant_id,
        )
        orgs = response.get("data", response.get("orgs", []))
        candidates = [item for item in orgs if isinstance(item, dict)]
        matches = self._resolve_generic_matches(candidates, query, ["name", "code", "type"])
        if len(matches) == 1:
            org = matches[0]
            resolved_org_id = org.get("id")
            if resolved_org_id is None:
                raise ValueError(f"Resolved organization '{query}' but no id was returned")
            return str(resolved_org_id), org
        if not matches:
            raise ValueError(f"No organization matched query '{query}'")
        raise ValueError(f"Multiple organizations matched query '{query}'")

    async def _resolve_member_with_llm(
        self,
        members: List[Dict[str, Any]],
        query: str,
        match_fields: List[str],
    ) -> Optional[Dict[str, Any]]:
        messages = [
            {
                "role": "system",
                "content": (
                    "You are given a list of member objects. "
                    "Identify the single best match for the requested member query. "
                    "Return only JSON with keys status, member_id, username, fullName, reason. "
                    "Allowed status values: unique, not_found, multiple. "
                    "Only return unique if the evidence is strong."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Query: {query}\n"
                    f"Match fields: {json.dumps(match_fields, ensure_ascii=False)}\n"
                    f"Members:\n{json.dumps(members, ensure_ascii=False, indent=2)}"
                ),
            },
        ]

        try:
            raw = await llm_client.generate_response(
                messages=messages,
                temperature=0.0,
                response_format={"type": "json_object"},
                max_tokens=600,
            )
            parsed = json.loads(raw)
            if parsed.get("status") != "unique":
                return None
            member_id = parsed.get("member_id")
            if member_id is None:
                return None
            normalized_member_id = str(member_id)
            for member in members:
                if str(member.get("id")) == normalized_member_id:
                    return {
                        "member_id": member.get("id"),
                        "matched_member": member,
                        "reason": parsed.get("reason", "matched via llm"),
                        "match_method": "llm",
                    }
        except Exception as exc:
            logger.warning("LLM member resolution fallback failed: %s", exc)
        return None

    async def get_member_id(
        self,
        query: str,
        members: Optional[List[Dict[str, Any]]] = None,
        match_fields: Optional[List[str]] = None,
        auth_token: Optional[str] = None,
        tenant_id: Optional[int] = None,
    ) -> ToolResult:
        """Resolve a member ID from full member details or by querying the membership service."""
        try:
            if not query or not str(query).strip():
                return ToolResult.error(
                    content="Member query cannot be empty",
                    error_code="INVALID_MEMBER_QUERY",
                )

            effective_token = auth_token or self.auth_token
            effective_tenant = tenant_id or self.tenant_id or 1
            fields = match_fields or ["username", "fullName", "email", "nickname", "alias", "name"]

            candidate_members = members
            if not candidate_members:
                if not effective_token:
                    return ToolResult.error(
                        content="Authentication required to fetch members for member ID resolution.",
                        error_code="AUTH_REQUIRED",
                    )
                response = await self.http_client.execute(
                    command="GET /v2/members",
                    params={"query": {"page": 1, "limit": 100}},
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                candidate_members = response.get("data", [])

            candidate_members = [item for item in (candidate_members or []) if isinstance(item, dict)]
            matches = self._resolve_member_matches(candidate_members, query, fields)

            if len(matches) == 1:
                member = matches[0]
                result = {
                    "status": "unique",
                    "query": query,
                    "member_id": member.get("id"),
                    "matched_member": member,
                    "reason": "matched using exact member fields",
                    "match_method": "deterministic",
                }
                return ToolResult.success(
                    content=f"Resolved member '{query}' to ID {member.get('id')}",
                    data=result,
                )

            if not matches and candidate_members:
                llm_result = await self._resolve_member_with_llm(candidate_members, query, fields)
                if llm_result:
                    llm_result["status"] = "unique"
                    llm_result["query"] = query
                    return ToolResult.success(
                        content=f"Resolved member '{query}' to ID {llm_result['member_id']}",
                        data=llm_result,
                    )

            if not matches:
                return ToolResult.error(
                    content=f"No member matched query '{query}'",
                    error_code="MEMBER_NOT_FOUND",
                    data={
                        "status": "not_found",
                        "query": query,
                    },
                )

            return ToolResult.error(
                content=f"Multiple members matched query '{query}'",
                error_code="MULTIPLE_MEMBER_MATCHES",
                data={
                    "status": "multiple",
                    "query": query,
                    "candidates": matches[:10],
                },
            )
        except Exception as e:
            logger.error(f"Error resolving member ID for query '{query}': {e}")
            return ToolResult.error(
                content=f"Failed to resolve member ID: {str(e)}",
                error_code="GET_MEMBER_ID_FAILED",
            )

    async def get_member(
        self,
        member_id: Optional[str] = None,
        query: Optional[str] = None,
        auth_token: Optional[str] = None,
        tenant_id: Optional[int] = None,
    ) -> ToolResult:
        """Get member details."""
        try:
            effective_token = auth_token or self.auth_token
            effective_tenant = tenant_id or self.tenant_id
            resolved_member_id = member_id
            resolved_member = None

            if not resolved_member_id:
                if not query:
                    return ToolResult.error(
                        content="Either member_id or query is required",
                        error_code="INVALID_MEMBER_LOOKUP",
                    )
                member_lookup = await self.get_member_id(
                    query=query,
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                if member_lookup.is_error:
                    return member_lookup
                resolved_member_id = str(member_lookup.data.get("member_id"))
                resolved_member = member_lookup.data.get("matched_member")

            params = {
                "path": {
                    "member_id": resolved_member_id
                }
            }
            response = await self.http_client.execute(
                command="GET /v2/members/{member_id}",
                params=params,
                auth_token=effective_token,
                tenant_id=effective_tenant
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
                data={
                    **(response if isinstance(response, dict) else {"member": member}),
                    "resolved_member_id": resolved_member_id,
                    "resolved_member": resolved_member or member,
                }
            )
        except Exception as e:
            logger.error(f"Error getting member {member_id or query}: {e}")
            return ToolResult.error(
                content=f"Failed to get member: {str(e)}",
                error_code="GET_MEMBER_FAILED"
            )

    async def lookup_role(
        self,
        query: str,
        roles: Optional[List[Dict[str, Any]]] = None,
        match_fields: Optional[List[str]] = None,
        auth_token: Optional[str] = None,
        tenant_id: Optional[int] = None,
    ) -> ToolResult:
        """Resolve a role ID from role details or by querying the membership service."""
        try:
            if not query or not str(query).strip():
                return ToolResult.error(
                    content="Role query cannot be empty",
                    error_code="INVALID_ROLE_QUERY",
                )

            effective_token = auth_token or self.auth_token
            effective_tenant = tenant_id or self.tenant_id or 1
            fields = match_fields or ["name", "code", "description"]

            candidate_roles = roles
            if not candidate_roles:
                if not effective_token:
                    return ToolResult.error(
                        content="Authentication required to fetch roles for role ID resolution.",
                        error_code="AUTH_REQUIRED",
                    )
                response = await self.http_client.execute(
                    command="GET /v2/roles",
                    params={"query": {"page": 1, "limit": 100, "search": query}},
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                candidate_roles = response.get("data", response.get("roles", []))

            candidate_roles = [item for item in (candidate_roles or []) if isinstance(item, dict)]
            matches = self._resolve_generic_matches(candidate_roles, query, fields)

            if len(matches) == 1:
                role = matches[0]
                result = {
                    "status": "unique",
                    "query": query,
                    "role_id": role.get("id"),
                    "matched_role": role,
                    "reason": "matched using exact role fields",
                    "match_method": "deterministic",
                }
                return ToolResult.success(
                    content=f"Resolved role '{query}' to ID {role.get('id')}",
                    data=result,
                )

            if not matches:
                return ToolResult.error(
                    content=f"No role matched query '{query}'",
                    error_code="ROLE_NOT_FOUND",
                    data={"status": "not_found", "query": query},
                )

            return ToolResult.error(
                content=f"Multiple roles matched query '{query}'",
                error_code="MULTIPLE_ROLE_MATCHES",
                data={"status": "multiple", "query": query, "candidates": matches[:10]},
            )
        except Exception as e:
            logger.error(f"Error resolving role ID for query '{query}': {e}")
            return ToolResult.error(
                content=f"Failed to resolve role ID: {str(e)}",
                error_code="LOOKUP_ROLE_FAILED",
            )

    async def lookup_resource(
        self,
        query: str,
        resources: Optional[List[Dict[str, Any]]] = None,
        system_code: Optional[str] = None,
        resource_type: Optional[str] = None,
        match_fields: Optional[List[str]] = None,
        auth_token: Optional[str] = None,
        tenant_id: Optional[int] = None,
    ) -> ToolResult:
        """Resolve a resource ID from resource details or by querying the membership service."""
        try:
            if not query or not str(query).strip():
                return ToolResult.error(
                    content="Resource query cannot be empty",
                    error_code="INVALID_RESOURCE_QUERY",
                )

            effective_token = auth_token or self.auth_token
            effective_tenant = tenant_id or self.tenant_id or 1
            fields = match_fields or ["name", "system_code", "description", "type"]

            candidate_resources = resources
            if not candidate_resources:
                if not effective_token:
                    return ToolResult.error(
                        content="Authentication required to fetch resources for resource ID resolution.",
                        error_code="AUTH_REQUIRED",
                    )
                params: Dict[str, Any] = {"query": {"page": 1, "page_size": 100}}
                if system_code:
                    params["query"]["system_code"] = system_code
                if resource_type:
                    params["query"]["type"] = resource_type
                response = await self.http_client.execute(
                    command="GET /v2/resources",
                    params=params,
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                candidate_resources = response.get("data", response.get("resources", []))

            candidate_resources = [item for item in (candidate_resources or []) if isinstance(item, dict)]
            matches = self._resolve_generic_matches(candidate_resources, query, fields)

            if len(matches) == 1:
                resource = matches[0]
                result = {
                    "status": "unique",
                    "query": query,
                    "resource_id": resource.get("id"),
                    "matched_resource": resource,
                    "reason": "matched using exact resource fields",
                    "match_method": "deterministic",
                }
                return ToolResult.success(
                    content=f"Resolved resource '{query}' to ID {resource.get('id')}",
                    data=result,
                )

            if not matches:
                return ToolResult.error(
                    content=f"No resource matched query '{query}'",
                    error_code="RESOURCE_NOT_FOUND",
                    data={"status": "not_found", "query": query},
                )

            return ToolResult.error(
                content=f"Multiple resources matched query '{query}'",
                error_code="MULTIPLE_RESOURCE_MATCHES",
                data={"status": "multiple", "query": query, "candidates": matches[:10]},
            )
        except Exception as e:
            logger.error(f"Error resolving resource ID for query '{query}': {e}")
            return ToolResult.error(
                content=f"Failed to resolve resource ID: {str(e)}",
                error_code="LOOKUP_RESOURCE_FAILED",
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
                    "newPassword": password
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

    async def list_roles(
        self,
        page: int = 1,
        limit: int = 10,
        search: Optional[str] = None,
        auth_token: Optional[str] = None,
        tenant_id: Optional[int] = None,
    ) -> ToolResult:
        """List available roles."""
        try:
            params = {
                "query": {
                    "page": max(1, page),
                    "limit": max(1, min(100, limit))
                }
            }
            if search:
                params["query"]["search"] = search
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

    async def assign_role(
        self,
        member_id: Optional[str] = None,
        role_id: Optional[str] = None,
        member_query: Optional[str] = None,
        role_query: Optional[str] = None,
        auth_token: Optional[str] = None,
        tenant_id: Optional[int] = None,
    ) -> ToolResult:
        """Assign a role to a member."""
        try:
            effective_token = auth_token or self.auth_token
            effective_tenant = tenant_id or self.tenant_id

            resolved_member_id = member_id
            resolved_member = None
            if not resolved_member_id:
                if not member_query:
                    return ToolResult.error(
                        content="Either member_id or member_query is required",
                        error_code="INVALID_MEMBER_LOOKUP",
                    )
                member_lookup = await self.get_member_id(
                    query=member_query,
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                if member_lookup.is_error:
                    return member_lookup
                resolved_member_id = str(member_lookup.data.get("member_id"))
                resolved_member = member_lookup.data.get("matched_member")

            resolved_role_id, resolved_role = await self._resolve_role_id(
                role_id=role_id,
                role_query=role_query,
                auth_token=effective_token,
                tenant_id=effective_tenant,
            )

            payload = {"role_id": resolved_role_id}
            params = {
                "path": {
                    "member_id": resolved_member_id
                },
                "body": payload
            }
            response = await self.http_client.execute(
                command="POST /v2/members/{member_id}/roles",
                params=params,
                auth_token=effective_token,
                tenant_id=effective_tenant
            )

            return ToolResult.success(
                content=f"Assigned role {resolved_role_id} to member {resolved_member_id}",
                data={
                    **(response if isinstance(response, dict) else {"result": response}),
                    "member_id": resolved_member_id,
                    "role_id": resolved_role_id,
                    "resolved_member": resolved_member,
                    "resolved_role": resolved_role,
                }
            )
        except Exception as e:
            logger.error(f"Error assigning role: {e}")
            return ToolResult.error(
                content=f"Failed to assign role: {str(e)}",
                error_code="ASSIGN_ROLE_FAILED"
            )

    async def list_orgs(
        self,
        page: int = 1,
        limit: int = 10,
        search: Optional[str] = None,
        auth_token: Optional[str] = None,
        tenant_id: Optional[int] = None,
    ) -> ToolResult:
        """List all organization units."""
        try:
            params = {
                "query": {
                    "page": max(1, page),
                    "limit": max(1, min(100, limit))
                }
            }
            if search:
                params["query"]["search"] = search
            response = await self.http_client.execute(
                command="GET /v2/orgs",
                params=params,
                auth_token=auth_token or self.auth_token,
                tenant_id=tenant_id or self.tenant_id
            )

            orgs = response.get("data", response.get("orgs", []))
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

    async def get_org(
        self,
        org_id: Optional[str] = None,
        query: Optional[str] = None,
        auth_token: Optional[str] = None,
        tenant_id: Optional[int] = None,
    ) -> ToolResult:
        """Get organization unit details."""
        try:
            effective_token = auth_token or self.auth_token
            effective_tenant = tenant_id or self.tenant_id
            resolved_org_id, resolved_org = await self._resolve_org_id(
                org_id=org_id,
                query=query,
                auth_token=effective_token,
                tenant_id=effective_tenant,
            )
            params = {
                "path": {
                    "org_id": resolved_org_id
                }
            }
            response = await self.http_client.execute(
                command="GET /v2/orgs/{org_id}",
                params=params,
                auth_token=effective_token,
                tenant_id=effective_tenant
            )

            org = response.get("org", response)
            return ToolResult.success(
                content=f"Retrieved organization {resolved_org_id}",
                data={
                    **(response if isinstance(response, dict) else {"org": org}),
                    "resolved_org_id": resolved_org_id,
                    "resolved_org": resolved_org or org,
                }
            )
        except Exception as e:
            logger.error(f"Error getting organization {org_id or query}: {e}")
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

    async def get_subject_permissions(
        self,
        subject_type: str,
        subject_id: Optional[str] = None,
        query: Optional[str] = None,
        org_id: Optional[int] = None,
        auth_token: Optional[str] = None,
        tenant_id: Optional[int] = None,
    ) -> ToolResult:
        """Get permissions directly assigned to a subject."""
        try:
            normalized_subject_type = str(subject_type or "").strip().lower()
            effective_token = auth_token or self.auth_token
            effective_tenant = tenant_id or self.tenant_id or 1

            if normalized_subject_type not in {"member", "role", "org"}:
                return ToolResult.error(
                    content=f"Unsupported subject_type '{subject_type}'",
                    error_code="INVALID_SUBJECT_TYPE",
                )

            limitations: List[str] = []

            if normalized_subject_type == "member":
                resolved_subject_id = subject_id
                resolved_subject = None
                if not resolved_subject_id:
                    if not query:
                        return ToolResult.error(
                            content="Either subject_id or query is required for member permissions",
                            error_code="INVALID_MEMBER_LOOKUP",
                        )
                    member_lookup = await self.get_member_id(
                        query=query,
                        auth_token=effective_token,
                        tenant_id=effective_tenant,
                    )
                    if member_lookup.is_error:
                        return member_lookup
                    resolved_subject_id = str(member_lookup.data.get("member_id"))
                    resolved_subject = member_lookup.data.get("matched_member")

                params: Dict[str, Any] = {"path": {"id": int(resolved_subject_id)}}
                if org_id is not None:
                    params["query"] = {"org_id": org_id}

                response = await self.http_client.execute(
                    command="GET /v2/members/{id}/permissions",
                    params=params,
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                permissions = response.get("direct_permissions", [])
                return ToolResult.success(
                    content=f"Found {len(permissions)} direct permissions for member {resolved_subject_id}",
                    data={
                        "subject_type": "member",
                        "subject_id": str(resolved_subject_id),
                        "resolved_subject": resolved_subject,
                        "permissions": permissions,
                        "raw": response,
                        "limitations": limitations,
                    },
                )

            if normalized_subject_type == "role":
                resolved_subject_id, resolved_subject = await self._resolve_role_id(
                    role_id=subject_id,
                    role_query=query,
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                response = await self.http_client.execute(
                    command="GET /v2/roles/{id}/permissions",
                    params={"path": {"id": int(resolved_subject_id)}},
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                permissions = response if isinstance(response, list) else response.get("data", response.get("permissions", []))
                return ToolResult.success(
                    content=f"Found {len(permissions)} direct permissions for role {resolved_subject_id}",
                    data={
                        "subject_type": "role",
                        "subject_id": str(resolved_subject_id),
                        "resolved_subject": resolved_subject,
                        "permissions": permissions,
                        "raw": response,
                        "limitations": limitations,
                    },
                )

            resolved_org_id, resolved_org = await self._resolve_org_id(
                org_id=subject_id,
                query=query,
                auth_token=effective_token,
                tenant_id=effective_tenant,
            )
            limitations.append("Organization direct-permission API is not available in the public Membership command set.")
            return ToolResult.success(
                content=f"Organization {resolved_org_id} was resolved, but direct organization permission lookup is unavailable.",
                data={
                    "subject_type": "org",
                    "subject_id": str(resolved_org_id),
                    "resolved_subject": resolved_org,
                    "permissions": [],
                    "limitations": limitations,
                },
            )
        except Exception as e:
            logger.error(f"Error getting subject permissions for {subject_type}:{subject_id or query}: {e}")
            return ToolResult.error(
                content=f"Failed to get subject permissions: {str(e)}",
                error_code="GET_SUBJECT_PERMISSIONS_FAILED",
            )

    async def get_member_effective_permissions(
        self,
        member_id: Optional[str] = None,
        query: Optional[str] = None,
        org_id: Optional[int] = None,
        auth_token: Optional[str] = None,
        tenant_id: Optional[int] = None,
    ) -> ToolResult:
        """Get a member's effective permissions from available APIs."""
        try:
            effective_token = auth_token or self.auth_token
            effective_tenant = tenant_id or self.tenant_id or 1

            member_result = await self.get_member(
                member_id=member_id,
                query=query,
                auth_token=effective_token,
                tenant_id=effective_tenant,
            )
            if member_result.is_error:
                return member_result

            resolved_member_id = str(member_result.data.get("resolved_member_id") or member_result.data.get("id"))
            member = member_result.data.get("resolved_member") or member_result.data.get("member") or member_result.data

            params: Dict[str, Any] = {"path": {"id": int(resolved_member_id)}}
            if org_id is not None:
                params["query"] = {"org_id": org_id}
            permissions_response = await self.http_client.execute(
                command="GET /v2/members/{id}/permissions",
                params=params,
                auth_token=effective_token,
                tenant_id=effective_tenant,
            )
            roles_response = await self.http_client.execute(
                command="GET /v2/members/{id}/roles",
                params=params,
                auth_token=effective_token,
                tenant_id=effective_tenant,
            )
            member_orgs_result = await self.get_member_orgs(
                member_id=resolved_member_id,
                auth_token=effective_token,
                tenant_id=effective_tenant,
            )
            member_orgs: List[Dict[str, Any]] = []
            if not member_orgs_result.is_error:
                member_orgs = member_orgs_result.data.get("data", member_orgs_result.data.get("orgs", []))
                if not isinstance(member_orgs, list):
                    member_orgs = []

            ancestor_orgs: List[Dict[str, Any]] = []
            seen_org_ids = set()
            for org in member_orgs:
                org_identifier = org.get("id")
                if org_identifier is None:
                    continue
                hierarchy_result = await self.get_org_hierarchy(
                    org_id=str(org_identifier),
                    direction="ancestors",
                    max_depth=10,
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                if hierarchy_result.is_error:
                    continue
                for ancestor in hierarchy_result.data.get("ancestors", []):
                    ancestor_id = ancestor.get("id")
                    if ancestor_id is None or ancestor_id in seen_org_ids:
                        continue
                    seen_org_ids.add(ancestor_id)
                    ancestor_orgs.append(ancestor)

            direct_permissions = permissions_response.get("direct_permissions", [])
            role_permissions = permissions_response.get("role_permissions", [])
            member_roles = roles_response if isinstance(roles_response, list) else roles_response.get("data", roles_response.get("roles", []))

            effective_permissions: List[Dict[str, Any]] = []
            permission_keys = set()

            def add_permission(permission: Dict[str, Any], source_type: str, source_id: Optional[Any] = None, source_name: Optional[str] = None):
                if not isinstance(permission, dict):
                    return
                key = (
                    permission.get("id"),
                    permission.get("code"),
                    permission.get("resource"),
                    permission.get("action"),
                    source_type,
                    source_id,
                )
                if key in permission_keys:
                    return
                permission_keys.add(key)
                effective_permissions.append({
                    **permission,
                    "source_type": source_type,
                    "source_id": source_id,
                    "source_name": source_name,
                })

            for permission in direct_permissions:
                add_permission(permission, "member", resolved_member_id, member.get("username") or member.get("fullName"))

            for role_entry in role_permissions:
                role = role_entry.get("role", {}) if isinstance(role_entry, dict) else {}
                for permission in role_entry.get("permissions", []) if isinstance(role_entry, dict) else []:
                    add_permission(permission, "role", role.get("id"), role.get("name"))

            limitations: List[str] = []
            if member_orgs or ancestor_orgs:
                limitations.append("Organization-derived permissions were not expanded because the public Membership command set does not expose organization permission lookup.")

            return ToolResult.success(
                content=f"Computed effective permissions for member {resolved_member_id}",
                data={
                    "member": member,
                    "member_id": resolved_member_id,
                    "direct_permissions": direct_permissions,
                    "role_permissions": role_permissions,
                    "effective_permissions": effective_permissions,
                    "member_roles": member_roles,
                    "member_orgs": member_orgs,
                    "ancestor_orgs": ancestor_orgs,
                    "limitations": limitations,
                    "raw": {
                        "member_permissions": permissions_response,
                        "member_roles": roles_response,
                    },
                },
            )
        except Exception as e:
            logger.error(f"Error getting effective permissions for member {member_id or query}: {e}")
            return ToolResult.error(
                content=f"Failed to get member effective permissions: {str(e)}",
                error_code="GET_MEMBER_EFFECTIVE_PERMISSIONS_FAILED",
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

    async def create_resource(
        self,
        system_code: str,
        name: str,
        type: str,
        description: Optional[str] = None,
        access_mode: str = "whitelist",
        auth_token: Optional[str] = None,
        tenant_id: Optional[int] = None,
    ) -> ToolResult:
        """Create a new resource."""
        try:
            payload: Dict[str, Any] = {
                "system_code": system_code,
                "name": name,
                "type": type,
                "access_mode": access_mode or "whitelist",
            }
            if description:
                payload["description"] = description

            response = await self.http_client.execute(
                command="POST /v2/resources",
                params={"body": payload},
                auth_token=auth_token or self.auth_token,
                tenant_id=tenant_id or self.tenant_id,
            )

            return ToolResult.success(
                content=f"Created resource {name}",
                data=response,
            )
        except Exception as e:
            logger.error(f"Error creating resource {name}: {e}")
            return ToolResult.error(
                content=f"Failed to create resource: {str(e)}",
                error_code="CREATE_RESOURCE_FAILED",
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
