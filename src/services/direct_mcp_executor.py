import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from src.models.models import DirectResult, RetrievalDiagnostics, TaskPlanResponse
from src.mcp.registry import MCPRegistry
from src.services.command_retriever import CommandRetriever
from src.services.llm_client import llm_client

logger = logging.getLogger(__name__)


class DirectMCPExecutor:
    """Attempt a single-tool MCP execution directly from the task entrypoint."""

    def __init__(self, command_retriever: CommandRetriever, mcp_registry: MCPRegistry):
        self.command_retriever = command_retriever
        self.mcp_registry = mcp_registry

    def _parse_mcp_command(self, command: str) -> Tuple[Optional[str], Optional[str]]:
        if not command.startswith("MCP."):
            return None, None
        parts = command.split(".")
        if len(parts) != 3:
            return None, None
        return parts[1], parts[2]

    def _get_tool_schema(self, server_name: str, tool_name: str) -> Optional[Dict[str, Any]]:
        tool_info = self.mcp_registry.get_tool_info(server_name, tool_name)
        if not tool_info:
            return None
        return tool_info.get("input_schema") or tool_info.get("inputSchema")

    def _is_safe_for_direct_execution(
        self,
        command: Dict[str, Any],
        tool_schema: Dict[str, Any],
    ) -> bool:
        risk_level = str(command.get("riskLevel", "normal")).lower()
        if risk_level in {"high", "critical"}:
            return False

        properties = tool_schema.get("properties", {}) if isinstance(tool_schema, dict) else {}
        required = [
            param for param in tool_schema.get("required", [])
            if param not in {"auth_token", "tenant_id"}
        ]
        if len(required) > 3:
            return False

        for param in required:
            param_schema = properties.get(param, {}) if isinstance(properties, dict) else {}
            param_type = str(param_schema.get("type", "string"))
            if param_type in {"object", "array"}:
                return False

        return True

    def _coerce_value(self, value: Any, schema: Dict[str, Any]) -> Any:
        if value is None or not isinstance(schema, dict):
            return value

        param_type = schema.get("type")
        if param_type == "integer":
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.strip():
                return int(value)
        if param_type == "number":
            if isinstance(value, (int, float)):
                return value
            if isinstance(value, str) and value.strip():
                return float(value)
        if param_type == "boolean":
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in {"true", "yes", "1"}:
                    return True
                if lowered in {"false", "no", "0"}:
                    return False
        return value

    def _sanitize_params(self, params: Dict[str, Any], tool_schema: Dict[str, Any]) -> Dict[str, Any]:
        properties = tool_schema.get("properties", {}) if isinstance(tool_schema, dict) else {}
        sanitized: Dict[str, Any] = {}
        for key, value in params.items():
            if key not in properties:
                continue
            try:
                sanitized[key] = self._coerce_value(value, properties.get(key, {}))
            except Exception:
                sanitized[key] = value
        return sanitized

    def _missing_required_params(self, params: Dict[str, Any], tool_schema: Dict[str, Any]) -> List[str]:
        required = [
            param for param in tool_schema.get("required", [])
            if param not in {"auth_token", "tenant_id"}
        ]
        missing = []
        for param in required:
            value = params.get(param)
            if value is None:
                missing.append(param)
            elif isinstance(value, str) and not value.strip():
                missing.append(param)
        return missing

    async def _extract_params(
        self,
        goal: str,
        server_name: str,
        tool_name: str,
        command: Dict[str, Any],
    ) -> Dict[str, Any]:
        tool_schema = self._get_tool_schema(server_name, tool_name) or {}
        properties = tool_schema.get("properties", {})
        required = [
            param for param in tool_schema.get("required", [])
            if param not in {"auth_token", "tenant_id"}
        ]

        extraction_prompt = [
            {
                "role": "system",
                "content": (
                    "You extract parameters for one MCP tool. "
                    "Return only valid JSON with keys confidence, params, question. "
                    "Use null question if enough information is present. "
                    "Do not invent values when the goal does not imply them."
                )
            },
            {
                "role": "user",
                "content": (
                    f"User goal: {goal}\n"
                    f"Tool: MCP.{server_name}.{tool_name}\n"
                    f"Summary: {command.get('summary', '')}\n"
                    f"Description: {command.get('description', '')}\n"
                    f"Required params: {json.dumps(required, ensure_ascii=False)}\n"
                    f"Tool schema properties: {json.dumps(properties, ensure_ascii=False)}\n\n"
                    "Return JSON:\n"
                    "{\n"
                    '  "confidence": 0.0,\n'
                    '  "params": {},\n'
                    '  "question": null\n'
                    "}"
                )
            }
        ]

        response = await llm_client.generate_response(
            messages=extraction_prompt,
            temperature=0.0,
            response_format={"type": "json_object"},
            max_tokens=800,
        )
        parsed = json.loads(response)
        return parsed

    async def try_execute(
        self,
        goal: str,
        tenant_id: int,
        auth_token: Optional[str],
        user_id: Optional[str] = None,
        candidate_limit: Optional[int] = None,
        preferred_mcp_servers: Optional[List[str]] = None,
        requested_mode: str = "mcp",
    ) -> Optional[TaskPlanResponse]:
        retrieval = await self.command_retriever.retrieve(
            goal=goal,
            tenant_id=tenant_id,
            candidate_limit=candidate_limit,
            source_types=["mcp_tool"],
            source_names=preferred_mcp_servers,
            user_id=user_id,
            auth_token=auth_token,
        )
        candidates = retrieval.get("prompt_candidates", [])
        diagnostics_data = retrieval.get("diagnostics", {})
        diagnostics_data.update({
            "requested_mode": requested_mode,
            "resolved_mode": "mcp",
            "system_state_loaded": False,
        })

        if not candidates:
            return None

        top_candidate = candidates[0]
        command_name = str(top_candidate.get("command", ""))
        server_name, tool_name = self._parse_mcp_command(command_name)
        if not server_name or not tool_name:
            return None

        tool_schema = self._get_tool_schema(server_name, tool_name) or {}
        if not self._is_safe_for_direct_execution(top_candidate, tool_schema):
            logger.info("Skipping direct MCP execution for %s due to safety/complexity rules", command_name)
            return None

        try:
            extracted = await self._extract_params(goal, server_name, tool_name, top_candidate)
        except Exception as e:
            logger.warning("Direct MCP param extraction failed for %s: %s", command_name, e)
            return None

        confidence = float(extracted.get("confidence", 0.0) or 0.0)
        raw_params = extracted.get("params", {}) if isinstance(extracted.get("params"), dict) else {}
        params = self._sanitize_params(raw_params, tool_schema)
        question = extracted.get("question")

        if auth_token and "auth_token" not in params:
            params["auth_token"] = auth_token
        if "tenant_id" not in params:
            params["tenant_id"] = tenant_id

        missing_required = self._missing_required_params(params, tool_schema)

        if question:
            return TaskPlanResponse(
                type="clarification_needed",
                confidence=confidence,
                question=str(question),
                resolved_mode="mcp",
                retrieval_diagnostics=RetrievalDiagnostics(**diagnostics_data),
            )

        if missing_required:
            return TaskPlanResponse(
                type="clarification_needed",
                confidence=confidence,
                question=f"Missing required parameters for direct MCP execution: {', '.join(missing_required)}",
                resolved_mode="mcp",
                retrieval_diagnostics=RetrievalDiagnostics(**diagnostics_data),
            )

        if confidence < 0.75:
            return None

        result = await self.mcp_registry.execute_command(
            mcp_name=server_name,
            tool_name=tool_name,
            **params
        )
        if result.is_error:
            logger.warning("Direct MCP execution failed for %s: %s", command_name, result.content)
            return None

        return TaskPlanResponse(
            type="direct_result",
            confidence=confidence,
            resolved_mode="mcp",
            retrieval_diagnostics=RetrievalDiagnostics(**diagnostics_data),
            direct_result=DirectResult(
                serverName=server_name,
                toolName=tool_name,
                params=params,
                content=result.content,
                data=result.data or {},
            )
        )
