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

        # 获取JWT token和tenant_id用于工具调用
        jwt_token = context.get("jwt_token")
        client_info = context.get("client_info", {})
        tenant_id = client_info.get("tenant_id")

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

        logger.info(f"Executing tool: {mcp_name}.{tool_name}")

        # ===== Membership API 推送的系统服务 token 处理 =====
        # 如果 Membership API 推送了 system_service_token，缓存到 MembershipMCPServer
        # 这样后续 audit 回调可以使用缓存的 token（24小时有效）
        system_service_token = arguments.get("system_service_token")
        pushed_tenant_id = arguments.get("_tenant_id") or arguments.get("tenant_id")

        if system_service_token and pushed_tenant_id:
            membership_mcp = registry.get_mcp("membership")
            if membership_mcp and hasattr(membership_mcp, "_audit_system_tokens"):
                # Issue #3 fix: Validate tenant claims consistency before caching
                if self._validate_system_token_claims(system_service_token, pushed_tenant_id):
                    membership_mcp._audit_system_tokens[pushed_tenant_id] = system_service_token
                    logger.info(
                        f"Cached system service token for tenant {pushed_tenant_id} "
                        f"(pushed by Membership API, 24h validity, claims validated)"
                    )
                else:
                    logger.warning(
                        f"Skipped caching system token for tenant {pushed_tenant_id}: "
                        f"claims validation failed (tenant mismatch or invalid subject)"
                    )

        # 从 arguments 中移除 system_service_token（它是传递给 MCP Router 的元数据，不是工具参数）
        if "system_service_token" in arguments:
            arguments = {k: v for k, v in arguments.items() if k != "system_service_token"}

        # Inject per-MCP model provider configuration for external OCR/VLM MCPs.
        arguments = await self._inject_external_model_configs(
            mcp_name=mcp_name,
            tool_name=tool_name,
            arguments=arguments,
            context=context,
        )

        # 执行工具（传递JWT token和tenant_id）
        try:
            effective_arguments = dict(arguments)
            effective_arguments.setdefault("auth_token", jwt_token)
            effective_arguments.setdefault("tenant_id", tenant_id)

            result = await registry.execute_command(
                mcp_name=mcp_name,
                tool_name=tool_name,
                **effective_arguments
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

    @staticmethod
    def _validate_system_token_claims(token: str, expected_tenant_id: Any) -> bool:
        """
        Issue #3 fix: Validate tenant claims consistency before caching.

        This is a lightweight sanity check, NOT a security boundary.
        Real security validation is done by Membership API when verifying the token.

        Checks:
        1. Decode JWT payload (without signature verification)
        2. If payload has tenantId/tenant_id, verify it matches expected_tenant_id
        3. If payload has 'sub' field, verify it follows system-service pattern

        Args:
            token: JWT token string
            expected_tenant_id: Expected tenant ID from arguments

        Returns:
            True if claims are consistent (allow caching)
            False if claims mismatch, token format invalid, or decode fails (skip caching)
        """
        import base64
        import json

        try:
            # JWT format: header.payload.signature
            parts = token.split('.')
            if len(parts) != 3:
                logger.warning("Invalid JWT format, refusing to cache")
                return False  # Refuse caching for invalid format

            # Decode payload (second part)
            payload = parts[1]
            # Add padding if needed
            padding = 4 - len(payload) % 4
            if padding != 4:
                payload += '=' * padding

            decoded = base64.urlsafe_b64decode(payload)
            claims = json.loads(decoded)

            # Check tenant ID consistency
            token_tenant_id = claims.get("tenantId") or claims.get("tenant_id")
            if token_tenant_id is not None:
                # Convert to same type for comparison
                if str(token_tenant_id) != str(expected_tenant_id):
                    logger.warning(
                        f"Token tenant mismatch: token has {token_tenant_id}, "
                        f"expected {expected_tenant_id}, refusing to cache"
                    )
                    return False

            # Check subject pattern for system service account
            # Expected: system-service-t{tenantId} or similar pattern (must start with system-service-)
            sub = claims.get("sub")
            if sub:
                if not sub.startswith("system-service-"):
                    logger.warning(
                        f"Token subject '{sub}' doesn't match system service pattern, "
                        f"refusing to cache"
                    )
                    return False

            return True

        except Exception as e:
            logger.warning(f"Failed to decode token claims: {e}, refusing to cache")
            return False  # Refuse caching if validation fails

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
