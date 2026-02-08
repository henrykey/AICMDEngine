from typing import List, Dict, Any, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
import json
import logging
from src.models.models import TaskRequest, TaskPlanResponse, PlanStep, RiskAssessment
from src.models.command_set import CommandSet
from src.models.command import Command
from src.services.llm_client import llm_client
from src.mcp.registry import MCPRegistry

logger = logging.getLogger(__name__)

class PlanningEngine:
    def __init__(self, db: AsyncIOMotorDatabase, mcp_registry: Optional[MCPRegistry] = None):
        self.db = db
        self.mcp_registry = mcp_registry

    async def get_available_commands(self, tenant_id: int, command_set_names: List[str] = None) -> List[Dict[str, Any]]:
        """
        Fetch commands available for the given tenant and optional command set names.
        """
        query = {"tenant_id": tenant_id}
        if command_set_names:
            # First find the command set IDs
            cs_cursor = self.db["command_sets"].find(
                {"tenant_id": tenant_id, "name": {"$in": command_set_names}},
                {"_id": 1}
            )
            cs_ids = [str(doc["_id"]) async for doc in cs_cursor]
            query["command_set_id"] = {"$in": cs_ids}

        # Fetch commands (limit to prevent memory issues)
        cursor = self.db["commands"].find(query).limit(1000)
        commands = []
        async for doc in cursor:
            # Convert ObjectId to string for JSON serialization if needed, or keep as is
            # For the prompt, we need a clean dictionary representation
            cmd_dict = {
                "command": doc["command"],
                "summary": doc["summary"],
                "description": doc.get("description", ""),
                "parameters": doc.get("parameters", []),
                "riskLevel": doc.get("riskLevel", "normal")
            }
            commands.append(cmd_dict)

        logger.info(f"Loaded {len(commands)} commands for tenant {tenant_id}")
        return commands

    def _get_mcp_commands(self) -> List[Dict[str, Any]]:
        """
        Extract MCP tools as commands for LLM planning.
        Converts MCP tool definitions into command format.
        """
        mcp_commands = []
        
        try:
            # Iterate through all registered MCPs
            for mcp in self.mcp_registry.get_all_mcps():
                tools_info = mcp.get_info()
                tools_list = tools_info.get("tools", [])  # tools is a list, not dict!
                
                # Convert each tool into a command
                for tool_info in tools_list:
                    tool_name = tool_info.get("name", "")
                    
                    # Extract input schema parameters
                    input_schema = tool_info.get("inputSchema", {})
                    properties = input_schema.get("properties", {})
                    required = input_schema.get("required", [])
                    
                    # Build parameters list
                    parameters = []
                    for param_name, param_info in properties.items():
                        param_def = {
                            "name": param_name,
                            "type": param_info.get("type", "string"),
                            "description": param_info.get("description", ""),
                            "required": param_name in required
                        }
                        parameters.append(param_def)
                    
                    # Create command dict
                    cmd_dict = {
                        "command": f"MCP.{mcp.name}.{tool_name}",
                        "summary": tool_info.get("description", ""),
                        "description": f"MCP Tool from {mcp.name} server",
                        "parameters": parameters,
                        "riskLevel": "normal"
                    }
                    mcp_commands.append(cmd_dict)
        
        except Exception as e:
            logger.warning(f"Failed to extract MCP commands: {e}")
        
        logger.info(f"Extracted {len(mcp_commands)} MCP tool commands")
        return mcp_commands

    async def _get_system_state(self, user_goal: str, tenant_id: int) -> str:
        """
        Query system state (orgs, roles, members) using MCP.
        Returns formatted string describing current system state.
        """
        if not self.mcp_registry:
            return "No system state available (MCP not configured)."

        try:
            # Try to get membership MCP and query it
            membership_mcp = self.mcp_registry.get_mcp("membership")
            if not membership_mcp:
                return "Membership MCP not available."

            state_parts = []

            # Query organizations
            try:
                org_result = await self.mcp_registry.execute_command("membership", "list_orgs", tenant_id=tenant_id)
                if org_result.success and org_result.data:
                    orgs = org_result.data if isinstance(org_result.data, list) else [org_result.data]
                    state_parts.append(f"**已存在的组织** ({len(orgs)} 个):")
                    for org in orgs[:10]:  # Limit display
                        name = org.get("name") if isinstance(org, dict) else str(org)
                        state_parts.append(f"  • {name}")
                    if len(orgs) > 10:
                        state_parts.append(f"  ... 及其他 {len(orgs) - 10} 个")
            except Exception as e:
                logger.debug(f"Failed to query organizations: {e}")

            # Query roles
            try:
                role_result = await self.mcp_registry.execute_command("membership", "list_roles", tenant_id=tenant_id)
                if role_result.success and role_result.data:
                    roles = role_result.data if isinstance(role_result.data, list) else [role_result.data]
                    state_parts.append(f"\n**已存在的岗位** ({len(roles)} 个):")
                    for role in roles[:10]:
                        name = role.get("name") if isinstance(role, dict) else str(role)
                        state_parts.append(f"  • {name}")
                    if len(roles) > 10:
                        state_parts.append(f"  ... 及其他 {len(roles) - 10} 个")
            except Exception as e:
                logger.debug(f"Failed to query roles: {e}")

            # Query members
            try:
                member_result = await self.mcp_registry.execute_command("membership", "list_members", tenant_id=tenant_id)
                if member_result.success and member_result.data:
                    members = member_result.data if isinstance(member_result.data, list) else [member_result.data]
                    state_parts.append(f"\n**已存在的成员** ({len(members)} 个):")
                    for member in members[:7]:
                        name = member.get("full_name") or member.get("username") if isinstance(member, dict) else str(member)
                        email = member.get("email") if isinstance(member, dict) else ""
                        state_parts.append(f"  • {name} ({email})")
                    if len(members) > 7:
                        state_parts.append(f"  ... 及其他 {len(members) - 7} 个")
            except Exception as e:
                logger.debug(f"Failed to query members: {e}")

            return "\n".join(state_parts) if state_parts else "System state: empty or unavailable."

        except Exception as e:
            logger.warning(f"Failed to get system state: {e}")
            return "Failed to retrieve system state."

    async def plan_task(self, request: TaskRequest, tenant_id: int, user_id: str = None, auth_token: str = None) -> TaskPlanResponse:
        # 1. Load Knowledge (Commands)
        command_set_names = request.context.command_set_names if request.context else None
        commands = await self.get_available_commands(tenant_id, command_set_names)

        if not commands:
             return TaskPlanResponse(
                type="clarification_needed",
                confidence=0.0,
                question="No available commands found for your tenant/context. Please contact support."
            )
        
        # Add MCP tools to available commands
        if self.mcp_registry:
            mcp_commands = self._get_mcp_commands()
            commands.extend(mcp_commands)

        # 1.5 Query existing data using MCP to provide context
        system_state_info = await self._get_system_state(request.goal, tenant_id)

        # 2. Generate Prompt (include tenant_id and conversation history)
        prompt_messages = self._build_prompt(
            request.goal, 
            commands, 
            tenant_id,
            request.conversation_history,
            system_state_info
        )

        # 3. AI Planning
        try:
            # We enforce JSON output strictly via prompt instructions
            llm_response_str = await llm_client.generate_response(
                messages=prompt_messages,
                temperature=0.0
            )
            
            # 4. Parse & Validate
            cleaned_response = llm_response_str.strip()
            if cleaned_response.startswith("```"):
                # Remove first line (```json or ```) and last line (```)
                lines = cleaned_response.split("\n")
                if len(lines) >= 3:
                     cleaned_response = "\n".join(lines[1:-1])
            
            plan_data = json.loads(cleaned_response)
            
            # Basic Mapping to Pydantic Model (Validation happens here)
            # The LLM is instructed to match the schema of TaskPlanResponse
            
            # Map risk_assessment if present
            risk_assessment = None
            if "risk_assessment" in plan_data:
                 risk_assessment = RiskAssessment(**plan_data["risk_assessment"])

            # Map plan steps
            steps = []
            if "plan" in plan_data and plan_data["plan"]:
                for s in plan_data["plan"]:
                    steps.append(PlanStep(**s))

            response = TaskPlanResponse(
                type="plan_ready" if steps else "clarification_needed", 
                confidence=plan_data.get("confidence", 0.0),
                plan=steps,
                question=plan_data.get("question"),
                risk_assessment=risk_assessment
            )

            # TODO: 5. Security/Risk Check (Programmatic Fallback) 
            # (We could iterate over steps and check the 'riskLevel' of the mapped command in DB vs the plan)

            return response

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            return TaskPlanResponse(
                type="clarification_needed",
                confidence=0.0,
                question="The system failed to generate a valid plan (JSON Error). Please try rephrasing."
            )
        except Exception as e:
            logger.error(f"Planning failed unexpectedly: {e}", exc_info=True)
            return TaskPlanResponse(
                type="clarification_needed",
                confidence=0.0,
                question=f"An internal error occurred: {str(e)}"
            )

    def _build_prompt(self, user_goal: str, commands: List[Dict[str, Any]], tenant_id: int, conversation_history: List = None, system_state_info: str = None) -> list[Dict[str, str]]:
        commands_json = json.dumps(commands, indent=2, ensure_ascii=False)

        system_prompt = f"""
# ROLE
You are an expert AI Task Planner (NL-TPS). Your goal is to convert a user's high-level objective into a precise, step-by-step execution plan based on a given set of available commands.

# USER CONTEXT
Current User's Tenant ID: {tenant_id}

# CURRENT SYSTEM STATE
{system_state_info if system_state_info else "No system data available."}

# COMMANDS
Here are the available commands you can use. Commands starting with "MCP." are preferred as they provide better functionality.
Each command is either an API endpoint or an MCP tool.

**IMPORTANT: When available, always prefer MCP commands (those starting with "MCP.") over regular API endpoints, as they provide better integration and data transformation.**

{commands_json}

# INSTRUCTIONS
1. Decomposition: Break down the user's objective into a sequence of logical steps.
2. Command Mapping: For each step, find the most appropriate command from the available COMMANDS.
   - **PRIORITY: Always check for MCP commands first (commands starting with "MCP."), as they are preferred.**
   - For example, if you see both "GET /v2/orgs/{id}/hierarchy" and "MCP.membership.get_org_hierarchy", always choose the MCP version.
3. **Parameter Validation**: Check if ALL required parameters can be extracted from the user's input.
   - If ANY required parameter (like username, password, email, etc.) is MISSING or UNCLEAR, you MUST ask a clarifying question.
   - DO NOT generate a plan with incomplete parameters.
   - DO NOT assume default values for critical business parameters.
4. **Parameter Placement**:
   - For MCP commands: Put ALL parameters directly in the "params" object (flattened structure, NOT nested in body/query/path)
     - Example for MCP.membership.update_member_password:
     ```json
     "params": {{"member_id": "$.steps[0].response.data[?(@.username == 'kehongwei')].id", "password": "khwkhw60"}}
     ```
   - For API endpoints:
     - Headers (like X-Tenant-ID): Put in "headers" object
     - Query parameters: Put in "query" object
     - Path parameters (like {{id}}): Put in "path" object
     - Request body fields: Put in "body" object
   - API Example:
     ```json
     "params": {{
       "headers": {{ "X-Tenant-ID": {tenant_id} }},
       "body": {{ "username": "alice", "email": "alice@example.com" }}
     }}
     ```
5. **Default Tenant ID**: Unless the user explicitly mentions a different tenant, ALWAYS use {tenant_id} (as an INTEGER) as the X-Tenant-ID header value.
6. **Dependency Identification**: If a step requires information from a previous step's result:
   - **IMPORTANT**: Use 0-based indexing for steps. Step 1 is steps[0], Step 2 is steps[1], etc.
   - For array results from a previous step (e.g., step 1): Use `$.steps[0].response.body.data[0].fieldName` or `$.steps[0].response.data[0].fieldName`
   - **CRITICAL: When finding a specific item from a list**, use JSONPath filter syntax: `$.steps[0].response.data[?(@.fieldName == 'value')].id`
     - Example: To find member with username='kehongwei' from step 1: `$.steps[0].response.data[?(@.username == 'kehongwei')].id`
     - Example: To find org with name='Engineering' from step 0: `$.steps[0].response.data[?(@.name == 'Engineering')].id`
   - Always use `[?(@.fieldName == 'value')]` syntax when you need to search for a specific item in a list
   - For object results: Use `$.steps[N].response.body.fieldName` or `$.steps[N].response.fieldName`
7. Risk Assessment: Evaluate the plan. If it involves high-risk actions (like DELETE, or commands marked as 'critical'), allow it but flag it in the 'risk_assessment' field.
8. **Clarification Protocol**:
   - If confidence < 0.8 due to missing information → Ask a specific question
   - If any required parameter is missing → Ask for that parameter
   - Keep questions concise and specific
9. Output Format: Respond ONLY with a valid JSON object adhering to the schema below.

# OUTPUT_SCHEMA
{{
  "confidence": <float 0.0-1.0>,
  "plan": [
    {{
      "step": <integer>,
      "description": "<string>",
      "command": "<command_string>",
      "params": {{ <key>: <value> }}
    }}
  ],
  "question": "<string or null>",
  "risk_assessment": {{
      "level": "normal" | "high" | "critical",
      "message": "<string>"
  }}
}}

**IMPORTANT**:
- If you set "question", then "plan" MUST be null or empty array.
- If you set "plan", then "question" MUST be null.
- Never generate both a plan AND a question in the same response.
"""
        
        # Build messages list
        messages = [{"role": "system", "content": system_prompt}]
        
        # Add conversation history if available
        if conversation_history:
            for msg in conversation_history:
                messages.append({
                    "role": msg.role,
                    "content": msg.content
                })
        
        # Add current user goal
        messages.append({"role": "user", "content": f'User objective: "{user_goal}"'})
        
        return messages
