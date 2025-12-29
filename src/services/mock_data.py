
from typing import List, Dict, Any
import requests

def get_membership_commands() -> List[Dict[str, Any]]:
    """
    Returns a list of commands based on the Membership Service API.
    """
    return [
        {
            "command": "CREATE_MEMBER",
            "summary": "Create a new member (human or virtual/agent)",
            "description": "Register a new user or agent in the system. Use 'isVirtual=True' for agents.",
            "parameters": {
                "username": "string (required)",
                "password": "string (required, password123 default)",
                "fullName": "string",
                "email": "string (required)",
                "isVirtual": "boolean (default False)",
                "agentType": "string (optional, e.g. 'workflow')"
            },
            "riskLevel": "high"
        },
        {
            "command": "ASSIGN_MEMBER_TO_ORG",
            "summary": "Add member to an organization/department",
            "description": "Assigns a member to a specific organization unit with a job title.",
            "parameters": {
                "member_id": "integer (required)",
                "org_id": "integer (required)",
                "title": "string",
                "is_primary": "boolean"
            },
            "riskLevel": "normal"
        },
        {
            "command": "ASSIGN_ROLE_TO_MEMBER",
            "summary": "Grant a role to a member",
            "description": "Assigns a role (which contains permissions) to a member.",
            "parameters": {
                "member_id": "integer (required)",
                "role_id": "integer (required)",
                "expires_at": "string (datetime, optional)"
            },
            "riskLevel": "high"
        },
        {
            "command": "GRANT_PERMISSION_DIRECTLY",
            "summary": "Grant specific permission (permit) to a member",
            "description": "Directly assigns a permission code to a member, bypassing roles.",
            "parameters": {
                "member_id": "integer (required)",
                "permission_code": "string (required)",
                 "resource_code": "string (required)",
                 "action_code": "string (required)"
            },
            "riskLevel": "critical"
        }
    ]
