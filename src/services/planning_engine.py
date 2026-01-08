from typing import List, Dict, Any
from motor.motor_asyncio import AsyncIOMotorDatabase
import json
import logging
from src.models.models import TaskRequest, TaskPlanResponse, PlanStep, RiskAssessment
from src.models.command_set import CommandSet
from src.models.command import Command
from src.services.llm_client import llm_client

logger = logging.getLogger(__name__)

class PlanningEngine:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

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
            # Include response schema if available - helps LLM generate correct JSONPath
            if "response_schema" in doc and doc["response_schema"]:
                cmd_dict["responseSchema"] = doc["response_schema"]
            commands.append(cmd_dict)

        logger.info(f"Loaded {len(commands)} commands for tenant {tenant_id}")
        return commands

    async def plan_task(self, request: TaskRequest, tenant_id: int, user_id: str = None) -> TaskPlanResponse:
        # 1. Load Knowledge (Commands)
        command_set_names = request.context.command_set_names if request.context else None
        commands = await self.get_available_commands(tenant_id, command_set_names)

        if not commands:
             return TaskPlanResponse(
                type="clarification_needed",
                confidence=0.0,
                question="No available commands found for your tenant/context. Please contact support."
            )

        # 2. Generate Prompt (include tenant_id and conversation history)
        prompt_messages = self._build_prompt(
            request.goal, 
            commands, 
            tenant_id,
            request.conversation_history
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

    def _build_prompt(self, user_goal: str, commands: List[Dict[str, Any]], tenant_id: int, conversation_history: List = None) -> list[Dict[str, str]]:
        commands_json = json.dumps(commands, indent=2, ensure_ascii=False)

        system_prompt = f"""
# ROLE
You are an expert AI Task Planner (NL-TPS). Your goal is to convert a user's high-level objective into a precise, step-by-step execution plan based on a given set of available commands.

# USER CONTEXT
Current User's Tenant ID: {tenant_id}

# COMMANDS
Here are the available commands you can use. Each command is an API endpoint.
{commands_json}

# INSTRUCTIONS
1. Decomposition: Break down the user's objective into a sequence of logical steps.
2. Command Mapping: For each step, find the most appropriate command from the available COMMANDS.
3. **Parameter Validation**: Check if ALL required parameters can be extracted from the user's input.
   - If ANY required parameter (like username, password, email, etc.) is MISSING or UNCLEAR, you MUST ask a clarifying question.
   - DO NOT generate a plan with incomplete parameters.
   - DO NOT assume default values for critical business parameters.
4. **Parameter Placement**:
   - Headers (like X-Tenant-ID): Put in "headers" object
   - Query parameters: Put in "query" object
   - Path parameters (like {{id}}): Put in "path" object
   - Request body fields: Put in "body" object
   - Example:
     ```json
     "params": {{
       "headers": {{ "X-Tenant-ID": {tenant_id} }},
       "body": {{ "username": "alice", "email": "alice@example.com" }}
     }}
     ```
5. **Default Tenant ID**: Unless the user explicitly mentions a different tenant, ALWAYS use {tenant_id} (as an INTEGER) as the X-Tenant-ID header value.
6. Dependency Identification: If a step requires information from a previous step's result, use JSONPath syntax.
   **IMPORTANT**: Check the command's responseSchema field to understand the response structure:
   - If responseSchema.type == "wrapped" and responseSchema.wrapper == "data":
     * For array items: "$.steps[0].response.data[0].id"
     * For object items: "$.steps[0].response.data.id"
   - If responseSchema.type == "object": "$.steps[0].response.body.id"
   - Always adjust the JSONPath based on the documented response structure, not assumptions.
   The system will dynamically parse responses according to their documented schemas.
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
