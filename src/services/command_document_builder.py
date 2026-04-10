from datetime import datetime
from typing import Any, Dict, List, Optional
import re


class CommandDocumentBuilder:
    """Build normalized retrieval documents for Mongo commands and MCP tools."""

    @staticmethod
    def _slugify(value: str) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9]+", "-", (value or "").strip().lower()).strip("-")
        return normalized or "default"

    @staticmethod
    def _normalize_parameter_names(parameters: Any) -> List[str]:
        if isinstance(parameters, list):
            result = []
            for item in parameters:
                if isinstance(item, dict) and item.get("name"):
                    result.append(str(item["name"]))
            return result

        if isinstance(parameters, dict):
            names: List[str] = []
            for section in ("body", "query", "path", "headers", "pathParams", "queryParams"):
                value = parameters.get(section)
                if isinstance(value, dict):
                    names.extend(str(k) for k in value.keys())
            return names

        return []

    @staticmethod
    def _normalize_parameter_descriptions(parameters: Any) -> List[str]:
        if not isinstance(parameters, list):
            return []

        result = []
        for item in parameters:
            if isinstance(item, dict):
                description = item.get("description")
                name = item.get("name")
                if description and name:
                    result.append(f"{name}: {description}")
                elif description:
                    result.append(str(description))
        return result

    @staticmethod
    def _build_retrieval_text(
        command: str,
        source_type: str,
        source_name: str,
        summary: str,
        description: str,
        tags: List[str],
        examples: List[str],
        parameter_names: List[str],
        parameter_descriptions: List[str],
        risk_level: str,
    ) -> str:
        parts = [
            f"Command: {command}",
            f"Source Type: {source_type}",
            f"Source Name: {source_name}",
            f"Summary: {summary or ''}",
            f"Description: {description or ''}",
            f"Tags: {', '.join(tags) if tags else ''}",
            f"Examples: {', '.join(examples) if examples else ''}",
            f"Parameter Names: {', '.join(parameter_names) if parameter_names else ''}",
            f"Parameter Descriptions: {', '.join(parameter_descriptions) if parameter_descriptions else ''}",
            f"Risk Level: {risk_level or 'normal'}",
        ]
        return "\n".join(parts)

    def build_from_command(
        self,
        command_doc: Dict[str, Any],
        source_name: str,
        index_version: str,
        embedding_metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        parameters = command_doc.get("parameters", [])
        tags = [str(tag) for tag in command_doc.get("tags", []) if tag is not None]
        examples = [str(example) for example in command_doc.get("examples", []) if example is not None]
        parameter_names = self._normalize_parameter_names(parameters)
        parameter_descriptions = self._normalize_parameter_descriptions(parameters)
        risk_level = str(command_doc.get("riskLevel", command_doc.get("risk_level", "normal")))
        doc_id = f"command:{command_doc.get('tenant_id', 0)}:{command_doc.get('_id', command_doc.get('command'))}"

        return {
            "doc_id": doc_id,
            "tenant_id": int(command_doc.get("tenant_id", 0)),
            "source_type": "command",
            "source_name": source_name,
            "command": command_doc.get("command", ""),
            "summary": command_doc.get("summary", ""),
            "description": command_doc.get("description", ""),
            "tags": tags,
            "examples": examples,
            "parameters": parameters,
            "parameter_names": parameter_names,
            "parameter_descriptions": parameter_descriptions,
            "risk_level": risk_level,
            "retrieval_text": self._build_retrieval_text(
                command=command_doc.get("command", ""),
                source_type="command",
                source_name=source_name,
                summary=command_doc.get("summary", ""),
                description=command_doc.get("description", ""),
                tags=tags,
                examples=examples,
                parameter_names=parameter_names,
                parameter_descriptions=parameter_descriptions,
                risk_level=risk_level,
            ),
            "embedding_provider": embedding_metadata.get("provider"),
            "embedding_model": embedding_metadata.get("model"),
            "embedding_dimensions": embedding_metadata.get("dimensions"),
            "index_version": index_version,
            "updated_at": datetime.utcnow().isoformat(),
        }

    def build_from_mcp_tool(
        self,
        mcp_name: str,
        tool_info: Dict[str, Any],
        index_version: str,
        embedding_metadata: Dict[str, Any],
        tenant_id: int = 0,
    ) -> Dict[str, Any]:
        input_schema = tool_info.get("inputSchema", {}) if isinstance(tool_info, dict) else {}
        properties = input_schema.get("properties", {}) if isinstance(input_schema, dict) else {}
        required = set(input_schema.get("required", []) if isinstance(input_schema, dict) else [])

        parameters = []
        parameter_names = []
        parameter_descriptions = []
        for param_name, param_info in properties.items():
            parameter_names.append(str(param_name))
            description = ""
            if isinstance(param_info, dict):
                description = str(param_info.get("description", ""))
            if description:
                parameter_descriptions.append(f"{param_name}: {description}")
            parameters.append({
                "name": param_name,
                "type": param_info.get("type", "string") if isinstance(param_info, dict) else "string",
                "description": description,
                "required": param_name in required,
            })

        command = f"MCP.{mcp_name}.{tool_info.get('name', '')}"
        summary = str(tool_info.get("description", ""))
        semantic_description = str(tool_info.get("semantic_description", "") or "")
        output_description = str(tool_info.get("output_description", "") or "")
        use_cases = [str(item) for item in tool_info.get("use_cases", []) if str(item).strip()]
        examples = [str(item) for item in tool_info.get("natural_language_examples", []) if str(item).strip()]
        tags = [str(tag) for tag in tool_info.get("tags", []) if str(tag).strip()] or [mcp_name, "mcp"]
        doc_id = f"mcp:{tenant_id}:{mcp_name}:{tool_info.get('name', '')}"
        description = semantic_description or f"MCP Tool from {mcp_name} server"
        combined_parameter_descriptions = list(parameter_descriptions)
        if output_description:
            combined_parameter_descriptions.append(f"Output: {output_description}")
        if use_cases:
            combined_parameter_descriptions.append(f"Use Cases: {'; '.join(use_cases)}")

        return {
            "doc_id": doc_id,
            "tenant_id": tenant_id,
            "source_type": "mcp_tool",
            "source_name": mcp_name,
            "command": command,
            "summary": summary,
            "description": description,
            "tags": tags,
            "examples": examples,
            "parameters": parameters,
            "parameter_names": parameter_names,
            "parameter_descriptions": combined_parameter_descriptions,
            "risk_level": "normal",
            "retrieval_text": self._build_retrieval_text(
                command=command,
                source_type="mcp_tool",
                source_name=mcp_name,
                summary=summary,
                description=description,
                tags=tags,
                examples=examples,
                parameter_names=parameter_names,
                parameter_descriptions=combined_parameter_descriptions,
                risk_level="normal",
            ),
            "embedding_provider": embedding_metadata.get("provider"),
            "embedding_model": embedding_metadata.get("model"),
            "embedding_dimensions": embedding_metadata.get("dimensions"),
            "index_version": index_version,
            "updated_at": datetime.utcnow().isoformat(),
        }

    def build_docintel_document_from_command(
        self,
        command_doc: Dict[str, Any],
        source_name: str,
        category_prefix: str = "cmdengine.command",
    ) -> Dict[str, Any]:
        base_doc = self.build_from_command(
            command_doc=command_doc,
            source_name=source_name,
            index_version="docintel",
            embedding_metadata={},
        )
        return {
            "externalId": base_doc["doc_id"],
            "title": f"COMMAND: {base_doc['command']}",
            "category": f"{category_prefix}.{self._slugify(source_name)}",
            "content": base_doc["retrieval_text"],
            "classification": 3,
            "includeInKb": False,
            "metadata": {
                "entity_type": "command",
                "command_id": str(command_doc.get("_id", "")),
                "command": base_doc["command"],
                "source_type": "command",
                "source_name": source_name,
                "tenant_id": base_doc["tenant_id"],
                "risk_level": base_doc["risk_level"],
                "tags": base_doc["tags"],
                "parameter_names": base_doc["parameter_names"],
                "command_set_id": str(command_doc.get("command_set_id", "")),
            }
        }

    def build_docintel_document_from_mcp_tool(
        self,
        mcp_name: str,
        tool_info: Dict[str, Any],
        category_prefix: str = "cmdengine.command",
        tenant_id: int = 0,
    ) -> Dict[str, Any]:
        base_doc = self.build_from_mcp_tool(
            mcp_name=mcp_name,
            tool_info=tool_info,
            index_version="docintel",
            embedding_metadata={},
            tenant_id=tenant_id,
        )
        return {
            "externalId": base_doc["doc_id"],
            "title": f"MCP: {mcp_name}.{tool_info.get('name', '')}",
            "category": f"{category_prefix}.mcp",
            "content": base_doc["retrieval_text"],
            "classification": 3,
            "includeInKb": False,
            "metadata": {
                "entity_type": "command",
                "command_id": base_doc["doc_id"],
                "command": base_doc["command"],
                "source_type": "mcp_tool",
                "source_name": mcp_name,
                "tenant_id": tenant_id,
                "risk_level": "normal",
                "tags": base_doc["tags"],
                "parameter_names": base_doc["parameter_names"],
                "examples": base_doc["examples"],
                "mcp_server": mcp_name,
                "mcp_tool_name": tool_info.get("name", ""),
            }
        }
