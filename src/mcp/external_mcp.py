"""
External MCP Server Adapter
支持多种传输方式连接外部MCP服务器：
- stdio: 标准输入/输出进程通信
- websocket: WebSocket 连接
- http: HTTP/SSE (streamable-http) 或 Legacy SSE 协议
  * 自动检测 /mcp (streamable-http) 端点
  * 降级到 /sse (legacy SSE) 端点
"""

import asyncio
import json
import logging
from typing import Dict, Any, Optional, List
from subprocess import PIPE, STDOUT
from datetime import datetime

from .base_server import BaseMCPServer, Tool, ToolResult
from ..core.config import settings

logger = logging.getLogger(__name__)


class ExternalMCPServer(BaseMCPServer):
    """
    外部MCP服务器适配器

    通过stdio或WebSocket连接到外部MCP服务器，
    并将其工具暴露给MCPRegistry
    """

    def __init__(
        self,
        name: str,
        command: Optional[str] = None,
        args: Optional[List[str]] = None,
        transport: str = "stdio",
        url: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout: int = 30
    ):
        """
        初始化外部MCP服务器适配器

        Args:
            name: MCP服务器名称
            command: 启动MCP服务器的命令 (stdio/websocket transport 需要)
            args: 命令参数列表
            transport: 传输方式
                - "stdio": 标准进程通信 (需要 command 参数)
                - "websocket": WebSocket 连接 (需要 url 参数)
                - "http": HTTP/SSE 连接 (需要 url 参数)
                  自动probing流程: GET /mcp → GET /sse → 连接成功
            url: 连接URL (websocket/http transport 需要)
                - WebSocket: ws://host:port/path
                - HTTP/SSE: http://host:port (会自动尝试 /mcp 和 /sse 端点)
            env: 环境变量
            timeout: 请求超时时间（秒）
        """
        super().__init__(name, "1.0")
        self.command = command
        self.args = args or []
        self.transport = transport
        self.url = url
        self.env = env or {}
        self.timeout = timeout

        # 进程管理 (stdio)
        self.process: Optional[asyncio.subprocess.Process] = None

        # WebSocket 连接 (websocket)
        self.websocket: Optional[Any] = None

        # HTTP 会话 (http/sse)
        self.http_session: Optional[Any] = None
        self.http_session_id: Optional[str] = None  # MCP session ID for streamable-http
        self.sse_mode: bool = False               # True = 使用旧版 SSE 协议 (/sse)
        self.sse_message_url: Optional[str] = None  # 旧版 SSE 的消息端点 URL
        self.sse_response: Optional[Any] = None    # 旧版 SSE 长连接 response 对象

        # 请求管理
        self.request_id = 0
        self.pending_requests: Dict[int, asyncio.Future] = {}

        # 工具缓存
        self.tools_cache: Dict[str, Dict[str, Any]] = {}

        # 验证参数
        if transport == "stdio" and not command:
            raise ValueError(f"'command' is required for stdio transport in '{name}'")
        if transport == "websocket" and not url:
            raise ValueError(f"'url' is required for websocket transport in '{name}'")

        logger.info(
            f"Created ExternalMCPServer '{name}' "
            f"(transport={transport}, url={url or 'N/A'}, command={command or 'N/A'})"
        )

    async def initialize(self) -> None:
        """初始化与外部MCP的连接"""
        try:
            if self.transport == "stdio":
                await self._connect_stdio()
            elif self.transport == "websocket":
                await self._connect_websocket()
            elif self.transport in ("http", "http-bridge", "sse"):
                await self._connect_http()
            else:
                raise ValueError(f"Unsupported transport: {self.transport}")

            # 标记为已初始化
            self.is_initialized = True
            self.last_heartbeat = datetime.now()

            logger.info(f"Initialized external MCP '{self.name}'")

        except Exception as e:
            logger.error(f"Failed to initialize external MCP '{self.name}': {e}")
            raise

    async def _connect_stdio(self):
        """通过stdio连接外部MCP"""
        try:
            # 准备环境变量
            import os
            env = os.environ.copy()
            env.update(self.env)

            # 启动外部MCP进程
            logger.info(
                f"Starting external MCP '{self.name}': "
                f"{self.command} {' '.join(self.args)}"
            )

            self.process = await asyncio.create_subprocess_exec(
                self.command,
                *self.args,
                stdin=PIPE,
                stdout=PIPE,
                stderr=PIPE,
                env=env,
                limit=settings.external_mcp_stdio_buffer_size
            )

            # 启动消息读取任务
            asyncio.create_task(self._read_messages_loop())

            # 等待进程启动
            await asyncio.sleep(0.5)

            # 发送initialize握手
            await self._send_initialize()

            # 发现工具
            await self._discover_tools()

        except Exception as e:
            logger.error(f"Failed to connect via stdio: {e}")
            if self.process:
                self.process.terminate()
                await self.process.wait()
            raise

    async def _connect_websocket(self):
        """通过WebSocket连接外部MCP"""
        try:
            import websockets

            logger.info(f"Connecting to WebSocket MCP '{self.name}': {self.url}")

            # 建立 WebSocket 连接
            self.websocket = await websockets.connect(
                self.url,
                ping_interval=20,
                ping_timeout=120,  # 增加到120秒，适应PaddleOCR等慢速MCP
                close_timeout=10,
                max_size=settings.external_mcp_ws_max_size
            )

            logger.info(f"WebSocket connection established to '{self.name}'")

            # 启动消息接收任务
            asyncio.create_task(self._read_websocket_messages_loop())

            # 等待连接稳定
            await asyncio.sleep(0.2)

            # 发送initialize握手
            await self._send_initialize()

            # 发现工具
            await self._discover_tools()

            logger.info(f"WebSocket MCP '{self.name}' initialized successfully")

        except Exception as e:
            logger.error(f"Failed to connect WebSocket MCP '{self.name}': {e}")
            if self.websocket:
                try:
                    await self.websocket.close()
                except Exception:
                    pass
                self.websocket = None
            raise

    async def _connect_http(self):
        """
        通过 HTTP 连接外部MCP，自动探测协议协商（Protocol Probing）
        
        协议探测流程:
        1. 尝试 streamable-http: POST /mcp + initialize 握手
           - 如果成功: 继续使用 streamable-http
           - 如果 404: 回退到 legacy SSE
        2. 如果 streamable-http 失败: 尝试 legacy SSE
           a. GET /sse 打开 SSE 长连接
           b. 等待 'event: endpoint' + 'data: /messages?session_id=xxx'
           c. 使用该 session_id POST 消息
        
        这种自动降级机制确保兼容不同版本的 MCP HTTP 服务
        """
        import aiohttp

        logger.info(f"Connecting to HTTP MCP '{self.name}': {self.url}")

        self.http_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.timeout, connect=30, sock_read=self.timeout),
            # Avoid "Chunk too big" on large streamable-http/SSE JSON-RPC responses
            # (e.g. finalize_task returning merged markdown/rag for many pages).
            read_bufsize=settings.external_mcp_http_read_buffer_size,
            max_line_size=settings.external_mcp_http_max_line_size,
            max_field_size=64 * 1024,
        )

        try:
            # 尝试 streamable-http
            probed = await self._probe_streamable_http()
            if probed:
                logger.info(f"HTTP MCP '{self.name}': using streamable-http (/mcp)")
                await self._discover_tools()
            else:
                # 回退旧版 SSE
                logger.info(f"HTTP MCP '{self.name}': /mcp not found, trying legacy SSE (/sse)")
                await self._connect_legacy_sse()
                await self._discover_tools()

            logger.info(f"HTTP MCP '{self.name}' initialized successfully")

        except Exception as e:
            logger.error(f"Failed to connect HTTP MCP '{self.name}': {e}")
            if self.http_session:
                try:
                    await self.http_session.close()
                except Exception:
                    pass
                self.http_session = None
            raise

    async def _probe_streamable_http(self) -> bool:
        """
        探测 streamable-http 协议 (/mcp 端点)
        
        streamable-http 特点:
        - POST /mcp 端点，body 为 JSON-RPC 请求
        - 支持 Mcp-Session-Id header
        - 响应可以是单个 JSON 或 SSE 流
        
        返回 True: /mcp 可用，继续用 streamable-http
        返回 False: 404/失败，回退到 legacy SSE (/sse)
        """
        import aiohttp

        init_request = {
            "jsonrpc": "2.0",
            "id": self._next_request_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                "clientInfo": {"name": "AICMDEngine", "version": "1.0.0"}
            }
        }

        mcp_url = f"{self.url.rstrip('/')}/mcp"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }

        try:
            async with self.http_session.post(
                mcp_url,
                data=json.dumps(init_request),
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 404:
                    return False

                session_id = resp.headers.get("Mcp-Session-Id") or resp.headers.get("mcp-session-id")
                if session_id:
                    self.http_session_id = session_id
                    logger.info(f"HTTP MCP '{self.name}' session ID: {session_id}")

                if resp.status == 200:
                    content_type = resp.headers.get("Content-Type", "")
                    response = None
                    if "text/event-stream" in content_type:
                        async for raw_line in resp.content:
                            line = raw_line.decode("utf-8").strip()
                            if line.startswith("data:"):
                                data_str = line[5:].strip()
                                if data_str:
                                    try:
                                        msg = json.loads(data_str)
                                        if "result" in msg or "error" in msg:
                                            response = msg
                                            break
                                    except json.JSONDecodeError:
                                        pass
                    else:
                        body = await resp.text()
                        if body.strip():
                            response = json.loads(body)

                    if response and "result" in response:
                        server_info = response["result"].get("serverInfo", {})
                        logger.info(
                            f"Connected to HTTP MCP '{self.name}': "
                            f"{server_info.get('name', 'Unknown')} "
                            f"v{server_info.get('version', 'Unknown')}"
                        )

                    # 发送 initialized 通知
                    try:
                        notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
                        await self._send_http_request(notif)
                    except Exception:
                        pass

                    return True

        except Exception as e:
            logger.warning(f"HTTP MCP '{self.name}' streamable-http probe failed: {e}")

        return False

    async def _connect_legacy_sse(self):
        """
        连接 legacy MCP SSE 协议 (/sse 端点)
        
        Legacy SSE 通讯流程:
        1. GET /sse: 打开 SSE 长连接
        2. 接收 'event: endpoint' + 'data: /messages?session_id=xxx'
        3. POST /messages?session_id=xxx: 发送 JSON-RPC 请求
        4. SSE 流推回响应: 'event: message' + 'data: {...JSON-RPC 响应...}'
        
        特点:
        - 长连接用于服务器推送消息
        - 短连接 POST 发送客户端消息
        - session_id 映射请求/响应对
        """
        import aiohttp

        sse_url = f"{self.url.rstrip('/')}/sse"
        logger.info(f"Connecting legacy SSE MCP '{self.name}': {sse_url}")

        endpoint_future: asyncio.Future = asyncio.get_event_loop().create_future()

        # 打开 SSE 长连接
        self.sse_response = await self.http_session.get(
            sse_url,
            headers={"Accept": "text/event-stream"},
            timeout=aiohttp.ClientTimeout(total=None, connect=30, sock_read=None)
        )

        if self.sse_response.status != 200:
            raise RuntimeError(
                f"Legacy SSE connect failed: HTTP {self.sse_response.status}"
            )

        # 背景任务：持续读取 SSE 事件
        async def _sse_reader():
            event_type = None
            try:
                async for raw_line in self.sse_response.content:
                    line = raw_line.decode("utf-8").rstrip("\n").rstrip("\r")
                    if line.startswith("event:"):
                        event_type = line[6:].strip()
                    elif line.startswith("data:"):
                        data_str = line[5:].strip()
                        if event_type == "endpoint":
                            # 收到消息端点 URL（可能是相对路径）
                            if data_str.startswith("/"):
                                base = self.url.rstrip("/")
                                # 取 scheme+host
                                from urllib.parse import urlparse
                                p = urlparse(base)
                                msg_url = f"{p.scheme}://{p.netloc}{data_str}"
                            else:
                                msg_url = data_str
                            self.sse_message_url = msg_url
                            self.sse_mode = True
                            if not endpoint_future.done():
                                endpoint_future.set_result(msg_url)
                            logger.info(
                                f"Legacy SSE MCP '{self.name}' message URL: {msg_url}"
                            )
                        elif event_type == "message" and data_str:
                            # JSON-RPC 响应，解析并 resolve 对应的 future
                            try:
                                msg = json.loads(data_str)
                                req_id = msg.get("id")
                                if req_id is not None and req_id in self.pending_requests:
                                    fut = self.pending_requests.pop(req_id)
                                    if not fut.done():
                                        fut.set_result(msg)
                            except json.JSONDecodeError:
                                pass
                        event_type = None
                    elif line == "":
                        event_type = None
            except Exception as e:
                logger.warning(f"Legacy SSE reader for '{self.name}' ended: {e}")
                # 将所有待定请求标记为错误
                for fut in self.pending_requests.values():
                    if not fut.done():
                        fut.set_exception(ConnectionError("SSE connection closed"))

        asyncio.create_task(_sse_reader())

        # 等待 endpoint 事件（最多 10 秒）
        try:
            await asyncio.wait_for(endpoint_future, timeout=10)
        except asyncio.TimeoutError:
            raise RuntimeError(f"Legacy SSE MCP '{self.name}': timeout waiting for endpoint event")

        # 发送 initialize 握手
        init_request = {
            "jsonrpc": "2.0",
            "id": self._next_request_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                "clientInfo": {"name": "AICMDEngine", "version": "1.0.0"}
            }
        }
        response = await self._send_legacy_sse_request(init_request)
        if response and "result" in response:
            server_info = response["result"].get("serverInfo", {})
            logger.info(
                f"Connected to legacy SSE MCP '{self.name}': "
                f"{server_info.get('name', 'Unknown')} "
                f"v{server_info.get('version', 'Unknown')}"
            )

        # 发送 initialized 通知
        try:
            notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
            await self._send_legacy_sse_request(notif, no_reply=True)
        except Exception:
            pass

    async def _send_legacy_sse_request(
        self,
        request: Dict[str, Any],
        no_reply: bool = False
    ) -> Optional[Dict[str, Any]]:
        """通过旧版 SSE 协议 POST 消息，响应从 SSE 流推回。"""
        import aiohttp

        if not self.sse_message_url:
            raise RuntimeError(f"Legacy SSE message URL not set for '{self.name}'")

        request_json = json.dumps(request)
        req_id = request.get("id")

        # 注册 future（仅有 id 的请求需要等待响应）
        fut: Optional[asyncio.Future] = None
        if req_id is not None and not no_reply:
            fut = asyncio.get_event_loop().create_future()
            self.pending_requests[req_id] = fut

        async with self.http_session.post(
            self.sse_message_url,
            data=request_json,
            headers={"Content-Type": "application/json"},
            timeout=aiohttp.ClientTimeout(total=30)
        ) as resp:
            if resp.status not in (200, 202, 204):
                body = await resp.text()
                if fut and req_id in self.pending_requests:
                    self.pending_requests.pop(req_id)
                raise RuntimeError(f"Legacy SSE POST failed: {resp.status} {body[:200]}")

        if fut is None:
            return None

        # 等待 SSE 流推回响应
        return await asyncio.wait_for(fut, timeout=self.timeout)

    async def _send_initialize(self):
        """发送initialize握手请求"""
        init_request = {
            "jsonrpc": "2.0",
            "id": self._next_request_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {},
                    "resources": {},
                    "prompts": {}
                },
                "clientInfo": {
                    "name": "AICMDEngine",
                    "version": "1.0.0"
                }
            }
        }

        try:
            response = await self._send_request(init_request)

            if response and "result" in response:
                server_info = response["result"].get("serverInfo", {})
                logger.info(
                    f"Connected to external MCP '{self.name}': "
                    f"{server_info.get('name', 'Unknown')} "
                    f"v{server_info.get('version', 'Unknown')}"
                )
            else:
                logger.warning(f"Unexpected initialize response from '{self.name}'")

        except Exception as e:
            logger.error(f"Failed to initialize external MCP '{self.name}': {e}")
            raise

    async def _discover_tools(self):
        """发现外部MCP提供的工具"""
        try:
            if self.transport in ("http", "http-bridge", "sse"):
                # HTTP方式：发送GET /tools请求
                await self._discover_tools_http()
            else:
                # JSON-RPC方式：stdio 和 websocket
                await self._discover_tools_jsonrpc()

        except Exception as e:
            logger.error(f"Failed to discover tools from '{self.name}': {e}")

    async def _discover_tools_jsonrpc(self):
        """通过JSON-RPC发现工具（stdio/websocket）"""
        list_request = {
            "jsonrpc": "2.0",
            "id": self._next_request_id(),
            "method": "tools/list"
        }

        response = await self._send_request(list_request)

        if response and "result" in response:
            tools = response["result"].get("tools", [])

            # 清空现有工具
            self.tools = {}

            # 注册所有发现的工具
            for tool_def in tools:
                await self._register_external_tool(tool_def)

            logger.info(
                f"Discovered {len(tools)} tools from external MCP '{self.name}'"
            )
        else:
            logger.warning(f"No tools returned from external MCP '{self.name}'")

    async def _discover_tools_http(self):
        """通过 HTTP 协议发现工具（自动选择 streamable-http 或 legacy SSE）"""
        try:
            logger.info(f"Discovering tools from HTTP MCP '{self.name}'")

            request = {
                "jsonrpc": "2.0",
                "id": self._next_request_id(),
                "method": "tools/list"
            }

            if self.sse_mode:
                response = await self._send_legacy_sse_request(request)
            else:
                response, _ = await self._send_http_request(request)

            if response and "result" in response:
                tools = response["result"].get("tools", [])

                # 清空现有工具
                self.tools = {}

                # 注册所有发现的工具
                for tool_def in tools:
                    await self._register_external_tool(tool_def)

                logger.info(
                    f"Discovered {len(tools)} tools from HTTP MCP '{self.name}'"
                )
            else:
                logger.warning(f"No tools returned from HTTP MCP '{self.name}'")

        except Exception as e:
            logger.error(f"Error discovering tools from HTTP MCP '{self.name}': {e}")
            raise

    async def _send_http_request(
        self,
        request: Dict[str, Any],
        allow_session_recover: bool = True,
    ) -> tuple:
        """向 streamable-http MCP 端点发送 JSON-RPC 请求。

        按 MCP streamable-http 规范：
        - POST /mcp
        - Content-Type: application/json
        - Accept: application/json, text/event-stream
        - Mcp-Session-Id: <session_id>  (握手后必须携带)

        响应可能是 application/json 或 text/event-stream，均处理。
        返回 (response_dict_or_None, session_id_or_None)
        """
        import aiohttp

        mcp_url = f"{self.url.rstrip('/')}/mcp"
        request_json = json.dumps(request)

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.http_session_id:
            headers["Mcp-Session-Id"] = self.http_session_id

        is_notification = "id" not in request  # 通知无需等待响应

        logger.debug(f"HTTP POST {mcp_url} method={request.get('method')}")

        try:
            async with self.http_session.post(
                mcp_url,
                data=request_json,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            ) as resp:
                # 提取 session ID（仅在 initialize 响应中出现）
                session_id = resp.headers.get("Mcp-Session-Id") or resp.headers.get("mcp-session-id")

                # 202 Accepted = 通知已收，无响应体
                if resp.status == 202 or is_notification:
                    return None, session_id

                if resp.status != 200:
                    body = await resp.text()
                    body_lc = body.lower()
                    # streamable-http server重启后，旧session会失效（404 Session not found）。
                    # 自动重建session并重试一次，避免上层直接拿到 "No response from external MCP"。
                    should_recover = (
                        allow_session_recover
                        and not is_notification
                        and not self.sse_mode
                        and bool(self.http_session_id)
                        and resp.status == 404
                        and "session" in body_lc
                        and "not found" in body_lc
                    )
                    if should_recover:
                        logger.warning(
                            "HTTP MCP '%s' session expired (404 Session not found), recovering session and retrying once",
                            self.name,
                        )
                        recovered = await self._recover_streamable_http_session()
                        if recovered:
                            return await self._send_http_request(
                                request,
                                allow_session_recover=False,
                            )
                    logger.error(
                        f"HTTP MCP '{self.name}' request failed: "
                        f"{resp.status} {body[:200]}"
                    )
                    return None, session_id

                content_type = resp.headers.get("Content-Type", "")

                if "text/event-stream" in content_type:
                    # SSE 响应：解析事件流，取第一个有 result/error 的消息
                    async for raw_line in resp.content:
                        line = raw_line.decode("utf-8").strip()
                        if line.startswith("data:"):
                            data_str = line[5:].strip()
                            if data_str and data_str != "[DONE]":
                                try:
                                    msg = json.loads(data_str)
                                    if "result" in msg or "error" in msg:
                                        return msg, session_id
                                except json.JSONDecodeError:
                                    pass
                    return None, session_id
                else:
                    # 直接 JSON 响应
                    body = await resp.text()
                    if body.strip():
                        return json.loads(body), session_id
                    return None, session_id

        except Exception as e:
            logger.error(
                "HTTP request error for '%s': %s (%r)",
                self.name,
                e.__class__.__name__,
                e,
            )
            raise

    async def _recover_streamable_http_session(self) -> bool:
        """重建失效的 streamable-http session，并返回是否成功。"""
        if self.sse_mode:
            return False
        old_session_id = self.http_session_id
        self.http_session_id = None
        try:
            ok = await self._probe_streamable_http()
            if ok:
                logger.info(
                    "HTTP MCP '%s' session recovered: %s -> %s",
                    self.name,
                    old_session_id or "<none>",
                    self.http_session_id or "<none>",
                )
                return True
            logger.error(
                "HTTP MCP '%s' session recover failed: streamable-http probe returned False",
                self.name,
            )
            return False
        except Exception as err:
            logger.error(
                "HTTP MCP '%s' session recover failed: %s (%r)",
                self.name,
                err.__class__.__name__,
                err,
            )
            return False

    async def _register_external_tool(self, tool_def: Dict[str, Any]):
        """注册外部工具到本地MCP"""
        tool_name = tool_def["name"]  # 保持原始名称，不带前缀
        self.tools_cache[tool_name] = tool_def

        # 创建工具描述
        description = tool_def.get("description", "")
        input_schema = tool_def.get("inputSchema", {})

        # 创建异步包装器
        async def external_tool_wrapper(**kwargs):
            return await self._execute_external_tool(tool_name, kwargs)

        # 注册到MCP（工具名不带前缀，前缀只用于协议层路由）
        self.register_tool(Tool(
            name=tool_name,
            description=description,
            input_schema=input_schema,
            handler=external_tool_wrapper
        ))

        logger.debug(f"Registered external tool '{tool_name}' from '{self.name}'")

    async def _execute_external_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> ToolResult:
        """执行外部工具"""
        # HTTP方式有不同的实现
        if self.transport in ("http", "http-bridge", "sse"):
            return await self._execute_tool_http(tool_name, arguments)
        else:
            return await self._execute_tool_jsonrpc(tool_name, arguments)

    async def _execute_tool_jsonrpc(
        self,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> ToolResult:
        """通过JSON-RPC执行工具（stdio/websocket）"""
        # 最大重试次数（用于处理连接断开重连）
        max_retries = 1
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                request = {
                    "jsonrpc": "2.0",
                    "id": self._next_request_id(),
                    "method": "tools/call",
                    "params": {
                        "name": tool_name,
                        "arguments": arguments
                    }
                }

                response = await self._send_request(request, timeout=self.timeout)

                if response:
                    if "error" in response:
                        error = response["error"]
                        error_msg = error.get("message", "Unknown error")
                        error_code = str(error.get("code", "UNKNOWN"))
                        logger.error(
                            f"External tool '{tool_name}' error: {error_msg}"
                        )
                        return ToolResult.error(error_msg, error_code=error_code)

                    if "result" in response:
                        return self._build_tool_result_from_response_result(tool_name, response["result"])

                    return ToolResult.error("Invalid response from external MCP", error_code="INVALID_RESPONSE")

                return ToolResult.error(
                    "No response from external MCP",
                    error_code="NO_RESPONSE"
                )

            except (RuntimeError, ConnectionError) as conn_err:
                # 连接错误（包括 WebSocket closed），尝试重试
                last_error = conn_err
                if attempt < max_retries:
                    logger.warning(
                        f"Connection error for '{tool_name}' (attempt {attempt + 1}/{max_retries + 1}): {conn_err}. Retrying..."
                    )
                    # 等待一小段时间后重试，让连接有时间恢复
                    await asyncio.sleep(0.5)
                    continue
                else:
                    error_msg = f"Error executing external tool '{tool_name}' after {max_retries + 1} attempts: {conn_err}"
                    logger.error(error_msg)
                    return ToolResult.error(error_msg, error_code="CONNECTION_ERROR")

            except asyncio.TimeoutError:
                error_msg = f"Tool '{tool_name}' execution timed out"
                logger.error(error_msg)
                return ToolResult.error(error_msg, error_code="TIMEOUT")
            except Exception as e:
                error_msg = f"Error executing external tool '{tool_name}': {e}"
                logger.error(error_msg)
                return ToolResult.error(error_msg, error_code="EXECUTION_ERROR")

    async def _execute_tool_http(
        self,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> ToolResult:
        """通过 HTTP SSE (streamable-http) 执行工具"""
        try:
            # 构造 JSON-RPC 请求
            request = {
                "jsonrpc": "2.0",
                "id": self._next_request_id(),
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments
                }
            }

            logger.info(f"Executing HTTP tool '{tool_name}'")

            # 根据协议模式选择发送方式
            if self.sse_mode:
                response = await self._send_legacy_sse_request(request)
            else:
                response, _ = await self._send_http_request(request)

            if response:
                if "error" in response:
                    error = response["error"]
                    error_msg = error.get("message", "Unknown error")
                    error_code = str(error.get("code", "UNKNOWN"))
                    logger.error(f"Tool '{tool_name}' error: {error_msg}")
                    return ToolResult.error(error_msg, error_code=error_code)

                if "result" in response:
                    return self._build_tool_result_from_response_result(tool_name, response["result"])

            return ToolResult.error(
                "No response from external MCP",
                error_code="NO_RESPONSE"
            )

        except asyncio.TimeoutError:
            error_msg = f"HTTP tool '{tool_name}' execution timed out ({self.timeout}s)"
            logger.error(error_msg)
            return ToolResult.error(error_msg, error_code="TIMEOUT")

        except Exception as e:
            error_msg = f"Error executing HTTP tool '{tool_name}': {e}"
            logger.error(error_msg)
            return ToolResult.error(error_msg, error_code="EXECUTION_ERROR")

    def _build_tool_result_from_response_result(self, tool_name: str, result: Dict[str, Any]) -> ToolResult:
        if result.get("isError", False):
            content = result.get("content", [])
            if content and len(content) > 0:
                error_text = content[0].get("text", "Unknown error")
                return ToolResult.error(error_text, error_code="TOOL_ERROR")
            return ToolResult.error("Unknown error", error_code="TOOL_ERROR")

        content = result.get("content", [])
        if content and len(content) > 0:
            text_content = []
            for item in content:
                if item.get("type") == "text":
                    text_content.append(item.get("text", ""))

            if text_content:
                combined_text = "\n".join(text_content)
                embedded_error = self._extract_embedded_tool_error(combined_text)
                if embedded_error:
                    logger.warning(
                        "External tool '%s' returned embedded error payload: %s",
                        tool_name,
                        embedded_error,
                    )
                    return ToolResult.error(embedded_error, error_code="TOOL_ERROR")

                logger.info(
                    "Tool '%s' result length: %s characters",
                    tool_name,
                    len(combined_text),
                )
                self._log_tool_engine_summary(tool_name, combined_text)
                return ToolResult.success(combined_text)

        return ToolResult.success(str(result))

    def _log_tool_engine_summary(self, tool_name: str, text: str) -> None:
        summary = self._extract_tool_engine_summary(text)
        if not summary:
            return

        logger.info(
            "Tool '%s' engine summary: engine=%s model_calls=%s item_sources=%s vlm=%s",
            tool_name,
            summary.get("engine"),
            summary.get("model_calls"),
            summary.get("item_sources"),
            summary.get("vlm"),
        )

    def _extract_tool_engine_summary(self, text: str) -> Optional[Dict[str, Any]]:
        raw = (text or "").strip()
        if not raw:
            return None

        try:
            payload = json.loads(raw)
        except Exception:
            return None

        if not isinstance(payload, dict):
            return None

        model_calls = payload.get("model_calls") if isinstance(payload.get("model_calls"), dict) else {}
        sources = self._extract_result_sources(payload)
        engines = set(sources)

        for key, value in model_calls.items():
            try:
                if int(value or 0) > 0:
                    engines.add(str(key))
            except Exception:
                continue

        vlm_info = payload.get("vlm") if isinstance(payload.get("vlm"), dict) else {}
        if vlm_info and bool(vlm_info.get("enabled")):
            engines.add("vlm_ocr")

        if not engines and not model_calls and not vlm_info:
            return None

        engine_order = ["pymupdf", "glm_ocr", "vlm_ocr", "glm_ocr_layout", "glm_ocr_layout+vlm_ocr"]
        ordered = [engine for engine in engine_order if engine in engines]
        ordered.extend(sorted(engine for engine in engines if engine not in ordered))
        return {
            "engine": "+".join(ordered) if ordered else "unknown",
            "model_calls": model_calls,
            "item_sources": sorted(sources),
            "vlm": {
                key: vlm_info.get(key)
                for key in ["enabled", "provider", "model", "base_url", "max_tokens", "timeout_sec"]
                if key in vlm_info
            },
        }

    def _extract_result_sources(self, payload: Dict[str, Any]) -> set:
        sources = set()
        for key in ["items", "tables", "formulas", "figures"]:
            value = payload.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        source = item.get("source")
                        if isinstance(source, str) and source.strip():
                            sources.add(source.strip())

        elements = payload.get("elements") if isinstance(payload.get("elements"), dict) else {}
        for key in ["tables", "formulas", "figures"]:
            value = elements.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        source = item.get("source")
                        if isinstance(source, str) and source.strip():
                            sources.add(source.strip())
        return sources

    def _extract_embedded_tool_error(self, text: str) -> Optional[str]:
        raw = (text or "").strip()
        if not raw:
            return None

        try:
            payload = json.loads(raw)
        except Exception:
            return None

        if not isinstance(payload, dict):
            return None

        error_value = payload.get("error")
        if not error_value:
            return None

        if isinstance(error_value, str):
            return error_value
        if isinstance(error_value, dict):
            return str(error_value.get("message") or error_value)
        return str(error_value)

    async def _send_request(
        self,
        request: Dict[str, Any],
        timeout: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """
        发送请求并等待响应

        Args:
            request: JSON-RPC请求对象
            timeout: 超时时间（秒）

        Returns:
            JSON-RPC响应对象
        """
        # 检查WebSocket连接，如果断开则重新连接
        if self.transport == "websocket" and self.websocket is None:
            logger.warning(f"WebSocket connection to '{self.name}' lost, reconnecting...")
            await self._connect_websocket()

        # 根据transport类型检查连接
        if self.transport == "stdio":
            if not self.process or self.process.stdin is None:
                raise RuntimeError("External MCP process is not running")
        elif self.transport == "websocket":
            if not self.websocket:
                raise RuntimeError("WebSocket MCP connection is not established")

        # 创建Future等待响应
        request_id = request["id"]
        future = asyncio.Future()
        self.pending_requests[request_id] = future

        try:
            # 发送请求
            json_str = json.dumps(request)
            logger.debug(
                f"Sending to external MCP '{self.name}' ({self.transport}): {json_str[:200]}..."
            )

            if self.transport == "websocket":
                # WebSocket 发送
                try:
                    await self.websocket.send(json_str)
                except Exception as send_err:
                    # WebSocket 发送失败，可能连接已断开
                    logger.warning(f"WebSocket send failed for '{self.name}': {send_err}")
                    # 清理连接
                    self.websocket = None
                    # 清理pending request
                    self.pending_requests.pop(request_id, None)
                    # 重新抛出异常
                    raise RuntimeError(f"WebSocket connection closed: {send_err}")

            else:
                # stdio 发送
                self.process.stdin.write((json_str + "\n").encode())
                await self.process.stdin.drain()

            # 等待响应
            timeout = timeout or self.timeout
            response = await asyncio.wait_for(future, timeout=timeout)

            return response

        except asyncio.TimeoutError:
            logger.error(
                f"Request timeout for external MCP '{self.name}' "
                f"(request_id={request_id}, transport={self.transport})"
            )
            # 清理pending request
            self.pending_requests.pop(request_id, None)
            # WebSocket连接可能已失效，标记为需要重新连接
            if self.transport == "websocket":
                self.websocket = None
            raise
        except Exception as e:
            logger.error(f"Error sending request to '{self.name}': {e}")
            # 清理pending request
            self.pending_requests.pop(request_id, None)
            # WebSocket连接可能已失效，标记为需要重新连接
            if self.transport == "websocket":
                self.websocket = None
            raise

    async def _read_messages_loop(self):
        """持续读取外部MCP的消息"""
        if not self.process or self.process.stdout is None:
            logger.error("Cannot start message loop: no stdout")
            return

        try:
            buffer = b""

            while True:
                # 检查进程是否还在运行
                if self.process.returncode is not None:
                    logger.warning(f"External MCP '{self.name}' process terminated")
                    break

                # 读取数据
                try:
                    chunk = await asyncio.wait_for(
                        self.process.stdout.read(4096),
                        timeout=0.1
                    )

                    if not chunk:
                        # EOF
                        logger.warning(f"External MCP '{self.name}' closed stdout")
                        break

                    buffer += chunk

                    # 处理完整的消息行
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)

                        if not line.strip():
                            continue

                        try:
                            message = json.loads(line.decode())
                            await self._handle_message(message)

                        except json.JSONDecodeError as e:
                            logger.error(f"Failed to parse JSON: {e}")
                            logger.debug(f"Invalid JSON: {line[:200]}")
                        except Exception as e:
                            logger.error(f"Error handling message: {e}")

                except asyncio.TimeoutError:
                    # 超时是正常的，继续循环
                    continue
                except Exception as e:
                    logger.error(f"Error reading from stdout: {e}")
                    break

        except Exception as e:
            logger.error(f"Message loop error: {e}")
        finally:
            # 清理所有pending requests
            for future in self.pending_requests.values():
                if not future.done():
                    future.set_exception(
                        RuntimeError("External MCP connection closed")
                    )
            self.pending_requests.clear()

    async def _read_websocket_messages_loop(self):
        """WebSocket 消息接收循环"""
        if not self.websocket:
            logger.error("Cannot start WebSocket message loop: no connection")
            return

        try:
            logger.debug(f"Starting WebSocket message loop for '{self.name}'")

            async for message in self.websocket:
                try:
                    data = json.loads(message)
                    logger.debug(f"Received WebSocket message from '{self.name}': {str(data)[:200]}...")
                    await self._handle_message(data)

                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse WebSocket JSON from '{self.name}': {e}")
                    logger.debug(f"Invalid JSON: {message[:200]}")
                except Exception as e:
                    logger.error(f"Error handling WebSocket message from '{self.name}': {e}")

            logger.warning(f"WebSocket MCP '{self.name}' connection closed")

        except Exception as e:
            logger.error(f"WebSocket message loop error for '{self.name}': {e}")
        finally:
            # 清理所有pending requests
            for future in self.pending_requests.values():
                if not future.done():
                    future.set_exception(
                        RuntimeError("WebSocket MCP connection closed")
                    )
            self.pending_requests.clear()

    async def _handle_message(self, message: Dict[str, Any]):
        """处理收到的消息"""
        request_id = message.get("id")

        if request_id is not None:
            # 这是一个响应消息
            future = self.pending_requests.get(request_id)

            if future and not future.done():
                future.set_result(message)
                # 清理
                self.pending_requests.pop(request_id, None)
            else:
                logger.debug(
                    f"Received response for unknown or completed request: {request_id}"
                )
        else:
            # 可能是通知消息
            method = message.get("method")
            if method:
                logger.debug(f"Received notification: {method}")

    def _next_request_id(self) -> int:
        """生成下一个请求ID"""
        self.request_id += 1
        return self.request_id

    async def close(self):
        """关闭连接并清理资源"""
        logger.info(f"Closing external MCP '{self.name}' (transport={self.transport})")

        # 清理pending requests
        for future in self.pending_requests.values():
            if not future.done():
                future.set_exception(
                    RuntimeError("External MCP is shutting down")
                )
        self.pending_requests.clear()

        # 关闭 HTTP 会话
        if self.transport in ("http", "http-bridge", "sse"):
            if hasattr(self, 'http_session') and self.http_session:
                try:
                    await self.http_session.close()
                    logger.info(f"HTTP session closed for '{self.name}'")
                except Exception as e:
                    logger.error(f"Error closing HTTP session: {e}")
                finally:
                    self.http_session = None

        # 关闭 WebSocket 连接
        if self.transport == "websocket" and self.websocket:
            try:
                await self.websocket.close()
                logger.info(f"WebSocket connection closed for '{self.name}'")
            except Exception as e:
                logger.error(f"Error closing WebSocket connection: {e}")
            finally:
                self.websocket = None

        # 终止进程 (stdio)
        if self.transport == "stdio" and self.process:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning(
                    f"External MCP '{self.name}' did not terminate gracefully, "
                    f"forcing kill"
                )
                self.process.kill()
                await self.process.wait()
            except Exception as e:
                logger.error(f"Error terminating process: {e}")

            self.process = None

        logger.info(f"Closed external MCP '{self.name}'")

    def get_info(self) -> Dict[str, Any]:
        """获取MCP服务器信息"""
        info = super().get_info()
        info.update({
            "transport": self.transport,
            "command": self.command,
            "args": self.args,
            "url": self.url
        })

        # 连接状态
        if self.transport == "websocket":
            # websockets.ClientConnection 没有直接的 open/closed 属性
            # 简单检查连接对象是否存在
            info["is_connected"] = self.websocket is not None
        elif self.transport in ("http", "http-bridge", "sse"):
            # HTTP 会话状态
            info["is_connected"] = hasattr(self, 'http_session') and self.http_session is not None
        else:  # stdio
            info["is_running"] = self.process is not None and self.process.returncode is None

        return info
