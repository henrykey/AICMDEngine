"""
MCP Protocol Handler

Handles JSON-RPC 2.0 messages for Model Context Protocol.
"""

from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


def get_tool_schema_properties(registry: Any, mcp_name: str, tool_name: str) -> Dict[str, Any]:
    """Return JSON schema properties for a registered MCP tool."""
    candidates = []
    if registry and hasattr(registry, "get_tool_info"):
        try:
            tool_info = registry.get_tool_info(mcp_name, tool_name)
            if tool_info:
                candidates.append(tool_info)
        except Exception as exc:
            logger.warning("[%s.%s] failed to read tool schema: %s", mcp_name, tool_name, exc)

    if registry and hasattr(registry, "get_mcp"):
        mcp = registry.get_mcp(mcp_name)
        tools_cache = getattr(mcp, "tools_cache", None) if mcp else None
        if isinstance(tools_cache, dict) and tools_cache.get(tool_name):
            candidates.append(tools_cache[tool_name])
        if mcp and hasattr(mcp, "get_info"):
            info = mcp.get_info() or {}
            tools = info.get("tools", [])
            if isinstance(tools, dict):
                if tools.get(tool_name):
                    candidates.append(tools[tool_name])
            elif isinstance(tools, list):
                for item in tools:
                    if isinstance(item, dict) and item.get("name") == tool_name:
                        candidates.append(item)
                        break

    for tool_info in candidates:
        if not isinstance(tool_info, dict):
            continue
        schema = tool_info.get("inputSchema") or tool_info.get("input_schema") or {}
        if not isinstance(schema, dict):
            continue
        properties = schema.get("properties") or {}
        if isinstance(properties, dict) and properties:
            return properties
    return {}


def choose_vlm_injection_key(properties: Dict[str, Any], args: Dict[str, Any]) -> Optional[str]:
    if "vlm_config" in args or "vlm_defaults" in args:
        return None
    if "vlm_defaults" in properties:
        return "vlm_defaults"
    if "vlm_config" in properties:
        return "vlm_config"
    return None


class MCPMessage:
    """MCP消息模型"""

    def __init__(
        self,
        jsonrpc: str = "2.0",
        id: Optional[Any] = None,
        method: Optional[str] = None,
        params: Optional[dict] = None,
        result: Optional[Any] = None,
        error: Optional[dict] = None
    ):
        """
        Initialize MCP message

        Args:
            jsonrpc: JSON-RPC version (default: "2.0")
            id: Request/Response ID
            method: Method name for requests
            params: Method parameters
            result: Result for responses
            error: Error for error responses
        """
        self.jsonrpc = jsonrpc
        self.id = id
        self.method = method
        self.params = params or {}
        self.result = result
        self.error = error

    def to_dict(self) -> dict:
        """
        转换为字典

        Returns:
            dict: Message as dictionary
        """
        data = {"jsonrpc": self.jsonrpc}

        if self.id is not None:
            data["id"] = self.id

        if self.method:
            data["method"] = self.method
            if self.params:
                data["params"] = self.params

        if self.result is not None:
            data["result"] = self.result

        if self.error:
            data["error"] = self.error

        return data

    @staticmethod
    def from_dict(data: dict) -> 'MCPMessage':
        """
        从字典创建

        Args:
            data: Message dictionary

        Returns:
            MCPMessage: Message object
        """
        return MCPMessage(
            jsonrpc=data.get("jsonrpc", "2.0"),
            id=data.get("id"),
            method=data.get("method"),
            params=data.get("params"),
            result=data.get("result"),
            error=data.get("error")
        )


class MCPProtocolHandler:
    """MCP协议处理器"""

    def __init__(self):
        """Initialize protocol handler"""
        self.supported_methods = {
            "initialize": self._handle_initialize,
            "tools/list": self._handle_tools_list,
            "tools/call": self._handle_tools_call,
            "resources/list": self._handle_resources_list,
            "resources/read": self._handle_resources_read,
            "prompts/list": self._handle_prompts_list,
            "prompts/get": self._handle_prompts_get,
        }

    async def handle_message(
        self,
        message: dict,
        context: dict
    ) -> Optional[dict]:
        """
        处理MCP消息

        Args:
            message: JSON-RPC message
            context: Context info (client_info, registry, etc.)

        Returns:
            dict: JSON-RPC response
        """
        try:
            mcp_msg = MCPMessage.from_dict(message)
        except Exception as e:
            logger.error(f"Failed to parse message: {e}")
            return {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "error": {
                    "code": -32700,
                    "message": "Parse error"
                }
            }

        # 检查方法
        if not mcp_msg.method:
            return {
                "jsonrpc": "2.0",
                "id": mcp_msg.id,
                "error": {
                    "code": -32600,
                    "message": "Invalid Request"
                }
            }

        # 路由到对应的处理器
        handler = self.supported_methods.get(mcp_msg.method)
        if not handler:
            return {
                "jsonrpc": "2.0",
                "id": mcp_msg.id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {mcp_msg.method}"
                }
            }

        # 执行处理器
        try:
            result = await handler(mcp_msg, context)
            return {
                "jsonrpc": "2.0",
                "id": mcp_msg.id,
                "result": result
            }
        except Exception as e:
            logger.error(f"Error handling {mcp_msg.method}: {e}")
            return {
                "jsonrpc": "2.0",
                "id": mcp_msg.id,
                "error": {
                    "code": -32603,
                    "message": "Internal error",
                    "data": str(e)
                }
            }

    async def _handle_initialize(
        self,
        message: MCPMessage,
        context: dict
    ) -> dict:
        """
        处理initialize请求

        Args:
            message: MCP message
            context: Context info

        Returns:
            dict: Server info and capabilities
        """
        params = message.params or {}
        client_info = context.get("client_info", {})

        logger.info(
            f"Initialize handshake from {client_info.get('client_id')}"
        )

        return {
            "protocolVersion": "2024-11-05",
            "serverInfo": {
                "name": "AICMDEngine MCP Router",
                "version": "1.0.0"
            },
            "capabilities": {
                "tools": {},
                "resources": {},
                "prompts": {}
            }
        }

    async def _handle_tools_list(
        self,
        message: MCPMessage,
        context: dict
    ) -> dict:
        """
        处理tools/list请求

        Args:
            message: MCP message
            context: Context info

        Returns:
            dict: List of available tools
        """
        registry = context.get("registry")
        if not registry:
            raise ValueError("Registry not available")

        tools = []
        for mcp in registry.get_all_mcps():
            mcp_info = mcp.get_info()
            tools_list = mcp_info.get("tools", [])

            # tools可能是list或dict
            if isinstance(tools_list, dict):
                tools_list_items = tools_list.items()
            else:
                tools_list_items = [(t.get("name"), t) for t in tools_list]

            for tool_name, tool_info in tools_list_items:
                tools.append({
                    "name": f"{mcp.name}.{tool_name}",
                    "description": tool_info.get("description", ""),
                    "inputSchema": tool_info.get("inputSchema", {})
                })

        logger.info(f"Listed {len(tools)} tools")
        return {"tools": tools}

    async def _handle_tools_call(
        self,
        message: MCPMessage,
        context: dict
    ) -> dict:
        """
        处理tools/call请求

        Args:
            message: MCP message
            context: Context info

        Returns:
            dict: Tool execution result
        """
        registry = context.get("registry")
        if not registry:
            raise ValueError("Registry not available")

        params = message.params or {}
        tool_name = params.get("name")
        arguments = params.get("arguments", {}) or {}

        if not tool_name:
            raise ValueError("Missing tool name")

        # 解析工具名称
        parts = tool_name.split(".", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid tool name format: {tool_name}")

        mcp_name, tool_name = parts

        waiting = (mcp_name == "pdf2md-enhanced" and tool_name == "process_task_page"
                   and arguments.get("routing_config", {}).get("calculation_poll") is True)
        (logger.debug if waiting else logger.info)("Executing tool: %s.%s", mcp_name, tool_name)

        arguments = await self.bind_authenticated_arguments(arguments, context, mcp_name, tool_name)

        # Inject per-MCP model provider configuration for external OCR/VLM MCPs.
        arguments = await self._inject_external_model_configs(
            mcp_name=mcp_name,
            tool_name=tool_name,
            arguments=arguments,
            context=context,
        )

        # 执行工具（传递JWT token和tenant_id）
        try:
            execution_context = {}
            if mcp_name == "model-capabilities":
                from src.mcp_servers.model_capabilities_mcp import CapabilityExecutionContext
                execution_context["execution_context"] = CapabilityExecutionContext(
                    tenant_id=str(context["client_info"]["tenant_id"]), token=context["jwt_token"])
            result = await registry.execute_command(
                mcp_name=mcp_name,
                tool_name=tool_name,
                **execution_context,
                **arguments
            )

            return {
                "content": [{
                    "type": "text",
                    "text": result.content
                }],
                "isError": bool(getattr(result, "is_error", False))
            }

        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            raise

    async def bind_authenticated_arguments(
        self, arguments: dict, context: dict, mcp_name: str, tool_name: str
    ) -> dict:
        """Bind execution identity before processing any caller-supplied metadata."""
        token = context.get("jwt_token")
        tenant = context.get("client_info", {}).get("tenant_id")
        if not isinstance(token, str) or not token.strip():
            raise ValueError("Authenticated token required")
        if isinstance(tenant, bool) or tenant is None or not str(tenant).isdigit() or int(tenant) <= 0:
            raise ValueError("Authenticated tenant required")
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be an object")
        args = dict(arguments)
        if mcp_name == "pdf2md-enhanced":
            for config_key in ("vlm_config", "vlm_defaults"):
                value = args.get(config_key)
                if isinstance(value, dict) and "_router_discovered_thinking" in value:
                    raise ValueError("Reserved Router model parameter")
        if mcp_name == "model-capabilities" and "execution_context" in args:
            raise ValueError("execution_context is reserved")
        if "auth_token" in args and args["auth_token"] != token:
            raise ValueError("auth_token conflicts with authenticated identity")
        for key in ("tenant_id", "_tenant_id"):
            if key in args and (isinstance(args[key], bool) or str(args[key]) != str(tenant)):
                raise ValueError(f"{key} conflicts with authenticated identity")
        args["auth_token"] = token
        args["tenant_id"] = tenant
        if mcp_name == "pdf2md-enhanced" and "source_identity" in args:
            identity = args["source_identity"]
            if not isinstance(identity, dict) or identity.get("tenant_id") != str(tenant):
                raise ValueError("source_identity_tenant_mismatch")
        if mcp_name == "membership" and tool_name == "submit_audit_events_batch":
            events = args.get("events")
            if not isinstance(events, list) or not events or any(
                not isinstance(event, dict) or str(event.get("tenant_id")) != str(tenant)
                or ("tenantId" in event and str(event["tenantId"]) != str(tenant))
                for event in events
            ):
                raise ValueError("Audit event tenant conflicts with authenticated identity")
        system_token = args.pop("system_service_token", None)
        args.pop("_tenant_id", None)
        if system_token:
            # Validate with the authority; decoding unsigned claims cannot authorize caching.
            from src.mcp.auth_jwt import MCPJWTAuth, JWTAuthConfig
            from src.core.config import settings
            auth = MCPJWTAuth(JWTAuthConfig(settings.membership_service_url))
            claims = await auth.validate_token(system_token)
            if (str(claims.get("tenant_id")) != str(tenant)
                    or not str(claims.get("sub", "")).startswith("system-service-")):
                raise ValueError("Invalid audit service identity")
            membership = context["registry"].get_mcp("membership")
            if membership is not None and hasattr(membership, "_audit_system_tokens"):
                membership._audit_system_tokens[tenant] = system_token
        return args

    async def _inject_external_model_configs(
        self,
        mcp_name: str,
        tool_name: str,
        arguments: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Inject VLM and OCR configs for external MCPs from runtime MCP bindings.
        Explicit request args always win over router injection.
        """
        args = dict(arguments or {})
        registry = context.get("registry")
        properties = get_tool_schema_properties(registry, mcp_name, tool_name)
        if not properties:
            return args

        vlm_key = choose_vlm_injection_key(properties, args)
        should_inject_ocr = "ocr_config" in properties and "ocr_config" not in args
        if not vlm_key and not should_inject_ocr:
            return args

        provider_manager = context.get("provider_manager")
        if provider_manager is None:
            logger.warning(f"[{mcp_name}] provider_manager unavailable, skip model injection")
            return args

        if vlm_key:
            provider_name = await self._resolve_mcp_llm_provider(mcp_name, context)
            if provider_name:
                vlm_config = self._build_model_config_from_provider(provider_manager, provider_name, mcp_name, "VLM")
                if vlm_config:
                    query = args.get("query_enhancement")
                    server = (registry.get_mcp("model-capabilities") if registry and mcp_name == "pdf2md-enhanced"
                              and tool_name == "extract_page_tables" and isinstance(query, dict)
                              and query.get("thinking_mode") == "high" else None)
                    runtime = getattr(server, "runtime", None)
                    if runtime and context.get("jwt_token") and context.get("client_info", {}).get("tenant_id"):
                        from src.mcp_servers.model_capabilities_mcp import CapabilityExecutionContext
                        identity = CapabilityExecutionContext(str(context["client_info"]["tenant_id"]), context["jwt_token"])
                        vlm_config = await runtime.apply_table_query(mcp_name, tool_name, args, vlm_config, identity)
                    args[vlm_key] = vlm_config
            else:
                logger.info("[%s.%s] no MCP->LLM binding found; skip VLM injection", mcp_name, tool_name)

        if should_inject_ocr:
            provider_name = await self._resolve_mcp_glm_ocr_provider(mcp_name, context)
            if provider_name:
                glm_ocr_config = self._build_model_config_from_provider(provider_manager, provider_name, mcp_name, "GLM-OCR")
                if glm_ocr_config:
                    glm_ocr_config["enabled"] = True
                    args["ocr_config"] = {"glm_ocr": glm_ocr_config}
            else:
                logger.info("[%s.%s] no MCP->GLM-OCR binding found; skip OCR injection", mcp_name, tool_name)

        return args

    @staticmethod
    def _build_model_config_from_provider(provider_manager: Any, provider_name: str, mcp_name: str, label: str) -> Optional[Dict[str, Any]]:
        provider = provider_manager.get_provider(provider_name)
        if not provider:
            logger.warning(f"[{mcp_name}] provider '{provider_name}' not found, skip {label} injection")
            return None

        api_key = provider_manager.config_loader.get_api_key(provider.api_key_ref) or ""

        return {
            "provider": provider.name,
            "model": provider.model,
            "base_url": provider.base_url,
            "api_key": api_key,
            "timeout_sec": provider.timeout,
            "temperature": provider.temperature,
            "max_tokens": provider.max_tokens,
            "context_window": getattr(provider, "context_window", 4096),
            "dual_output_max_tokens": getattr(provider, "dual_output_max_tokens", 4096),
            "thinking_mode": getattr(provider, "thinking_mode", "default"),
        }

    async def _resolve_mcp_llm_provider(self, mcp_name: str, context: Dict[str, Any]) -> Optional[str]:
        mongodb = context.get("mongodb")
        if mongodb is not None:
            try:
                doc = await mongodb.mcp_server_settings.find_one({"server_name": mcp_name})
                if doc and doc.get("llm_provider"):
                    return str(doc.get("llm_provider")).strip()
            except Exception as exc:
                logger.warning(f"[{mcp_name}] failed to read mcp_server_settings: {exc}")

        registry = context.get("registry")
        if registry:
            mcp = registry.get_mcp(mcp_name)
            cfg = getattr(mcp, "external_config", {}) if mcp else {}
            static_provider = cfg.get("llm_provider") or cfg.get("vlm")
            if static_provider:
                return str(static_provider).strip()

        return None

    async def _resolve_mcp_glm_ocr_provider(self, mcp_name: str, context: Dict[str, Any]) -> Optional[str]:
        mongodb = context.get("mongodb")
        if mongodb is not None:
            try:
                doc = await mongodb.mcp_server_settings.find_one({"server_name": mcp_name})
                if doc and doc.get("glm_ocr_provider"):
                    return str(doc.get("glm_ocr_provider")).strip()
            except Exception as exc:
                logger.warning(f"[{mcp_name}] failed to read mcp_server_settings: {exc}")

        registry = context.get("registry")
        if registry:
            mcp = registry.get_mcp(mcp_name)
            cfg = getattr(mcp, "external_config", {}) if mcp else {}
            static_provider = cfg.get("glm_ocr_provider") or cfg.get("ocr_provider")
            if not static_provider and isinstance(cfg.get("glm_ocr"), dict):
                static_provider = cfg["glm_ocr"].get("provider")
            if static_provider:
                return str(static_provider).strip()

        return None

    @staticmethod
    def _mask_secret(value: str) -> str:
        if not value:
            return ""
        if len(value) <= 8:
            return "***"
        return f"{value[:4]}***{value[-4:]}"

    async def _handle_resources_list(
        self,
        message: MCPMessage,
        context: dict
    ) -> dict:
        """处理resources/list请求"""
        # 暂不实现resources
        return {"resources": []}

    async def _handle_resources_read(
        self,
        message: MCPMessage,
        context: dict
    ) -> dict:
        """处理resources/read请求"""
        # 暂不实现resources
        raise ValueError("Resources not implemented")

    async def _handle_prompts_list(
        self,
        message: MCPMessage,
        context: dict
    ) -> dict:
        """处理prompts/list请求"""
        # 暂不实现prompts
        return {"prompts": []}

    async def _handle_prompts_get(
        self,
        message: MCPMessage,
        context: dict
    ) -> dict:
        """处理prompts/get请求"""
        # 暂不实现prompts
        raise ValueError("Prompts not implemented")
