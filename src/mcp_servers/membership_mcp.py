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
            semantic_description="创建新成员账号。用于新增真实成员或虚拟成员，为后续组织关联、角色分配和权限授予提供主体。",
            use_cases=[
                "创建新用户",
                "创建测试成员或虚拟成员",
                "在给成员分配组织和角色前先建档",
            ],
            natural_language_examples=[
                "创建一个用户名为 zhangsan 的成员",
                "新增测试用户 test_user_01，邮箱 test@example.com",
            ],
            output_description="返回新建成员的详细信息，通常包含 id、username、email、status、is_virtual 等字段。",
            tags=["membership", "member", "create", "management", "task_tool"],
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
            semantic_description="更新成员基本资料，如用户名、邮箱或虚拟成员状态。适用于成员档案维护。",
            use_cases=[
                "修改成员资料",
                "修正用户名或邮箱",
                "调整成员虚拟身份标记",
            ],
            natural_language_examples=[
                "把成员 19 的邮箱改成 wangwh@example.com",
                "更新 admin 用户的资料",
            ],
            output_description="返回更新后的成员信息或更新结果，通常包含 member_id 和最新成员对象。",
            tags=["membership", "member", "update", "management", "task_tool"],
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
            semantic_description="删除成员账号。用于移除不再需要的成员记录，此操作通常是管理类高风险操作。",
            use_cases=[
                "删除测试成员",
                "移除错误创建的成员",
            ],
            natural_language_examples=[
                "删除成员 25",
                "把这个测试用户删掉",
            ],
            output_description="返回删除操作结果，通常包含删除状态、member_id 或后端确认信息。",
            tags=["membership", "member", "delete", "management", "dangerous_tool"],
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
            semantic_description="重置或修改成员密码。用于密码过期处理、人工重置密码或初始化账号密码。",
            use_cases=[
                "重置成员密码",
                "处理密码过期",
                "初始化成员登录密码",
            ],
            natural_language_examples=[
                "把 admin 的密码改成新密码",
                "重置成员 1 的密码",
            ],
            output_description="返回密码更新结果，通常包含 member_id、操作状态和后端确认信息。",
            tags=["membership", "member", "password", "security", "task_tool"],
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
            semantic_description="在指定组织下创建角色或岗位。用于后续给成员赋角色，并通过角色集中管理权限。",
            use_cases=[
                "创建岗位角色",
                "创建组织内的新角色",
                "为权限建模新增角色",
            ],
            natural_language_examples=[
                "在研发部创建一个 DevOps 角色",
                "新增一个 code 为 hr_admin 的角色",
            ],
            output_description="返回新建角色信息，通常包含 id、name、code、org_id、description、active。",
            tags=["membership", "role", "create", "management", "task_tool"],
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

        self.register_tool(Tool(
            name="lookup_org",
            description="Resolve an organization unit ID from organization details such as name, code, or type",
            semantic_description="根据组织名称、编码或类型解析唯一组织 ID。可直接接收完整组织数组，也可内部自动查询组织列表。",
            use_cases=[
                "根据自然语言线索获取组织 ID",
                "为组织详情、成员入组织、组织层级查询提供 org_id",
            ],
            natural_language_examples=[
                "研发部对应哪个组织 ID？",
                "Engineering 这个组织的 ID 是多少？",
            ],
            output_description="返回 status、org_id、matched_org、candidates，用于后续步骤继续执行。",
            tags=["membership", "org", "id_resolution", "lookup", "task_tool"],
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The organization name, code, type, or descriptive text to match"
                    },
                    "orgs": {
                        "type": "array",
                        "description": "Optional full organization objects from a previous list_orgs step"
                    },
                    "match_fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional fields to match against. Defaults to name/code/type"
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
            handler=self.lookup_org
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
            semantic_description="创建新的组织单元，可用于公司、部门、团队、项目组等组织结构维护。",
            use_cases=[
                "新增部门或团队",
                "创建临时项目组",
                "维护组织架构",
            ],
            natural_language_examples=[
                "创建一个叫 Engineering Platform 的团队",
                "在研发中心下面新增测试部",
            ],
            output_description="返回新建组织信息，通常包含 id、name、type、parent_id、description、is_temporary。",
            tags=["membership", "org", "create", "management", "task_tool"],
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
            name="get_member_roles",
            description="Get all roles assigned to a member by member ID or by member query",
            semantic_description="获取成员拥有的所有角色。支持 member_id，也支持按用户名、姓名、邮箱等 query 自动解析成员后查询角色。",
            use_cases=[
                "查看成员属于哪些角色",
                "查询用户拥有哪些岗位/角色",
                "为成员有效权限汇总提供角色来源",
            ],
            natural_language_examples=[
                "list all roles user wangwh belong to",
                "王维宏有哪些角色？",
                "admin 属于哪些角色？",
            ],
            output_description="返回 member_id、resolved_member、roles、raw。roles 中通常包含 role 对象、org_id、granted_at、granted_by。",
            tags=["membership", "member", "role", "lookup", "task_tool"],
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
                        "description": "Optional org scope for member roles"
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
            handler=self.get_member_roles
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
            semantic_description="更新组织单元的基本资料，如名称、描述、临时属性或有效期。",
            use_cases=[
                "修改组织名称",
                "更新组织描述",
                "调整临时组织有效期",
            ],
            natural_language_examples=[
                "把 org 5 的名字改成 Platform Team",
                "更新测试部的说明信息",
            ],
            output_description="返回更新后的组织信息或更新结果，通常包含 org_id 和最新组织对象。",
            tags=["membership", "org", "update", "management", "task_tool"],
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
            semantic_description="删除或归档组织单元。用于清理错误创建或停用的组织结构节点，属于管理类高风险操作。",
            use_cases=[
                "删除错误创建的组织",
                "归档不再使用的临时组织",
            ],
            natural_language_examples=[
                "删除 org 12",
                "把这个临时项目组归档",
            ],
            output_description="返回删除或归档结果，通常包含 org_id、状态和后端确认信息。",
            tags=["membership", "org", "delete", "management", "dangerous_tool"],
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
            description="Assign a member to an organization unit by IDs or by member/org query",
            semantic_description="将成员加入组织。支持直接传 member_id/org_id，也支持按成员名称和组织名称自动解析后完成关联。",
            use_cases=[
                "把成员加入组织",
                "根据自然语言指定成员和组织完成关联",
            ],
            natural_language_examples=[
                "把 kehongwei 加入研发部",
                "add wangwh to Engineering",
            ],
            output_description="返回 member_id、org_id、resolved_member、resolved_org 以及关联结果。",
            tags=["membership", "member", "org", "assignment", "task_tool"],
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
                    "member_query": {
                        "type": "string",
                        "description": "Member lookup text such as username, full name, or email"
                    },
                    "org_query": {
                        "type": "string",
                        "description": "Organization lookup text such as organization name or code"
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
            handler=self.assign_member_to_org
        ))

        # Get member organizations tool
        self.register_tool(Tool(
            name="get_member_orgs",
            description="Get all organizations a member belongs to",
            semantic_description="查询成员所属的全部组织。常用于分析成员所在部门、计算成员继承权限、继续查询组织层级。",
            use_cases=[
                "查看成员所在组织",
                "为权限分析获取组织上下文",
                "确认成员是否属于某部门",
            ],
            natural_language_examples=[
                "wangwh 属于哪些组织？",
                "显示成员 19 的所属部门",
            ],
            output_description="返回成员组织列表，通常包含 org_id、name、type、parent_id，以及成员与组织关联信息。",
            tags=["membership", "member", "org", "relation", "task_tool"],
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
            semantic_description="将成员从指定组织中移除。用于组织调整、离岗或撤销成员与组织的关联。",
            use_cases=[
                "把成员移出部门",
                "撤销成员所属组织关系",
            ],
            natural_language_examples=[
                "把成员 19 从 org 3 移除",
                "remove wangwh from Engineering",
            ],
            output_description="返回移除操作结果，通常包含 member_id、org_id 和后端确认状态。",
            tags=["membership", "member", "org", "unassignment", "task_tool"],
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
            semantic_description="查询组织层级关系，包括上级组织、下级组织或双向层级。用于组织树分析和权限继承分析。",
            use_cases=[
                "查看组织上下级关系",
                "分析组织树",
                "为成员有效权限计算补充组织链路",
            ],
            natural_language_examples=[
                "显示研发部的上级和下级组织",
                "Engineering 的组织层级是什么？",
            ],
            output_description="返回层级结构数据，通常包含 org_id、ancestors、descendants、depth 或相关层级节点数组。",
            tags=["membership", "org", "hierarchy", "relation", "task_tool"],
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

        self.register_tool(Tool(
            name="render_org_chart",
            description="Render an organization's structure as Mermaid graph markdown for chat display",
            semantic_description="将当前租户或指定根组织的组织结构渲染成 Mermaid 图，适合在 AI 助手对话中直接展示组织树。",
            use_cases=[
                "显示整个租户的组织结构图",
                "查看某个组织节点下面的树形结构",
                "在聊天里可视化组织机构",
            ],
            natural_language_examples=[
                "显示当前租户的组织结构图",
                "用 mermaid 画出研发部下面的组织树",
            ],
            output_description="返回 markdown 文本，其中包含 ```mermaid 代码块，以及 org_count、root_org、nodes 等结构化数据。",
            tags=["membership", "org", "tree", "visualization", "mermaid", "task_tool"],
            input_schema={
                "type": "object",
                "properties": {
                    "org_id": {
                        "type": "string",
                        "description": "Optional root organization ID. If omitted, render the tenant/root organization tree."
                    },
                    "query": {
                        "type": "string",
                        "description": "Optional organization lookup text such as name or code"
                    },
                    "include_inactive": {
                        "type": "boolean",
                        "description": "Whether to include inactive organizations in the chart",
                        "default": True
                    },
                    "max_nodes": {
                        "type": "integer",
                        "description": "Maximum nodes to render in the Mermaid chart",
                        "default": 80
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["TD", "LR"],
                        "description": "Mermaid graph direction: top-down or left-right",
                        "default": "TD"
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
            handler=self.render_org_chart
        ))

        self._register_root_admin_tools()
        self._register_llm_tools()

        # Submit audit event tool
        self.register_tool(Tool(
            name="submit_audit_event",
            description="Submit a single audit event to the membership audit service",
            semantic_description="向审计服务提交单条审计事件。适用于记录登录、系统操作、API 调用、数据变更等行为。",
            use_cases=[
                "记录单条审计日志",
                "MCP 或系统调用后补充审计事件",
                "安全与合规留痕",
            ],
            natural_language_examples=[
                "提交一条用户登录审计日志",
                "记录一次 MCP 客户端连接事件",
            ],
            output_description="返回审计写入结果，通常包含事件接收状态、事件标识或后端确认信息。",
            tags=["membership", "audit", "logging", "write", "task_tool"],
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
            semantic_description="批量提交多条审计事件。适用于批处理同步、日志回灌或一次性补录多条操作轨迹。",
            use_cases=[
                "批量写入审计日志",
                "同步历史操作事件",
                "批处理导入审计记录",
            ],
            natural_language_examples=[
                "批量提交这 10 条审计事件",
                "把这些 API 调用记录写入审计系统",
            ],
            output_description="返回批量写入结果，通常包含接收数量、成功数量、失败项或后端确认信息。",
            tags=["membership", "audit", "logging", "batch", "task_tool"],
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

    def _register_root_admin_tools(self) -> None:
        """Register root/admin task tools."""
        auth_props = {
            "auth_token": {
                "type": "string",
                "description": "Authentication token (optional, will use default if not provided)"
            },
            "tenant_id": {
                "type": "integer",
                "description": "Tenant ID header override when the API requires tenant context"
            }
        }

        self.register_tool(Tool(
            name="manage_tenant",
            description="Root tenant administration task tool for tenant lifecycle and tenant-member management",
            semantic_description="面向 root/admin 的租户管理任务工具。统一处理租户列表、详情、创建、更新、启用、停用、初始化，以及成员加入或移出租户等系统管理操作。",
            use_cases=["创建租户", "初始化租户", "启用或停用租户", "把成员加入或移出租户", "检查多租户一致性和统计信息"],
            natural_language_examples=["创建一个新的租户 Acme", "初始化租户 33", "把成员 15 加入租户 33", "检查当前系统的租户一致性"],
            output_description="根据 action 返回租户列表、租户详情、初始化结果、租户成员操作结果、统计信息或一致性检查结果。",
            tags=["membership", "root", "tenant", "admin", "task_tool"],
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "get", "create", "update", "activate", "deactivate", "initialize", "add_member", "remove_member", "statistics", "validate_system_orgs", "validate_consistency"],
                        "description": "Tenant administration action"
                    },
                    "tenant_id_param": {"type": "integer", "description": "Target tenant ID for tenant-specific actions"},
                    "member_id": {"type": "integer", "description": "Member ID for add_member/remove_member actions"},
                    "name": {"type": "string", "description": "Tenant name for create/update"},
                    "description": {"type": "string", "description": "Tenant description for create/update"},
                    "page": {"type": "integer", "description": "Page number for list action", "default": 1},
                    "page_size": {"type": "integer", "description": "Page size for list action", "default": 20},
                    **auth_props,
                },
                "required": ["action"]
            },
            handler=self.manage_tenant
        ))

        self.register_tool(Tool(
            name="manage_agent",
            description="Root/admin task tool for agent inventory, credentials, policy, and execution logs",
            semantic_description="面向 root/admin 的 Agent 管理任务工具。统一处理 Agent 列表、凭证查看与创建、策略查看与更新，以及运行日志查询。",
            use_cases=["查看所有 Agent", "给 Agent 创建凭证", "检查或更新 Agent policy", "查看 Agent 运行日志"],
            natural_language_examples=["列出所有 llm agents", "给 agent 12 创建 api_key 凭证", "查看 agent 12 的策略", "查询 agent 12 最近的执行日志"],
            output_description="根据 action 返回 agent 列表、凭证信息、策略对象、更新结果或日志列表。",
            tags=["membership", "root", "agent", "admin", "task_tool"],
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "get_credentials", "create_credentials", "get_policy", "update_policy", "get_logs"],
                        "description": "Agent administration action"
                    },
                    "agent_id": {"type": "integer", "description": "Agent/member ID for credential/policy/log actions"},
                    "page": {"type": "integer", "description": "Page number for list/log actions", "default": 1},
                    "page_size": {"type": "integer", "description": "Page size for list/log actions", "default": 20},
                    "agent_type": {"type": "string", "description": "Agent type filter for list action"},
                    "owner_id": {"type": "integer", "description": "Owner member ID filter for list action"},
                    "credential_type": {"type": "string", "enum": ["api_key", "oauth2", "jwt"], "description": "Credential type for create_credentials"},
                    "expires_at": {"type": "string", "format": "date-time", "description": "Credential expiration for create_credentials"},
                    "scope_json": {"type": "object", "description": "Credential scope for create_credentials"},
                    "policy": {"type": "object", "description": "Full AgentPolicy object for update_policy"},
                    "start_time": {"type": "string", "format": "date-time", "description": "Log query start time"},
                    "end_time": {"type": "string", "format": "date-time", "description": "Log query end time"},
                    "status": {"type": "string", "description": "Log status filter"},
                    **auth_props,
                },
                "required": ["action"]
            },
            handler=self.manage_agent
        ))

        self.register_tool(Tool(
            name="manage_settings",
            description="Root/admin task tool for global or org-level settings management",
            semantic_description="面向 root/admin 的系统配置管理任务工具。统一处理配置列表、单项读取、添加或更新配置、删除配置。",
            use_cases=["查看全局配置", "查询某个 org 的配置项", "更新系统设置", "删除指定配置"],
            natural_language_examples=["列出全局 settings", "查看 org 0 的 llm.default_provider 配置", "把 org 0 的某个 key 改成新值", "删除 org 12 的某个设置"],
            output_description="根据 action 返回 settings 列表、单项配置对象、写入结果或删除结果。",
            tags=["membership", "root", "settings", "admin", "task_tool"],
            input_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["list", "get", "upsert", "delete"], "description": "Settings administration action"},
                    "org_id": {"type": "integer", "description": "Organization ID, use 0 for global settings", "default": 0},
                    "key": {"type": "string", "description": "Setting key"},
                    "value": {"type": "string", "description": "Setting value for upsert"},
                    "description": {"type": "string", "description": "Optional setting description for upsert"},
                    **auth_props,
                },
                "required": ["action"]
            },
            handler=self.manage_settings
        ))

        self.register_tool(Tool(
            name="query_audit_logs",
            description="Root/admin task tool for querying audit logs with common filters",
            semantic_description="面向 root/admin 的审计日志查询任务工具。支持按时间范围、操作者、动作类型和目标类型检索审计记录。",
            use_cases=["排查系统操作历史", "查询某成员的管理动作", "按时间窗口检查安全审计事件"],
            natural_language_examples=["查询今天的审计日志", "查看 operator 19 的所有管理操作", "列出 target_type 为 member 的审计记录"],
            output_description="返回审计日志数组和分页信息，日志包含 operator_id、action_type、target_type、before_data、after_data、created_at 等字段。",
            tags=["membership", "root", "audit", "admin", "task_tool"],
            input_schema={
                "type": "object",
                "properties": {
                    "page": {"type": "integer", "description": "Page number", "default": 1},
                    "page_size": {"type": "integer", "description": "Page size", "default": 20},
                    "start_time": {"type": "string", "format": "date-time", "description": "Query start time"},
                    "end_time": {"type": "string", "format": "date-time", "description": "Query end time"},
                    "operator_id": {"type": "integer", "description": "Operator member ID"},
                    "action_type": {"type": "string", "description": "Action type filter"},
                    "target_type": {"type": "string", "description": "Target type filter"},
                    **auth_props,
                }
            },
            handler=self.query_audit_logs
        ))

        self.register_tool(Tool(
            name="manage_auth_session",
            description="Admin/session task tool for login, token issuing, OTP flow, auto-login, token refresh, and authz checks",
            semantic_description="认证与会话管理任务工具。支持密码登录、令牌签发、OTP 请求与登录、自动登录、刷新 access token，以及 resource/action 级鉴权检查。适合管理员或系统集成场景，不应作为普通查询工具默认使用。",
            use_cases=["登录获取 access token", "给 agent 或集成签发 token", "发起 OTP 登录流程", "刷新 access token", "检查某资源动作是否允许"],
            natural_language_examples=["用用户名密码登录", "给这个 client 签发 access token", "请求 admin@example.com 的登录 OTP", "刷新当前 access token", "检查某成员是否允许访问某资源"],
            output_description="根据 action 返回 access_token、refresh_token、otp_token、expires_in、member_id、allowed 或错误信息。",
            tags=["membership", "auth", "session", "admin", "sensitive_tool", "task_tool"],
            input_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["issue_token", "login", "request_otp", "otp_login", "auto_login", "refresh_token", "check_authz"], "description": "Authentication/session action"},
                    "grant_type": {"type": "string", "enum": ["password", "client_credentials", "refresh_token"], "description": "Grant type for issue_token"},
                    "username": {"type": "string", "description": "Username for login or password grant"},
                    "password": {"type": "string", "description": "Password for login or password grant"},
                    "device_id": {"type": "string", "description": "Device ID for login or auto-login"},
                    "client_id": {"type": "string", "description": "Client ID for client_credentials grant"},
                    "client_secret": {"type": "string", "description": "Client secret for client_credentials grant"},
                    "refresh_token": {"type": "string", "description": "Refresh token for issue_token(refresh_token)"},
                    "contact": {"type": "string", "description": "Phone number or email for OTP"},
                    "channel": {"type": "string", "enum": ["SMS", "EMAIL"], "description": "OTP delivery channel"},
                    "purpose": {"type": "string", "enum": ["login", "register", "reset_password"], "description": "OTP purpose"},
                    "otp_code": {"type": "string", "description": "OTP verification code"},
                    "otp_token": {"type": "string", "description": "OTP token returned by request_otp"},
                    "auto_login_token": {"type": "string", "description": "Auto login token"},
                    "resource": {"type": "string", "description": "Resource code for check_authz"},
                    "permission_action": {"type": "string", "description": "Action name for check_authz"},
                    "org_id": {"type": "integer", "description": "Organization context for check_authz"},
                    "on_behalf_of": {"type": "integer", "description": "Member ID to evaluate authz on behalf of"},
                    **auth_props,
                },
                "required": ["action"]
            },
            handler=self.manage_auth_session
        ))

    def _register_llm_tools(self) -> None:
        """Register Membership LLM provider/config management tools."""
        auth_props = {
            "auth_token": {
                "type": "string",
                "description": "Authentication token (optional, will use default if not provided)"
            },
            "tenant_id": {
                "type": "integer",
                "description": "Tenant ID (optional, will use default if not provided)"
            }
        }
        provider_props = {
            "name": {"type": "string", "description": "Provider unique name"},
            "type": {"type": "string", "description": "Provider type, e.g. openai, qwen, ollama"},
            "baseUrl": {"type": "string", "description": "OpenAI-compatible API base URL"},
            "model": {"type": "string", "description": "Default model name"},
            "apiKeyRef": {"type": "string", "description": "Environment variable reference for the API key, e.g. QWEN_API_KEY"},
            "apiKey": {"type": "string", "description": "Direct API key value when the Membership API accepts it; prefer apiKeyRef for safer configuration"},
            "enabled": {"type": "boolean", "description": "Whether this provider is enabled", "default": True},
            "active": {"type": "boolean", "description": "Whether this provider is the active/default provider", "default": False},
            "priority": {"type": "integer", "description": "Provider priority, smaller usually means higher priority", "default": 1},
            "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 30},
            "temperature": {"type": "number", "description": "Default temperature", "default": 0.7},
            "maxTokens": {"type": "integer", "description": "Default max tokens", "default": 2048},
            "topP": {"type": "number", "description": "Default top_p", "default": 1.0},
            "costPer1kTokens": {"type": "number", "description": "Estimated cost per 1k tokens", "default": 0.001},
            "capabilities": {"type": "array", "items": {"type": "string"}, "description": "Capability tags, e.g. chat, embedding, vision"},
            "contextWindow": {"type": "integer", "description": "Context window size", "default": 4096},
            "supportsMultimodal": {"type": "boolean", "description": "Whether multimodal inputs are supported", "default": False},
            "supportedFormats": {"type": "array", "items": {"type": "string"}, "description": "Supported input formats"},
            "embeddingDimensions": {"type": "integer", "description": "Embedding dimensions when this provider supports embeddings"},
            "metadata": {"type": "object", "description": "Provider metadata"}
        }

        self.register_tool(Tool(
            name="list_llm_providers",
            description="List all LLM providers managed by Membership",
            semantic_description="列出 Membership 统一管理的 LLM Provider 配置，用于查看可用模型提供方、模型、能力、启停状态和优先级。",
            use_cases=["查看所有 LLM providers", "检查可用模型配置", "查看 DocIntel 可用的 LLM 提供方"],
            natural_language_examples=["列出所有 LLM providers", "有哪些模型提供商？", "show llm providers"],
            output_description="返回 providers 数组，包含 name、type、baseUrl、model、enabled、active、priority、capabilities 等字段。",
            tags=["membership", "llm", "provider", "list", "task_tool"],
            input_schema={"type": "object", "properties": {**auth_props}},
            handler=self.list_llm_providers
        ))

        self.register_tool(Tool(
            name="get_llm_provider",
            description="Get a specific LLM provider by name",
            semantic_description="按 Provider 名称查询单个 LLM Provider 配置详情。",
            use_cases=["查看指定 LLM provider", "检查某个模型提供方配置"],
            natural_language_examples=["查看 qwen provider", "get llm provider deepseek"],
            output_description="返回指定 Provider 的完整配置。",
            tags=["membership", "llm", "provider", "profile", "task_tool"],
            input_schema={
                "type": "object",
                "properties": {"name": provider_props["name"], **auth_props},
                "required": ["name"]
            },
            handler=self.get_llm_provider
        ))

        self.register_tool(Tool(
            name="create_llm_provider",
            description="Create an LLM provider",
            semantic_description="创建新的 LLM Provider 配置，写入 Membership 共享 MongoDB 的 llm_providers 集合。",
            use_cases=["新增 LLM provider", "配置新的模型提供商", "添加 OpenAI-compatible LLM"],
            natural_language_examples=["创建一个 qwen LLM provider", "add an OpenAI compatible provider"],
            output_description="返回创建后的 Provider 配置。",
            tags=["membership", "llm", "provider", "create", "task_tool"],
            input_schema={
                "type": "object",
                "properties": {**provider_props, **auth_props},
                "required": ["name"]
            },
            handler=self.create_llm_provider
        ))

        self.register_tool(Tool(
            name="update_llm_provider",
            description="Update an LLM provider",
            semantic_description="更新指定 LLM Provider 配置。name 用于路径定位，其余字段作为配置内容发送。",
            use_cases=["更新 LLM provider", "修改模型名称/baseUrl/能力/优先级"],
            natural_language_examples=["把 qwen provider 的 model 改成 qwen-plus", "update deepseek provider"],
            output_description="返回更新后的 Provider 配置。",
            tags=["membership", "llm", "provider", "update", "task_tool"],
            input_schema={
                "type": "object",
                "properties": {**provider_props, **auth_props},
                "required": ["name"]
            },
            handler=self.update_llm_provider
        ))

        self.register_tool(Tool(
            name="delete_llm_provider",
            description="Delete an LLM provider by name",
            semantic_description="删除指定名称的 LLM Provider 配置。",
            use_cases=["删除 LLM provider", "移除模型提供方配置"],
            natural_language_examples=["删除 qwen provider", "remove llm provider deepseek"],
            output_description="返回 deleted Provider 名称。",
            tags=["membership", "llm", "provider", "delete", "task_tool"],
            input_schema={
                "type": "object",
                "properties": {"name": provider_props["name"], **auth_props},
                "required": ["name"]
            },
            handler=self.delete_llm_provider
        ))

        self.register_tool(Tool(
            name="set_llm_provider_enabled",
            description="Enable or disable an LLM provider",
            semantic_description="启用或禁用指定 LLM Provider。",
            use_cases=["启用 LLM provider", "禁用某个模型提供商"],
            natural_language_examples=["禁用 qwen provider", "enable llm provider deepseek"],
            output_description="返回 name 和 enabled 状态。",
            tags=["membership", "llm", "provider", "enabled", "task_tool"],
            input_schema={
                "type": "object",
                "properties": {"name": provider_props["name"], "enabled": provider_props["enabled"], **auth_props},
                "required": ["name", "enabled"]
            },
            handler=self.set_llm_provider_enabled
        ))

        self.register_tool(Tool(
            name="set_active_llm_provider",
            description="Set an LLM provider as the active/default provider",
            semantic_description="将指定 LLM Provider 设置为当前租户默认/active Provider。",
            use_cases=["设置默认 LLM provider", "切换当前活动模型提供方"],
            natural_language_examples=["把 qwen 设置为默认 LLM provider", "set deepseek as active provider"],
            output_description="返回 success 和 active Provider 名称。",
            tags=["membership", "llm", "provider", "active", "default", "task_tool"],
            input_schema={
                "type": "object",
                "properties": {"name": provider_props["name"], **auth_props},
                "required": ["name"]
            },
            handler=self.set_active_llm_provider
        ))

        purpose_prop = {
            "type": "string",
            "description": "LLM usage purpose, e.g. translation, docintel.chat, docintel.embedding, docintel.extraction"
        }
        self.register_tool(Tool(
            name="list_llm_usage_configs",
            description="List all LLM usage configurations",
            semantic_description="列出当前租户的 LLM 用途配置，例如 translation、docintel.chat、docintel.embedding、docintel.extraction 使用哪些 Provider。",
            use_cases=["查看 LLM 用途配置", "检查 DocIntel chat/embedding 使用哪个 provider"],
            natural_language_examples=["列出 LLM usage configs", "DocIntel chat 用哪个 provider？"],
            output_description="返回 configs 数组和 total。",
            tags=["membership", "llm", "usage_config", "list", "task_tool"],
            input_schema={"type": "object", "properties": {**auth_props}},
            handler=self.list_llm_usage_configs
        ))

        self.register_tool(Tool(
            name="upsert_llm_usage_config",
            description="Create or update an LLM usage configuration",
            semantic_description="为指定用途保存 LLM Provider 配置。providerNames 是有序列表，第一个为主 provider，后续为 fallback。",
            use_cases=["配置 DocIntel chat 的 provider", "配置 embedding provider", "设置 translation fallback providers"],
            natural_language_examples=["把 docintel.chat 配置为 qwen, deepseek", "set embedding providers to qwen-embedding"],
            output_description="返回 success 和 config。",
            tags=["membership", "llm", "usage_config", "upsert", "task_tool"],
            input_schema={
                "type": "object",
                "properties": {
                    "purpose": purpose_prop,
                    "providerNames": {"type": "array", "items": {"type": "string"}, "description": "Ordered provider names"},
                    "fallbackToEnv": {"type": "boolean", "description": "Whether to fall back to .env config", "default": True},
                    "description": {"type": "string", "description": "Optional note"},
                    **auth_props
                },
                "required": ["purpose", "providerNames"]
            },
            handler=self.upsert_llm_usage_config
        ))

        self.register_tool(Tool(
            name="delete_llm_usage_config",
            description="Delete an LLM usage configuration",
            semantic_description="删除指定用途的 LLM 配置，之后将回退到环境变量配置。",
            use_cases=["删除某个 LLM 用途配置", "恢复到环境变量 LLM 配置"],
            natural_language_examples=["删除 docintel.chat 的 LLM 配置", "remove translation usage config"],
            output_description="返回 success 和 deleted purpose。",
            tags=["membership", "llm", "usage_config", "delete", "task_tool"],
            input_schema={
                "type": "object",
                "properties": {"purpose": purpose_prop, **auth_props},
                "required": ["purpose"]
            },
            handler=self.delete_llm_usage_config
        ))

        self.register_tool(Tool(
            name="resolve_llm_usage_config",
            description="Preview resolved providers for an LLM usage purpose",
            semantic_description="预览指定用途实际解析出的 LLM Provider 列表，包括 MongoDB 配置和 .env fallback。",
            use_cases=["查看 DocIntel chat 实际会用哪些 provider", "检查 embedding provider 解析结果"],
            natural_language_examples=["解析 docintel.chat 的 provider", "which providers are used for docintel.embedding?"],
            output_description="返回 purpose、count、providers，providers 包含 name、model、baseUrl、source。",
            tags=["membership", "llm", "usage_config", "resolve", "task_tool"],
            input_schema={
                "type": "object",
                "properties": {"purpose": purpose_prop, **auth_props},
                "required": ["purpose"]
            },
            handler=self.resolve_llm_usage_config
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

    async def lookup_org(
        self,
        query: str,
        orgs: Optional[List[Dict[str, Any]]] = None,
        match_fields: Optional[List[str]] = None,
        auth_token: Optional[str] = None,
        tenant_id: Optional[int] = None,
    ) -> ToolResult:
        """Resolve an organization ID from organization details or by querying the membership service."""
        try:
            if not query or not str(query).strip():
                return ToolResult.error(
                    content="Organization query cannot be empty",
                    error_code="INVALID_ORG_QUERY",
                )

            effective_token = auth_token or self.auth_token
            effective_tenant = tenant_id or self.tenant_id or 1
            fields = match_fields or ["name", "code", "type"]

            candidate_orgs = orgs
            if not candidate_orgs:
                if not effective_token:
                    return ToolResult.error(
                        content="Authentication required to fetch organizations for org ID resolution.",
                        error_code="AUTH_REQUIRED",
                    )
                response = await self.http_client.execute(
                    command="GET /v2/orgs",
                    params={"query": {"page": 1, "limit": 100, "search": query}},
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                candidate_orgs = response.get("data", response.get("orgs", []))

            candidate_orgs = [item for item in (candidate_orgs or []) if isinstance(item, dict)]
            matches = self._resolve_generic_matches(candidate_orgs, query, fields)

            if len(matches) == 1:
                org = matches[0]
                result = {
                    "status": "unique",
                    "query": query,
                    "org_id": org.get("id"),
                    "matched_org": org,
                    "reason": "matched using exact organization fields",
                    "match_method": "deterministic",
                }
                return ToolResult.success(
                    content=f"Resolved organization '{query}' to ID {org.get('id')}",
                    data=result,
                )

            if not matches:
                return ToolResult.error(
                    content=f"No organization matched query '{query}'",
                    error_code="ORG_NOT_FOUND",
                    data={"status": "not_found", "query": query},
                )

            return ToolResult.error(
                content=f"Multiple organizations matched query '{query}'",
                error_code="MULTIPLE_ORG_MATCHES",
                data={"status": "multiple", "query": query, "candidates": matches[:10]},
            )
        except Exception as e:
            logger.error(f"Error resolving organization ID for query '{query}': {e}")
            return ToolResult.error(
                content=f"Failed to resolve organization ID: {str(e)}",
                error_code="LOOKUP_ORG_FAILED",
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

    async def render_org_chart(
        self,
        org_id: Optional[str] = None,
        query: Optional[str] = None,
        include_inactive: bool = True,
        max_nodes: int = 80,
        direction: str = "TD",
        auth_token: Optional[str] = None,
        tenant_id: Optional[int] = None,
    ) -> ToolResult:
        """Render organization tree as Mermaid markdown."""
        try:
            effective_token = auth_token or self.auth_token
            effective_tenant = tenant_id or self.tenant_id or 1

            resolved_org_id: Optional[int] = None
            resolved_org: Optional[Dict[str, Any]] = None
            if org_id or query:
                resolved_org_id_str, resolved_org = await self._resolve_org_id(
                    org_id=org_id,
                    query=query,
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                resolved_org_id = int(resolved_org_id_str)

            response = await self.http_client.execute(
                command="GET /v2/orgs",
                params={"query": {"page": 1, "limit": max(100, min(max_nodes * 2, 500))}},
                auth_token=effective_token,
                tenant_id=effective_tenant,
            )
            orgs = response.get("data", response.get("orgs", [])) if isinstance(response, dict) else []
            chart = self._org_mermaid_body(
                orgs=orgs,
                root_org_id=resolved_org_id,
                include_inactive=include_inactive,
                max_nodes=max(10, min(max_nodes, 200)),
                direction=direction if direction in {"TD", "LR"} else "TD",
            )
            if chart.get("error"):
                return ToolResult.error(
                    content=chart["error"],
                    error_code="RENDER_ORG_CHART_FAILED",
                )

            title = self._safe_mermaid_label((resolved_org or {}).get("name") or f"Tenant {effective_tenant} Organization Structure")
            markdown = f"## {title}\n\n```mermaid\n{chart['mermaid']}\n```"
            if chart.get("truncated"):
                markdown += f"\n\nShowing first {chart['displayed']} of {chart['total_available']} organizations."

            rendered_ids = {str(i) for i in chart["ordered_ids"]}
            rendered_nodes = [org for org in orgs if isinstance(org, dict) and str(org.get("id")) in rendered_ids]

            return ToolResult.success(
                content=markdown,
                data={
                    "markdown": markdown,
                    "mermaid": chart["mermaid"],
                    "org_count": chart["displayed"],
                    "total_available": chart["total_available"],
                    "root_org": chart.get("root_org") or resolved_org,
                    "nodes": rendered_nodes,
                    "resolved_org_id": resolved_org_id,
                    "resolved_org": resolved_org,
                }
            )
        except Exception as e:
            logger.error(f"Error rendering org chart for {org_id or query}: {e}")
            return ToolResult.error(
                content=f"Failed to render organization chart: {str(e)}",
                error_code="RENDER_ORG_CHART_FAILED"
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

    async def assign_member_to_org(
        self,
        member_id: Optional[str] = None,
        org_id: Optional[str] = None,
        member_query: Optional[str] = None,
        org_query: Optional[str] = None,
        auth_token: Optional[str] = None,
        tenant_id: Optional[int] = None,
    ) -> ToolResult:
        """Assign a member to an organization unit."""
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

            resolved_org_id, resolved_org = await self._resolve_org_id(
                org_id=org_id,
                query=org_query,
                auth_token=effective_token,
                tenant_id=effective_tenant,
            )

            payload = {"org_id": resolved_org_id}
            params = {
                "path": {
                    "member_id": resolved_member_id
                },
                "body": payload
            }
            response = await self.http_client.execute(
                command="POST /v2/members/{member_id}/orgs",
                params=params,
                auth_token=effective_token,
                tenant_id=effective_tenant
            )

            return ToolResult.success(
                content=f"Assigned member {resolved_member_id} to organization {resolved_org_id}",
                data={
                    **(response if isinstance(response, dict) else {"result": response}),
                    "member_id": resolved_member_id,
                    "org_id": resolved_org_id,
                    "resolved_member": resolved_member,
                    "resolved_org": resolved_org,
                }
            )
        except Exception as e:
            logger.error(f"Error assigning member to organization: {e}")
            return ToolResult.error(
                content=f"Failed to assign member to organization: {str(e)}",
                error_code="ASSIGN_MEMBER_TO_ORG_FAILED"
            )

    async def get_member_roles(
        self,
        member_id: Optional[str] = None,
        query: Optional[str] = None,
        org_id: Optional[int] = None,
        auth_token: Optional[str] = None,
        tenant_id: Optional[int] = None,
    ) -> ToolResult:
        """Get all roles a member has."""
        try:
            effective_token = auth_token or self.auth_token
            effective_tenant = tenant_id or self.tenant_id or 1
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

            params: Dict[str, Any] = {"path": {"id": int(resolved_member_id)}}
            if org_id is not None:
                params["query"] = {"org_id": org_id}

            response = await self.http_client.execute(
                command="GET /v2/members/{id}/roles",
                params=params,
                auth_token=effective_token,
                tenant_id=effective_tenant,
            )
            roles = response if isinstance(response, list) else response.get("data", response.get("roles", []))
            if not isinstance(roles, list):
                roles = []

            role_names = []
            for role_entry in roles[:5]:
                if not isinstance(role_entry, dict):
                    continue
                role = role_entry.get("role") if isinstance(role_entry.get("role"), dict) else role_entry
                role_names.append(role.get("name") or role.get("code") or str(role.get("id", "Unknown")))
            content_lines = [f"Found {len(roles)} roles for member {resolved_member_id}"]
            if role_names:
                content_lines.append("\nRoles:")
                content_lines.extend(f"  • {name}" for name in role_names)
                if len(roles) > len(role_names):
                    content_lines.append(f"  ... and {len(roles) - len(role_names)} more")

            return ToolResult.success(
                content="\n".join(content_lines),
                data={
                    "member_id": str(resolved_member_id),
                    "resolved_member": resolved_member,
                    "roles": roles,
                    "raw": response,
                },
            )
        except Exception as e:
            logger.error(f"Error getting member roles for {member_id or query}: {e}")
            return ToolResult.error(
                content=f"Failed to get member roles: {str(e)}",
                error_code="GET_MEMBER_ROLES_FAILED",
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

    def _build_llm_provider_payload(self, **kwargs: Any) -> Dict[str, Any]:
        allowed_fields = [
            "name", "type", "baseUrl", "model", "apiKeyRef", "apiKey",
            "enabled", "active", "priority", "timeout", "temperature",
            "maxTokens", "topP", "costPer1kTokens", "capabilities",
            "contextWindow", "supportsMultimodal", "supportedFormats",
            "embeddingDimensions", "metadata",
        ]
        return {key: kwargs[key] for key in allowed_fields if kwargs.get(key) is not None}

    async def list_llm_providers(self, auth_token: Optional[str] = None, tenant_id: Optional[int] = None) -> ToolResult:
        """List all LLM providers."""
        try:
            response = await self.http_client.execute(
                command="GET /v2/llm/providers",
                params={},
                auth_token=auth_token or self.auth_token,
                tenant_id=tenant_id or self.tenant_id,
            )
            providers = response.get("providers", []) if isinstance(response, dict) else []
            return ToolResult.success(content=f"Found {len(providers)} LLM providers", data=response)
        except Exception as e:
            logger.error(f"Error listing LLM providers: {e}")
            return ToolResult.error(content=f"Failed to list LLM providers: {str(e)}", error_code="LIST_LLM_PROVIDERS_FAILED")

    async def get_llm_provider(self, name: str, auth_token: Optional[str] = None, tenant_id: Optional[int] = None) -> ToolResult:
        """Get an LLM provider by name."""
        try:
            response = await self.http_client.execute(
                command="GET /v2/llm/providers/{name}",
                params={"path": {"name": name}},
                auth_token=auth_token or self.auth_token,
                tenant_id=tenant_id or self.tenant_id,
            )
            return ToolResult.success(content=f"Retrieved LLM provider {name}", data=response)
        except Exception as e:
            logger.error(f"Error getting LLM provider {name}: {e}")
            return ToolResult.error(content=f"Failed to get LLM provider: {str(e)}", error_code="GET_LLM_PROVIDER_FAILED")

    async def create_llm_provider(
        self,
        name: str,
        type: Optional[str] = None,
        baseUrl: Optional[str] = None,
        model: Optional[str] = None,
        apiKeyRef: Optional[str] = None,
        apiKey: Optional[str] = None,
        enabled: Optional[bool] = None,
        active: Optional[bool] = None,
        priority: Optional[int] = None,
        timeout: Optional[int] = None,
        temperature: Optional[float] = None,
        maxTokens: Optional[int] = None,
        topP: Optional[float] = None,
        costPer1kTokens: Optional[float] = None,
        capabilities: Optional[List[str]] = None,
        contextWindow: Optional[int] = None,
        supportsMultimodal: Optional[bool] = None,
        supportedFormats: Optional[List[str]] = None,
        embeddingDimensions: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
        auth_token: Optional[str] = None,
        tenant_id: Optional[int] = None,
    ) -> ToolResult:
        """Create an LLM provider."""
        try:
            payload = self._build_llm_provider_payload(**locals())
            response = await self.http_client.execute(
                command="POST /v2/llm/providers",
                params={"body": payload},
                auth_token=auth_token or self.auth_token,
                tenant_id=tenant_id or self.tenant_id,
            )
            return ToolResult.success(content=f"Created LLM provider {name}", data=response)
        except Exception as e:
            logger.error(f"Error creating LLM provider {name}: {e}")
            return ToolResult.error(content=f"Failed to create LLM provider: {str(e)}", error_code="CREATE_LLM_PROVIDER_FAILED")

    async def update_llm_provider(
        self,
        name: str,
        type: Optional[str] = None,
        baseUrl: Optional[str] = None,
        model: Optional[str] = None,
        apiKeyRef: Optional[str] = None,
        apiKey: Optional[str] = None,
        enabled: Optional[bool] = None,
        active: Optional[bool] = None,
        priority: Optional[int] = None,
        timeout: Optional[int] = None,
        temperature: Optional[float] = None,
        maxTokens: Optional[int] = None,
        topP: Optional[float] = None,
        costPer1kTokens: Optional[float] = None,
        capabilities: Optional[List[str]] = None,
        contextWindow: Optional[int] = None,
        supportsMultimodal: Optional[bool] = None,
        supportedFormats: Optional[List[str]] = None,
        embeddingDimensions: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
        auth_token: Optional[str] = None,
        tenant_id: Optional[int] = None,
    ) -> ToolResult:
        """Update an LLM provider."""
        try:
            payload = self._build_llm_provider_payload(**locals())
            response = await self.http_client.execute(
                command="PUT /v2/llm/providers/{name}",
                params={"path": {"name": name}, "body": payload},
                auth_token=auth_token or self.auth_token,
                tenant_id=tenant_id or self.tenant_id,
            )
            return ToolResult.success(content=f"Updated LLM provider {name}", data=response)
        except Exception as e:
            logger.error(f"Error updating LLM provider {name}: {e}")
            return ToolResult.error(content=f"Failed to update LLM provider: {str(e)}", error_code="UPDATE_LLM_PROVIDER_FAILED")

    async def delete_llm_provider(self, name: str, auth_token: Optional[str] = None, tenant_id: Optional[int] = None) -> ToolResult:
        """Delete an LLM provider by name."""
        try:
            response = await self.http_client.execute(
                command="DELETE /v2/llm/providers/{name}",
                params={"path": {"name": name}},
                auth_token=auth_token or self.auth_token,
                tenant_id=tenant_id or self.tenant_id,
            )
            return ToolResult.success(content=f"Deleted LLM provider {name}", data=response)
        except Exception as e:
            logger.error(f"Error deleting LLM provider {name}: {e}")
            return ToolResult.error(content=f"Failed to delete LLM provider: {str(e)}", error_code="DELETE_LLM_PROVIDER_FAILED")

    async def set_llm_provider_enabled(self, name: str, enabled: bool, auth_token: Optional[str] = None, tenant_id: Optional[int] = None) -> ToolResult:
        """Enable or disable an LLM provider."""
        try:
            response = await self.http_client.execute(
                command="PATCH /v2/llm/providers/{name}/enabled",
                params={"path": {"name": name}, "body": {"enabled": enabled}},
                auth_token=auth_token or self.auth_token,
                tenant_id=tenant_id or self.tenant_id,
            )
            return ToolResult.success(content=f"Set LLM provider {name} enabled={enabled}", data=response)
        except Exception as e:
            logger.error(f"Error setting LLM provider enabled state for {name}: {e}")
            return ToolResult.error(content=f"Failed to set LLM provider enabled state: {str(e)}", error_code="SET_LLM_PROVIDER_ENABLED_FAILED")

    async def set_active_llm_provider(self, name: str, auth_token: Optional[str] = None, tenant_id: Optional[int] = None) -> ToolResult:
        """Set an LLM provider as active/default."""
        try:
            response = await self.http_client.execute(
                command="PATCH /v2/llm/providers/{name}/active",
                params={"path": {"name": name}},
                auth_token=auth_token or self.auth_token,
                tenant_id=tenant_id or self.tenant_id,
            )
            return ToolResult.success(content=f"Set active LLM provider to {name}", data=response)
        except Exception as e:
            logger.error(f"Error setting active LLM provider {name}: {e}")
            return ToolResult.error(content=f"Failed to set active LLM provider: {str(e)}", error_code="SET_ACTIVE_LLM_PROVIDER_FAILED")

    async def list_llm_usage_configs(self, auth_token: Optional[str] = None, tenant_id: Optional[int] = None) -> ToolResult:
        """List LLM usage configs."""
        try:
            response = await self.http_client.execute(
                command="GET /v2/llm/usage-configs",
                params={},
                auth_token=auth_token or self.auth_token,
                tenant_id=tenant_id or self.tenant_id,
            )
            configs = response.get("configs", []) if isinstance(response, dict) else []
            return ToolResult.success(content=f"Found {len(configs)} LLM usage configs", data=response)
        except Exception as e:
            logger.error(f"Error listing LLM usage configs: {e}")
            return ToolResult.error(content=f"Failed to list LLM usage configs: {str(e)}", error_code="LIST_LLM_USAGE_CONFIGS_FAILED")

    async def upsert_llm_usage_config(
        self,
        purpose: str,
        providerNames: List[str],
        fallbackToEnv: bool = True,
        description: Optional[str] = None,
        auth_token: Optional[str] = None,
        tenant_id: Optional[int] = None,
    ) -> ToolResult:
        """Create or update an LLM usage config."""
        try:
            payload: Dict[str, Any] = {"providerNames": providerNames, "fallbackToEnv": fallbackToEnv}
            if description is not None:
                payload["description"] = description
            response = await self.http_client.execute(
                command="PUT /v2/llm/usage-configs/{purpose}",
                params={"path": {"purpose": purpose}, "body": payload},
                auth_token=auth_token or self.auth_token,
                tenant_id=tenant_id or self.tenant_id,
            )
            return ToolResult.success(content=f"Saved LLM usage config {purpose}", data=response)
        except Exception as e:
            logger.error(f"Error upserting LLM usage config {purpose}: {e}")
            return ToolResult.error(content=f"Failed to upsert LLM usage config: {str(e)}", error_code="UPSERT_LLM_USAGE_CONFIG_FAILED")

    async def delete_llm_usage_config(self, purpose: str, auth_token: Optional[str] = None, tenant_id: Optional[int] = None) -> ToolResult:
        """Delete an LLM usage config."""
        try:
            response = await self.http_client.execute(
                command="DELETE /v2/llm/usage-configs/{purpose}",
                params={"path": {"purpose": purpose}},
                auth_token=auth_token or self.auth_token,
                tenant_id=tenant_id or self.tenant_id,
            )
            return ToolResult.success(content=f"Deleted LLM usage config {purpose}", data=response)
        except Exception as e:
            logger.error(f"Error deleting LLM usage config {purpose}: {e}")
            return ToolResult.error(content=f"Failed to delete LLM usage config: {str(e)}", error_code="DELETE_LLM_USAGE_CONFIG_FAILED")

    async def resolve_llm_usage_config(self, purpose: str, auth_token: Optional[str] = None, tenant_id: Optional[int] = None) -> ToolResult:
        """Preview resolved providers for an LLM usage purpose."""
        try:
            response = await self.http_client.execute(
                command="GET /v2/llm/usage-configs/{purpose}/resolved",
                params={"path": {"purpose": purpose}},
                auth_token=auth_token or self.auth_token,
                tenant_id=tenant_id or self.tenant_id,
            )
            count = response.get("count", 0) if isinstance(response, dict) else 0
            return ToolResult.success(content=f"Resolved {count} providers for LLM usage {purpose}", data=response)
        except Exception as e:
            logger.error(f"Error resolving LLM usage config {purpose}: {e}")
            return ToolResult.error(content=f"Failed to resolve LLM usage config: {str(e)}", error_code="RESOLVE_LLM_USAGE_CONFIG_FAILED")

    async def manage_tenant(
        self,
        action: str,
        tenant_id_param: Optional[int] = None,
        member_id: Optional[int] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        auth_token: Optional[str] = None,
        tenant_id: Optional[int] = None,
    ) -> ToolResult:
        """Root/admin tenant management task tool."""
        try:
            effective_token = auth_token or self.auth_token
            effective_tenant = tenant_id or self.tenant_id or 1
            normalized_action = str(action or "").strip().lower()

            if normalized_action == "list":
                response = await self.http_client.execute(
                    command="GET /v2/tenants",
                    params={"query": {"page": max(1, page), "pageSize": max(1, min(100, page_size))}},
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                tenants = response.get("data", []) if isinstance(response, dict) else []
                return ToolResult.success(content=f"Found {len(tenants)} tenants", data=response)

            if normalized_action == "statistics":
                response = await self.http_client.execute(
                    command="GET /v2/tenants/statistics",
                    params={},
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                total = response.get("totalTenants", "unknown") if isinstance(response, dict) else "unknown"
                return ToolResult.success(content=f"Tenant statistics loaded, totalTenants={total}", data=response)

            if normalized_action == "validate_system_orgs":
                response = await self.http_client.execute(
                    command="GET /v2/tenants/validate-system-organizations",
                    params={},
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                valid = response.get("valid") if isinstance(response, dict) else None
                return ToolResult.success(content=f"System organization validation complete, valid={valid}", data=response)

            if normalized_action == "validate_consistency":
                response = await self.http_client.execute(
                    command="GET /v2/tenants/validate-consistency",
                    params={},
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                consistent = response.get("consistent") if isinstance(response, dict) else None
                return ToolResult.success(content=f"Tenant consistency validation complete, consistent={consistent}", data=response)

            if normalized_action in {"get", "update", "activate", "deactivate", "initialize", "add_member", "remove_member"} and tenant_id_param is None:
                return ToolResult.error(content="tenant_id_param is required for this tenant action", error_code="TENANT_ID_REQUIRED")

            if normalized_action == "get":
                response = await self.http_client.execute(
                    command="GET /v2/tenants/{id}",
                    params={"path": {"id": int(tenant_id_param)}},
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                return ToolResult.success(content=f"Loaded tenant {tenant_id_param}", data=response)

            if normalized_action == "create":
                if not name:
                    return ToolResult.error(content="name is required for create tenant", error_code="TENANT_NAME_REQUIRED")
                body = {"name": name}
                if description is not None:
                    body["description"] = description
                response = await self.http_client.execute(
                    command="POST /v2/tenants",
                    params={"body": body},
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                return ToolResult.success(content=f"Created tenant {name}", data=response)

            if normalized_action == "update":
                if name is None and description is None:
                    return ToolResult.error(content="name or description is required for update tenant", error_code="TENANT_UPDATE_FIELDS_REQUIRED")
                body: Dict[str, Any] = {}
                if name is not None:
                    body["name"] = name
                if description is not None:
                    body["description"] = description
                response = await self.http_client.execute(
                    command="PATCH /v2/tenants/{id}",
                    params={"path": {"id": int(tenant_id_param)}, "body": body},
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                return ToolResult.success(content=f"Updated tenant {tenant_id_param}", data=response)

            if normalized_action == "activate":
                response = await self.http_client.execute(
                    command="POST /v2/tenants/{id}/activate",
                    params={"path": {"id": int(tenant_id_param)}},
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                return ToolResult.success(content=f"Activated tenant {tenant_id_param}", data=response)

            if normalized_action == "deactivate":
                response = await self.http_client.execute(
                    command="POST /v2/tenants/{id}/deactivate",
                    params={"path": {"id": int(tenant_id_param)}},
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                return ToolResult.success(content=f"Deactivated tenant {tenant_id_param}", data=response)

            if normalized_action == "initialize":
                response = await self.http_client.execute(
                    command="POST /v2/tenants/{tenantId}/initialize",
                    params={"path": {"tenantId": int(tenant_id_param)}},
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                status = response.get("status") if isinstance(response, dict) else "unknown"
                return ToolResult.success(content=f"Initialized tenant {tenant_id_param}, status={status}", data=response)

            if normalized_action in {"add_member", "remove_member"} and member_id is None:
                return ToolResult.error(content="member_id is required for tenant member actions", error_code="MEMBER_ID_REQUIRED")

            if normalized_action == "add_member":
                response = await self.http_client.execute(
                    command="POST /v2/tenants/{tenantId}/members/{memberId}",
                    params={"path": {"tenantId": int(tenant_id_param), "memberId": int(member_id)}},
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                return ToolResult.success(content=f"Added member {member_id} to tenant {tenant_id_param}", data=response)

            if normalized_action == "remove_member":
                response = await self.http_client.execute(
                    command="DELETE /v2/tenants/{tenantId}/members/{memberId}",
                    params={"path": {"tenantId": int(tenant_id_param), "memberId": int(member_id)}},
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                return ToolResult.success(content=f"Removed member {member_id} from tenant {tenant_id_param}", data=response)

            return ToolResult.error(content=f"Unsupported tenant action: {action}", error_code="UNSUPPORTED_TENANT_ACTION")
        except Exception as e:
            logger.error(f"Error managing tenant action={action}: {e}")
            return ToolResult.error(content=f"Failed to manage tenant: {str(e)}", error_code="MANAGE_TENANT_FAILED")

    async def manage_agent(
        self,
        action: str,
        agent_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
        agent_type: Optional[str] = None,
        owner_id: Optional[int] = None,
        credential_type: Optional[str] = None,
        expires_at: Optional[str] = None,
        scope_json: Optional[Dict[str, Any]] = None,
        policy: Optional[Dict[str, Any]] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        status: Optional[str] = None,
        auth_token: Optional[str] = None,
        tenant_id: Optional[int] = None,
    ) -> ToolResult:
        """Root/admin agent management task tool."""
        try:
            effective_token = auth_token or self.auth_token
            effective_tenant = tenant_id or self.tenant_id or 1
            normalized_action = str(action or "").strip().lower()

            if normalized_action == "list":
                query: Dict[str, Any] = {"page": max(1, page), "pageSize": max(1, min(100, page_size))}
                if agent_type:
                    query["agent_type"] = agent_type
                if owner_id is not None:
                    query["owner_id"] = owner_id
                response = await self.http_client.execute(
                    command="GET /v2/agents",
                    params={"query": query},
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                agents = response.get("data", []) if isinstance(response, dict) else []
                return ToolResult.success(content=f"Found {len(agents)} agents", data=response)

            if agent_id is None:
                return ToolResult.error(content="agent_id is required for this agent action", error_code="AGENT_ID_REQUIRED")

            if normalized_action == "get_credentials":
                response = await self.http_client.execute(
                    command="GET /v2/agents/{id}/credentials",
                    params={"path": {"id": int(agent_id)}},
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                count = len(response) if isinstance(response, list) else len(response.get("data", []))
                return ToolResult.success(content=f"Loaded {count} credentials for agent {agent_id}", data=response)

            if normalized_action == "create_credentials":
                if not credential_type:
                    return ToolResult.error(content="credential_type is required for create_credentials", error_code="CREDENTIAL_TYPE_REQUIRED")
                body: Dict[str, Any] = {"type": credential_type}
                if expires_at is not None:
                    body["expires_at"] = expires_at
                if scope_json is not None:
                    body["scope_json"] = scope_json
                response = await self.http_client.execute(
                    command="POST /v2/agents/{id}/credentials",
                    params={"path": {"id": int(agent_id)}, "body": body},
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                return ToolResult.success(content=f"Created {credential_type} credential for agent {agent_id}", data=response)

            if normalized_action == "get_policy":
                response = await self.http_client.execute(
                    command="GET /v2/agents/{id}/policy",
                    params={"path": {"id": int(agent_id)}},
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                return ToolResult.success(content=f"Loaded policy for agent {agent_id}", data=response)

            if normalized_action == "update_policy":
                if not policy:
                    return ToolResult.error(content="policy is required for update_policy", error_code="POLICY_REQUIRED")
                response = await self.http_client.execute(
                    command="PUT /v2/agents/{id}/policy",
                    params={"path": {"id": int(agent_id)}, "body": policy},
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                return ToolResult.success(content=f"Updated policy for agent {agent_id}", data=response)

            if normalized_action == "get_logs":
                query = {"page": max(1, page), "pageSize": max(1, min(100, page_size))}
                if start_time:
                    query["start_time"] = start_time
                if end_time:
                    query["end_time"] = end_time
                if status:
                    query["status"] = status
                response = await self.http_client.execute(
                    command="GET /v2/agents/{id}/logs",
                    params={"path": {"id": int(agent_id)}, "query": query},
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                logs = response.get("data", []) if isinstance(response, dict) else []
                return ToolResult.success(content=f"Loaded {len(logs)} logs for agent {agent_id}", data=response)

            return ToolResult.error(content=f"Unsupported agent action: {action}", error_code="UNSUPPORTED_AGENT_ACTION")
        except Exception as e:
            logger.error(f"Error managing agent action={action}: {e}")
            return ToolResult.error(content=f"Failed to manage agent: {str(e)}", error_code="MANAGE_AGENT_FAILED")

    async def manage_settings(
        self,
        action: str,
        org_id: int = 0,
        key: Optional[str] = None,
        value: Optional[str] = None,
        description: Optional[str] = None,
        auth_token: Optional[str] = None,
        tenant_id: Optional[int] = None,
    ) -> ToolResult:
        """Root/admin settings management task tool."""
        try:
            effective_token = auth_token or self.auth_token
            effective_tenant = tenant_id or self.tenant_id or 1
            normalized_action = str(action or "").strip().lower()

            if normalized_action == "list":
                query: Dict[str, Any] = {"org_id": org_id}
                if key:
                    query["key"] = key
                response = await self.http_client.execute(
                    command="GET /v2/settings",
                    params={"query": query},
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                count = len(response) if isinstance(response, list) else len(response.get("data", []))
                return ToolResult.success(content=f"Loaded {count} settings", data=response)

            if not key:
                return ToolResult.error(content="key is required for this settings action", error_code="SETTING_KEY_REQUIRED")

            if normalized_action == "get":
                response = await self.http_client.execute(
                    command="GET /v2/settings/{org_id}/{key}",
                    params={"path": {"org_id": int(org_id), "key": key}},
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                return ToolResult.success(content=f"Loaded setting {key} for org {org_id}", data=response)

            if normalized_action == "upsert":
                if value is None:
                    return ToolResult.error(content="value is required for upsert setting", error_code="SETTING_VALUE_REQUIRED")
                body: Dict[str, Any] = {"org_id": int(org_id), "key": key, "value": value}
                if description is not None:
                    body["description"] = description
                response = await self.http_client.execute(
                    command="POST /v2/settings",
                    params={"body": body},
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                return ToolResult.success(content=f"Saved setting {key} for org {org_id}", data=response)

            if normalized_action == "delete":
                response = await self.http_client.execute(
                    command="DELETE /v2/settings/{org_id}/{key}",
                    params={"path": {"org_id": int(org_id), "key": key}},
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                return ToolResult.success(content=f"Deleted setting {key} for org {org_id}", data=response)

            return ToolResult.error(content=f"Unsupported settings action: {action}", error_code="UNSUPPORTED_SETTINGS_ACTION")
        except Exception as e:
            logger.error(f"Error managing settings action={action}: {e}")
            return ToolResult.error(content=f"Failed to manage settings: {str(e)}", error_code="MANAGE_SETTINGS_FAILED")

    async def query_audit_logs(
        self,
        page: int = 1,
        page_size: int = 20,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        operator_id: Optional[int] = None,
        action_type: Optional[str] = None,
        target_type: Optional[str] = None,
        auth_token: Optional[str] = None,
        tenant_id: Optional[int] = None,
    ) -> ToolResult:
        """Query audit logs."""
        try:
            query: Dict[str, Any] = {"page": max(1, page), "pageSize": max(1, min(100, page_size))}
            if start_time:
                query["start_time"] = start_time
            if end_time:
                query["end_time"] = end_time
            if operator_id is not None:
                query["operator_id"] = operator_id
            if action_type:
                query["action_type"] = action_type
            if target_type:
                query["target_type"] = target_type

            response = await self.http_client.execute(
                command="GET /v2/audit/logs",
                params={"query": query},
                auth_token=auth_token or self.auth_token,
                tenant_id=tenant_id or self.tenant_id or 1,
            )
            logs = response.get("data", []) if isinstance(response, dict) else []
            return ToolResult.success(content=f"Found {len(logs)} audit logs", data=response)
        except Exception as e:
            logger.error(f"Error querying audit logs: {e}")
            return ToolResult.error(content=f"Failed to query audit logs: {str(e)}", error_code="QUERY_AUDIT_LOGS_FAILED")

    async def manage_auth_session(
        self,
        action: str,
        grant_type: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        device_id: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        refresh_token: Optional[str] = None,
        contact: Optional[str] = None,
        channel: Optional[str] = None,
        purpose: Optional[str] = None,
        otp_code: Optional[str] = None,
        otp_token: Optional[str] = None,
        auto_login_token: Optional[str] = None,
        resource: Optional[str] = None,
        permission_action: Optional[str] = None,
        org_id: Optional[int] = None,
        on_behalf_of: Optional[int] = None,
        auth_token: Optional[str] = None,
        tenant_id: Optional[int] = None,
    ) -> ToolResult:
        """Authentication/session management task tool."""
        try:
            effective_token = auth_token or self.auth_token
            effective_tenant = tenant_id or self.tenant_id or 1
            normalized_action = str(action or "").strip().lower()

            if normalized_action == "issue_token":
                if not grant_type:
                    return ToolResult.error(content="grant_type is required for issue_token", error_code="GRANT_TYPE_REQUIRED")
                body: Dict[str, Any] = {"grant_type": grant_type}
                if username is not None:
                    body["username"] = username
                if password is not None:
                    body["password"] = password
                if client_id is not None:
                    body["client_id"] = client_id
                if client_secret is not None:
                    body["client_secret"] = client_secret
                if refresh_token is not None:
                    body["refresh_token"] = refresh_token
                response = await self.http_client.execute(
                    command="POST /v2/auth/token",
                    params={"body": body},
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                return ToolResult.success(content="Issued access token", data=response)

            if normalized_action == "login":
                if not username or not password:
                    return ToolResult.error(content="username and password are required for login", error_code="LOGIN_FIELDS_REQUIRED")
                body = {"username": username, "password": password}
                if device_id is not None:
                    body["device_id"] = device_id
                response = await self.http_client.execute(
                    command="POST /v2/auth/login",
                    params={"body": body},
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                return ToolResult.success(content=f"Login completed for {username}", data=response)

            if normalized_action == "request_otp":
                if not contact or not channel:
                    return ToolResult.error(content="contact and channel are required for request_otp", error_code="OTP_REQUEST_FIELDS_REQUIRED")
                body = {"contact": contact, "channel": channel}
                if purpose is not None:
                    body["purpose"] = purpose
                response = await self.http_client.execute(
                    command="POST /v2/auth/otp-request",
                    params={"body": body},
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                return ToolResult.success(content=f"OTP requested for {contact}", data=response)

            if normalized_action == "otp_login":
                if not contact or not otp_code or not otp_token:
                    return ToolResult.error(content="contact, otp_code, and otp_token are required for otp_login", error_code="OTP_LOGIN_FIELDS_REQUIRED")
                response = await self.http_client.execute(
                    command="POST /v2/auth/otp-login",
                    params={"body": {"contact": contact, "otp_code": otp_code, "otp_token": otp_token}},
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                return ToolResult.success(content=f"OTP login completed for {contact}", data=response)

            if normalized_action == "auto_login":
                if not device_id or not auto_login_token:
                    return ToolResult.error(content="device_id and auto_login_token are required for auto_login", error_code="AUTO_LOGIN_FIELDS_REQUIRED")
                response = await self.http_client.execute(
                    command="POST /v2/auth/auto-login",
                    params={"body": {"device_id": device_id, "auto_login_token": auto_login_token}},
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                return ToolResult.success(content="Auto login completed", data=response)

            if normalized_action == "refresh_token":
                response = await self.http_client.execute(
                    command="POST /v2/auth/token/refresh",
                    params={},
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                return ToolResult.success(content="Refreshed access token", data=response)

            if normalized_action == "check_authz":
                if not resource or not permission_action:
                    return ToolResult.error(content="resource and permission_action are required for check_authz", error_code="AUTHZ_FIELDS_REQUIRED")
                body: Dict[str, Any] = {"resource": resource, "action": permission_action}
                if org_id is not None:
                    body["org_id"] = org_id
                if on_behalf_of is not None:
                    body["on_behalf_of"] = on_behalf_of
                response = await self.http_client.execute(
                    command="POST /v2/authz/check",
                    params={"body": body},
                    auth_token=effective_token,
                    tenant_id=effective_tenant,
                )
                allowed = response.get("allowed") if isinstance(response, dict) else None
                return ToolResult.success(content=f"Authorization checked, allowed={allowed}", data=response)

            return ToolResult.error(content=f"Unsupported auth/session action: {action}", error_code="UNSUPPORTED_AUTH_ACTION")
        except Exception as e:
            logger.error(f"Error managing auth/session action={action}: {e}")
            return ToolResult.error(content=f"Failed to manage auth/session: {str(e)}", error_code="MANAGE_AUTH_SESSION_FAILED")

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

            # Detect language from query for bilingual output
            def _detect_language(text: Optional[str]) -> str:
                if not text:
                    return 'en'
                chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
                return 'zh' if chinese_chars > len(text) * 0.3 else 'en'

            is_zh = _detect_language(query)

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
                    content=f"找到 {len(permissions)} 个直接权限" if is_zh else f"Found {len(permissions)} direct permissions for member {resolved_subject_id}",
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
                    content=f"找到 {len(permissions)} 个直接权限" if is_zh else f"Found {len(permissions)} direct permissions for role {resolved_subject_id}",
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
            org_content = f"组织 {resolved_org_id} 已解析，但组织直接权限查询功能暂不可用" if is_zh else f"Organization {resolved_org_id} was resolved, but direct organization permission lookup is unavailable."
            return ToolResult.success(
                content=org_content,
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
            roles_result = await self.get_member_roles(
                member_id=resolved_member_id,
                org_id=org_id,
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
            member_roles = []
            roles_response: Any = None
            if not roles_result.is_error:
                roles_response = roles_result.data.get("raw")
                member_roles = roles_result.data.get("roles", [])

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

    def _safe_mermaid_label(self, value: Any) -> str:
        text = str(value or "").strip()
        text = text.replace('"', "'").replace("\n", " ").replace("\r", " ")
        return re.sub(r"\s+", " ", text)

    def _org_parent_id(self, org: Dict[str, Any]) -> Optional[int]:
        for key in ("parent_id", "parentId", "parentOrgId"):
            if org.get(key) is not None:
                try:
                    return int(org.get(key))
                except (TypeError, ValueError):
                    return None
        return None

    def _org_active(self, org: Dict[str, Any]) -> bool:
        status = str(org.get("status") or "").strip().lower()
        if status:
            return status in {"active", "enabled", "true"}
        active_value = org.get("active")
        if isinstance(active_value, bool):
            return active_value
        return True

    def _org_mermaid_body(
        self,
        orgs: List[Dict[str, Any]],
        root_org_id: Optional[int],
        include_inactive: bool,
        max_nodes: int,
        direction: str,
    ) -> Dict[str, Any]:
        filtered_orgs = [org for org in orgs if isinstance(org, dict)]
        if not include_inactive:
            filtered_orgs = [org for org in filtered_orgs if self._org_active(org)]

        org_map: Dict[int, Dict[str, Any]] = {}
        children_map: Dict[Optional[int], List[int]] = {}
        for org in filtered_orgs:
            try:
                org_id = int(org.get("id"))
            except (TypeError, ValueError):
                continue
            org_map[org_id] = org
            parent_id = self._org_parent_id(org)
            children_map.setdefault(parent_id, []).append(org_id)

        if root_org_id is not None and root_org_id not in org_map:
            return {"error": f"Organization {root_org_id} not found in chart data"}

        root_candidates: List[int]
        if root_org_id is not None:
            root_candidates = [root_org_id]
        else:
            root_candidates = sorted(children_map.get(None, []))
            if not root_candidates:
                root_candidates = sorted(
                    [org_id for org_id, org in org_map.items() if self._org_parent_id(org) not in org_map]
                )

        visited: set[int] = set()
        ordered_ids: List[int] = []
        edges: List[tuple[int, int]] = []

        def walk(node_id: int) -> None:
            if node_id in visited or len(ordered_ids) >= max_nodes:
                return
            visited.add(node_id)
            ordered_ids.append(node_id)
            for child_id in sorted(children_map.get(node_id, [])):
                if child_id not in org_map or len(ordered_ids) >= max_nodes:
                    continue
                edges.append((node_id, child_id))
                walk(child_id)

        for candidate in root_candidates:
            walk(candidate)
            if len(ordered_ids) >= max_nodes:
                break

        if not ordered_ids:
            return {"error": "No organizations available to render"}

        lines = [f"graph {direction}"]
        for org_id in ordered_ids:
            org = org_map[org_id]
            label_parts = [self._safe_mermaid_label(org.get("name") or f"Org {org_id}")]
            org_type = org.get("type")
            if org_type:
                label_parts.append(f"({self._safe_mermaid_label(org_type)})")
            if not self._org_active(org):
                label_parts.append("[inactive]")
            label = " ".join(label_parts)
            lines.append(f'  org_{org_id}["{label}"]')

        for parent_id, child_id in edges:
            if parent_id in visited and child_id in visited:
                lines.append(f"  org_{parent_id} --> org_{child_id}")

        truncated = len(org_map) > len(ordered_ids)
        if truncated:
            lines.append(f"  truncated_note[\"Showing first {len(ordered_ids)} of {len(org_map)} org nodes\"]")

        return {
            "mermaid": "\n".join(lines),
            "ordered_ids": ordered_ids,
            "truncated": truncated,
            "total_available": len(org_map),
            "displayed": len(ordered_ids),
            "root_org": org_map.get(root_candidates[0]) if root_candidates else None,
        }

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
