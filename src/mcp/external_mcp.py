"""
External MCP Server Adapter
支持通过stdio或WebSocket连接外部MCP服务器
"""

import asyncio
import json
import logging
from typing import Dict, Any, Optional, List
from subprocess import PIPE, STDOUT
from datetime import datetime

from .base_server import BaseMCPServer, Tool, ToolResult

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
            command: 启动MCP服务器的命令 (stdio transport 需要)
            args: 命令参数列表
            transport: 传输方式 (stdio 或 websocket)
            url: WebSocket URL (websocket transport 需要)
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
                limit=1024 * 1024  # 1MB buffer
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
                ping_timeout=20,
                close_timeout=10,
                max_size=10 * 1024 * 1024  # 10MB
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

        except Exception as e:
            logger.error(f"Failed to discover tools from '{self.name}': {e}")

    async def _register_external_tool(self, tool_def: Dict[str, Any]):
        """注册外部工具到本地MCP"""
        tool_name = tool_def["name"]
        self.tools_cache[tool_name] = tool_def

        # 创建工具描述
        description = tool_def.get("description", "")
        input_schema = tool_def.get("inputSchema", {})

        # 创建异步包装器
        async def external_tool_wrapper(**kwargs):
            return await self._execute_external_tool(tool_name, kwargs)

        # 注册到MCP
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
                    result = response["result"]

                    # 检查是否有错误标记
                    if result.get("isError", False):
                        content = result.get("content", [])
                        if content and len(content) > 0:
                            error_text = content[0].get("text", "Unknown error")
                            return ToolResult.error(error_text, error_code="TOOL_ERROR")

                    # 提取文本内容
                    content = result.get("content", [])
                    if content and len(content) > 0:
                        text_content = []
                        for item in content:
                            if item.get("type") == "text":
                                text_content.append(item.get("text", ""))

                        if text_content:
                            combined_text = "\n".join(text_content)
                            # 记录识别的文字长度
                            logger.info(
                                f"OCR tool '{tool_name}' recognized text length: {len(combined_text)} characters"
                            )
                            # 打印前100个字符用于调试
                            preview = combined_text[:100] if len(combined_text) > 100 else combined_text
                            logger.debug(f"OCR text preview: {preview}")
                            return ToolResult.success(combined_text)

                    return ToolResult.success(str(result))

            return ToolResult.error(
                "No response from external MCP",
                error_code="NO_RESPONSE"
            )

        except asyncio.TimeoutError:
            error_msg = f"Tool '{tool_name}' execution timed out"
            logger.error(error_msg)
            return ToolResult.error(error_msg, error_code="TIMEOUT")
        except Exception as e:
            error_msg = f"Error executing external tool '{tool_name}': {e}"
            logger.error(error_msg)
            return ToolResult.error(error_msg, error_code="EXECUTION_ERROR")

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
                await self.websocket.send(json_str)
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
            raise
        except Exception as e:
            logger.error(f"Error sending request to '{self.name}': {e}")
            # 清理pending request
            self.pending_requests.pop(request_id, None)
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
            info["is_connected"] = self.websocket is not None and not self.websocket.closed
        else:  # stdio
            info["is_running"] = self.process is not None and self.process.returncode is None

        return info
