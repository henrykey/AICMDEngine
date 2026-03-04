"""
MCP Protocol Handler

Handles JSON-RPC 2.0 messages for Model Context Protocol.
"""

from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


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

        # Inject per-MCP LLM provider configuration for external OCR/VLM MCPs.
        arguments = await self._inject_external_vlm_config(
            mcp_name=mcp_name,
            tool_name=tool_name,
            arguments=arguments,
            context=context,
        )

        # 执行工具（传递JWT token和tenant_id）
        try:
            result = await registry.execute_command(
                mcp_name=mcp_name,
                tool_name=tool_name,
                auth_token=jwt_token,  # 传递JWT token
                tenant_id=tenant_id,   # 传递tenant_id
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

    async def _inject_external_vlm_config(
        self,
        mcp_name: str,
        tool_name: str,
        arguments: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Inject vlm_config for external MCPs from runtime MCP->LLM binding.
        Priority:
        1) Explicit request args (caller-provided vlm_config/vlm_defaults)
        2) MongoDB mcp_server_settings.llm_provider
        3) EXTERNAL_MCPS static config field (llm_provider/vlm)
        """
        args = dict(arguments or {})

        # Respect explicit caller override.
        if args.get("vlm_config") or args.get("vlm_defaults"):
            logger.info(
                "[%s.%s] caller provided VLM config directly; skip router injection",
                mcp_name,
                tool_name,
            )
            return args

        # Currently only pdf2md-enhanced requires runtime injected vlm_config.
        if mcp_name != "pdf2md-enhanced":
            return args

        provider_name = await self._resolve_mcp_llm_provider(mcp_name, context)
        if not provider_name:
            logger.info("[%s.%s] no MCP->LLM binding found; skip VLM injection", mcp_name, tool_name)
            return args

        provider_manager = context.get("provider_manager")
        if provider_manager is None:
            logger.warning(f"[{mcp_name}] provider_manager unavailable, skip VLM injection")
            return args

        provider = provider_manager.get_provider(provider_name)
        if not provider:
            logger.warning(f"[{mcp_name}] provider '{provider_name}' not found, skip VLM injection")
            return args

        api_key = provider_manager.config_loader.get_api_key(provider.api_key_ref)
        if not api_key:
            logger.warning(f"[{mcp_name}] provider '{provider_name}' api_key not available, skip VLM injection")
            return args

        vlm_config = {
            "provider": provider.name,
            "model": provider.model,
            "base_url": provider.base_url,
            "api_key": api_key,
            "timeout_sec": provider.timeout,
            "temperature": provider.temperature,
        }

        if tool_name == "start_task":
            args["vlm_defaults"] = vlm_config
        elif tool_name == "process_task_page":
            args["vlm_config"] = vlm_config

        return args

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
