from typing import List, Dict, Any, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
import json
import logging
import re
from difflib import SequenceMatcher
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

    async def _get_system_state(self, user_goal: str, tenant_id: int, auth_token: str = None) -> str:
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
                org_result = await self.mcp_registry.execute_command(
                    "membership", "list_orgs", tenant_id=tenant_id, auth_token=auth_token
                )
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
                role_result = await self.mcp_registry.execute_command(
                    "membership", "list_roles", tenant_id=tenant_id, auth_token=auth_token
                )
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
                member_result = await self.mcp_registry.execute_command(
                    "membership", "list_members", tenant_id=tenant_id, auth_token=auth_token
                )
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

    def _extract_orgs_from_membership_result(self, data: Any) -> List[Dict[str, Any]]:
        """Extract organization list from various MCP payload shapes."""
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict):
            if isinstance(data.get("data"), list):
                return [x for x in data.get("data", []) if isinstance(x, dict)]
            if isinstance(data.get("organization"), dict):
                return [data.get("organization")]
            # Some tools may return a single org object directly
            if "id" in data and "name" in data:
                return [data]
        return []

    async def _get_existing_orgs(self, tenant_id: int, auth_token: Optional[str]) -> List[Dict[str, Any]]:
        """Get existing orgs for planner-stage semantic dedup checks."""
        if not self.mcp_registry:
            return []
        try:
            result = await self.mcp_registry.execute_command(
                "membership", "list_orgs", tenant_id=tenant_id, auth_token=auth_token, page=1, limit=200
            )
            if not result.success:
                return []
            return self._extract_orgs_from_membership_result(result.data)
        except Exception as e:
            logger.debug(f"Failed to load existing orgs for planning guard: {e}")
            return []

    def _org_name_semantic_key(self, name: str) -> str:
        if not name:
            return ""
        normalized = re.sub(r"[^a-z0-9\s]", " ", name.lower()).strip()
        normalized = re.sub(r"\s+", " ", normalized)
        stopwords = {"company", "co", "corp", "corporation", "inc", "llc", "ltd", "limited", "the"}
        tokens = [t for t in normalized.split(" ") if t and t not in stopwords]
        return " ".join(tokens)

    def _org_name_similarity(self, a: str, b: str) -> float:
        """Combined similarity for org names (token + character)."""
        a_key = self._org_name_semantic_key(a)
        b_key = self._org_name_semantic_key(b)
        if not a_key or not b_key:
            return 0.0

        a_tokens = set(a_key.split())
        b_tokens = set(b_key.split())
        token_score = 0.0
        if a_tokens and b_tokens:
            inter = len(a_tokens & b_tokens)
            union = len(a_tokens | b_tokens)
            token_score = inter / union if union else 0.0

        char_score = SequenceMatcher(None, a_key, b_key).ratio()
        return max(token_score, char_score)

    def _deep_replace_org_name_in_params(self, value: Any, old_name: str, new_name: str) -> Any:
        """Recursively replace org-name equality filters in JSONPath-like strings."""
        if isinstance(value, str):
            patterns = [
                f"@.name == '{old_name}'",
                f'@.name == "{old_name}"'
            ]
            for pat in patterns:
                if pat in value:
                    value = value.replace(pat, f"@.name == '{new_name}'")
            return value
        if isinstance(value, dict):
            return {k: self._deep_replace_org_name_in_params(v, old_name, new_name) for k, v in value.items()}
        if isinstance(value, list):
            return [self._deep_replace_org_name_in_params(v, old_name, new_name) for v in value]
        return value

    def _looks_like_org_id_jsonpath(self, value: str, org_name: str) -> bool:
        """Detect JSONPath patterns that resolve org id via name filter."""
        if not value.startswith("$.steps[") or not value.strip().endswith(".id"):
            return False
        name_patterns = [
            f"@.name == '{org_name}'",
            f'@.name == "{org_name}"'
        ]
        return any(p in value for p in name_patterns)

    def _deep_replace_org_id_jsonpath(self, value: Any, old_name: str, replacement_jsonpath: str) -> Any:
        """Replace downstream org-id lookups by name with deterministic ID JSONPath."""
        if isinstance(value, str):
            if self._looks_like_org_id_jsonpath(value, old_name):
                return replacement_jsonpath
            return value
        if isinstance(value, dict):
            return {k: self._deep_replace_org_id_jsonpath(v, old_name, replacement_jsonpath) for k, v in value.items()}
        if isinstance(value, list):
            return [self._deep_replace_org_id_jsonpath(v, old_name, replacement_jsonpath) for v in value]
        return value

    def _rewrite_plan_step_reference_to_reused_org_id(self, plan: List[Dict[str, Any]], old_name: str, reused_step_index: int) -> None:
        """Rewrite downstream references to use the reused-org step id directly."""
        replacement_jsonpath = f"$.steps[{reused_step_index}].response.id"
        for idx, step in enumerate(plan):
            if idx <= reused_step_index or not isinstance(step, dict):
                continue
            params = step.get("params")
            if params is not None:
                step["params"] = self._deep_replace_org_id_jsonpath(params, old_name, replacement_jsonpath)

    def _rewrite_plan_name_references(self, plan: List[Dict[str, Any]], old_name: str, new_name: str) -> None:
        """Rewrite downstream JSONPath name references after deterministic org reuse."""
        if old_name == new_name:
            return
        for step in plan:
            if not isinstance(step, dict):
                continue
            params = step.get("params")
            if params is not None:
                step["params"] = self._deep_replace_org_name_in_params(params, old_name, new_name)

    def _apply_org_creation_safeguard(self, plan_data: Dict[str, Any], existing_orgs: List[Dict[str, Any]]) -> Optional[str]:
        """
        Planner-stage safeguard (authoritative):
        - high similarity => MUST reuse existing org (rewrite create->get)
        - medium similarity => MUST ask clarification (no blind create)
        - keep list_orgs wording consistent with reuse decision
        """
        plan = plan_data.get("plan")
        if not isinstance(plan, list) or not plan:
            return None

        reused_any = False

        for step_idx, step in enumerate(plan):
            if not isinstance(step, dict):
                continue
            if step.get("command") != "MCP.membership.create_org":
                continue

            params = step.get("params", {}) if isinstance(step.get("params"), dict) else {}
            org_name = params.get("name")
            force_create = bool(params.get("force_create", False))
            if not isinstance(org_name, str) or not org_name.strip() or force_create:
                continue

            target_parent = params.get("parent_id")

            best = None
            best_score = 0.0
            for org in existing_orgs:
                name = str(org.get("name", ""))
                if not name:
                    continue

                # Parent-aware matching when planner provides parent_id
                if target_parent is not None and org.get("parentId") != target_parent:
                    continue

                score = self._org_name_similarity(org_name, name)
                if score > best_score:
                    best = org
                    best_score = score

            # 1) Deterministic reuse
            if best and best_score >= 0.90:
                matched_name = str(best.get("name", org_name))
                matched_id = str(best.get("id"))
                step["command"] = "MCP.membership.get_org"
                step["params"] = {"org_id": matched_id}
                step["description"] = (
                    f"Reuse existing organization '{matched_name}' (similar to '{org_name}')"
                )
                # Rewrite downstream references to deterministic reused step id first,
                # then normalize residual name-based filters to canonical org name.
                self._rewrite_plan_step_reference_to_reused_org_id(plan, org_name, step_idx)
                self._rewrite_plan_name_references(plan, org_name, matched_name)
                reused_any = True
                continue

            # 2) Ambiguous match -> clarification first
            if best and best_score >= 0.75:
                return (
                    f"发现与 '{org_name}' 高相似的已有组织 '{best.get('name')}'（相似度 {best_score:.2f}）。"
                    "请确认：复用现有组织，还是强制新建？"
                )

        # 3) Eliminate contradictory wording on list step after deterministic reuse
        if reused_any:
            for step in plan:
                if not isinstance(step, dict):
                    continue
                if step.get("command") == "MCP.membership.list_orgs":
                    step["description"] = "List existing organizations to confirm and reuse target organization"

        return None

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
        system_state_info = await self._get_system_state(request.goal, tenant_id, auth_token=auth_token)

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
                temperature=0.0,
                response_format={"type": "json_object"}
            )

            # 4. Parse & Validate
            try:
                plan_data = self._parse_plan_json(llm_response_str)
            except json.JSONDecodeError:
                logger.warning("Primary JSON parse failed; attempting LLM JSON repair")
                try:
                    repaired_response = await self._repair_plan_json_with_llm(llm_response_str)
                    plan_data = self._parse_plan_json(repaired_response)
                except json.JSONDecodeError:
                    logger.warning("JSON repair parse failed; attempting compact re-plan retry")
                    retry_response = await self._retry_compact_plan_with_llm(prompt_messages)
                    plan_data = self._parse_plan_json(retry_response)
            
            # Planner-stage semantic org dedup guard
            existing_orgs = await self._get_existing_orgs(tenant_id, auth_token)
            guard_question = self._apply_org_creation_safeguard(plan_data, existing_orgs)
            if guard_question:
                return TaskPlanResponse(
                    type="clarification_needed",
                    confidence=0.7,
                    question=guard_question
                )

            # Basic Mapping to Pydantic Model (Validation happens here)
            # The LLM is instructed to match the schema of TaskPlanResponse

            # Map risk_assessment if present and valid
            risk_assessment = None
            raw_risk = plan_data.get("risk_assessment") if isinstance(plan_data, dict) else None
            if isinstance(raw_risk, dict):
                risk_assessment = RiskAssessment(**raw_risk)

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

    def _clean_llm_json_response(self, raw_response: str) -> str:
        """Normalize LLM output and try to extract a JSON object string."""
        cleaned = raw_response.strip()

        # Remove markdown code fences if present
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            if len(lines) >= 3:
                cleaned = "\n".join(lines[1:-1]).strip()

        return cleaned

    def _extract_balanced_json_object(self, text: str) -> Optional[str]:
        """Extract first balanced JSON object from arbitrary text."""
        start = text.find("{")
        if start == -1:
            return None

        depth = 0
        in_string = False
        escaped = False

        for i in range(start, len(text)):
            ch = text[i]

            if escaped:
                escaped = False
                continue

            if ch == "\\":
                escaped = True
                continue

            if ch == '"':
                in_string = not in_string
                continue

            if in_string:
                continue

            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]

        return None

    def _parse_plan_json(self, raw_response: str) -> Dict[str, Any]:
        """Parse LLM response as JSON with lightweight recovery."""
        cleaned = self._clean_llm_json_response(raw_response)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as first_err:
            # Try extracting a balanced JSON object from mixed content
            extracted = self._extract_balanced_json_object(cleaned)
            if extracted:
                try:
                    logger.warning("Retrying JSON parse using extracted balanced object")
                    return json.loads(extracted)
                except json.JSONDecodeError:
                    pass

            raise first_err

    async def _repair_plan_json_with_llm(self, raw_response: str) -> str:
        """Ask LLM to repair malformed plan JSON and return JSON-only text."""
        repair_messages = [
            {
                "role": "system",
                "content": (
                    "You are a strict JSON repair assistant. "
                    "Fix malformed JSON and return only ONE valid JSON object. "
                    "Do not add explanations or markdown fences."
                )
            },
            {
                "role": "user",
                "content": (
                    "Repair the following malformed JSON so it is syntactically valid and preserves intent. "
                    "Output must be a single JSON object with keys: confidence, plan, question, risk_assessment.\n\n"
                    f"MALFORMED_JSON:\n{raw_response[:8000]}"
                )
            }
        ]

        repaired = await llm_client.generate_response(
            messages=repair_messages,
            temperature=0.0,
            response_format={"type": "json_object"},
            max_tokens=2500
        )
        return repaired

    async def _retry_compact_plan_with_llm(self, original_prompt_messages: List[Dict[str, str]]) -> str:
        """Retry planning with compact JSON-only instruction to avoid truncation."""
        retry_messages = list(original_prompt_messages)
        retry_messages.append({
            "role": "user",
            "content": (
                "Retry with compact output. Return only one valid JSON object, no markdown. "
                "Maximum 20 steps, each description under 80 characters."
            )
        })

        return await llm_client.generate_response(
            messages=retry_messages,
            temperature=0.0,
            response_format={"type": "json_object"},
            max_tokens=2500
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
   - For role/position creation tasks, use `MCP.membership.create_role` (NOT `MCP.membership.create_org`).
   - For organization creation, treat semantically similar names as potential duplicates (e.g., "Joinkey Software" ~ "Joinkey Software Company"). Reuse existing org when likely same; if uncertain, ask a clarification question before creating.
3. **Execution Completeness (Critical)**:
   - If the user asks to CREATE/UPDATE/ASSIGN/DEPLOY/START entities, the plan MUST include those write operations.
   - Read/list/check steps can be used for idempotency and lookup, but MUST be followed by concrete write/execute steps in the same plan.
   - NEVER return a read-only plan when the user's request is clearly an execution task.
4. **Parameter Validation**: Check required parameters carefully.
   - Ask clarification ONLY when a truly required business parameter is missing for execution.
   - Do NOT ask clarification for optional/internal flags if safe defaults exist.
   - If most entities can be executed and only a subset is missing required fields, still produce an executable plan for the resolvable part and put unresolved items in the final verification/check step description.
5. **Parameter Placement**:
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
6. **Default Tenant ID**: Unless the user explicitly mentions a different tenant, ALWAYS use {tenant_id} (as an INTEGER) as the X-Tenant-ID header value.
7. **Dependency Identification**: If a step requires information from a previous step's result:
   - **IMPORTANT**: Use 0-based indexing for steps. Step 1 is steps[0], Step 2 is steps[1], etc.
   - For array results from a previous step (e.g., step 1): Use `$.steps[0].response.body.data[0].fieldName` or `$.steps[0].response.data[0].fieldName`
   - **CRITICAL: When finding a specific item from a list**, use JSONPath filter syntax: `$.steps[0].response.data[?(@.fieldName == 'value')].id`
     - Example: To find member with username='kehongwei' from step 1: `$.steps[0].response.data[?(@.username == 'kehongwei')].id`
     - Example: To find org with name='Engineering' from step 0: `$.steps[0].response.data[?(@.name == 'Engineering')].id`
   - Always use `[?(@.fieldName == 'value')]` syntax when you need to search for a specific item in a list
   - For object results: Use `$.steps[N].response.body.fieldName` or `$.steps[N].response.fieldName`
8. Risk Assessment: Evaluate the plan. If it involves high-risk actions (like DELETE, or commands marked as 'critical'), allow it but flag it in the 'risk_assessment' field.
9. **Clarification Protocol**:
   - If confidence < 0.8 due to missing critical information → Ask a specific question
   - If required business fields are missing for core execution → ask once, concisely
   - Do NOT ask for confirmation to run obvious setup steps when the user has already requested execution
10. Output Format: Respond ONLY with a valid JSON object adhering to the schema below.
11. Keep plan concise: maximum 30 steps, short descriptions, no repeated explanatory text.
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
