#!/usr/bin/env python3
"""
MCP HTTP/SSE Proxy Server

将 stdio MCP 服务器（进程或 Docker 容器）转换为 HTTP/SSE 服务器（MCP 标准协议），
使 MCP Router 可以通过网络连接外部 MCP。

用法:
    python -m src

支持两种模式:
    1. 进程模式 (type: process) - 启动本地 stdio MCP 进程（默认）
    2. 容器模式 (type: docker) - 连接到 Docker 容器中的 stdio MCP

协议: Legacy MCP SSE
    GET  /sse                      → 建立 SSE 流，返回 endpoint event
    POST /messages?session_id=xxx  → 转发 JSON-RPC 到 stdio，响应通过 SSE 返回
"""

import asyncio
import json
import logging
import os
import signal
import sys
import uuid
from pathlib import Path
from typing import Dict, Any, Optional

import yaml
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MCPServerWrapper:
    """包装一个 stdio MCP 进程，提供 HTTP/SSE 接口（Legacy MCP SSE 协议）"""

    def __init__(self, name: str, config: Dict[str, Any]):
        self.name = name
        self.port = config['port']
        self.server_type = config.get('type', 'process')

        if self.server_type == 'process':
            self.cwd = config.get('cwd', '.')
            self.command = config['command']
            self.args = config.get('args', [])
            self.env_vars = config.get('env', {})
        elif self.server_type == 'docker':
            self.container_name = config['container']
            self.container_cmd = config.get('command', [])
        else:
            raise ValueError(f"Unknown server type: {self.server_type}")

        self.timeout = config.get('timeout', 300)
        self.process: Optional[asyncio.subprocess.Process] = None
        # session_id -> asyncio.Queue（各 SSE 连接的响应队列）
        self.sessions: Dict[str, asyncio.Queue] = {}
        # req_id -> Future（用于 /mcp streamable-http 端点的同步响应等待）
        self.mcp_pending: Dict[Any, asyncio.Future] = {}
        self._read_task: Optional[asyncio.Task] = None
        self._server: Optional[uvicorn.Server] = None
        self.is_running = False

    # ------------------------------------------------------------------
    # stdio 进程管理
    # ------------------------------------------------------------------

    async def _start_process(self):
        """启动本地 stdio MCP 进程"""
        env = os.environ.copy()
        env.update(self.env_vars)
        full_cmd = self.command + self.args
        logger.info(f"Starting stdio MCP '{self.name}': {' '.join(full_cmd)}")
        self.process = await asyncio.create_subprocess_exec(
            *full_cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.cwd),
            env=env,
        )
        logger.info(f"Started '{self.name}' PID={self.process.pid}")

    async def _start_docker_container(self):
        """通过 docker exec 连接到容器内 stdio MCP"""
        cmd = ["docker", "exec", "-i", self.container_name]
        if self.container_cmd:
            cmd.extend(self.container_cmd)
        logger.info(f"Executing in container: {' '.join(cmd)}")
        self.process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        logger.info(f"Connected to container '{self.container_name}' PID={self.process.pid}")

    async def _read_stdio_loop(self):
        """持续读取 stdio 输出，广播到所有 SSE 会话"""
        try:
            async def drain_stderr():
                while True:
                    line = await self.process.stderr.readline()
                    if not line:
                        break
                    logger.debug(f"[{self.name}] stderr: {line.decode().rstrip()}")

            asyncio.create_task(drain_stderr())

            while True:
                line = await self.process.stdout.readline()
                if not line:
                    logger.warning(f"[{self.name}] stdio stdout closed")
                    break
                text = line.decode().strip()
                if not text:
                    continue
                logger.debug(f"[{self.name}] stdout → SSE: {text[:120]}")
                # 广播到所有 SSE 会话队列
                for q in list(self.sessions.values()):
                    await q.put(text)
                # 同时解析是否有等待中的 /mcp 同步请求
                try:
                    msg = json.loads(text)
                    req_id = msg.get("id")
                    if req_id is not None and req_id in self.mcp_pending:
                        fut = self.mcp_pending.pop(req_id)
                        if not fut.done():
                            fut.set_result(msg)
                except (json.JSONDecodeError, Exception):
                    pass
        except Exception as e:
            logger.error(f"[{self.name}] stdio read error: {e}")

    # ------------------------------------------------------------------
    # HTTP/SSE 端点
    # ------------------------------------------------------------------

    async def sse_endpoint(self, request: Request) -> StreamingResponse:
        """GET /sse — 建立 SSE 流，向客户端发送 message endpoint"""
        session_id = str(uuid.uuid4())
        queue: asyncio.Queue = asyncio.Queue()
        self.sessions[session_id] = queue
        logger.info(f"[{self.name}] SSE session opened: {session_id}")

        message_url = f"/messages?session_id={session_id}"

        async def event_stream():
            try:
                yield f"event: endpoint\ndata: {message_url}\n\n"
                logger.info(f"[{self.name}] SSE sent endpoint: {message_url}")
                while True:
                    try:
                        data = await asyncio.wait_for(queue.get(), timeout=30.0)
                        yield f"event: message\ndata: {data}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
            except Exception as e:
                logger.debug(f"[{self.name}] SSE session {session_id} closed: {e}")
            finally:
                self.sessions.pop(session_id, None)
                logger.info(f"[{self.name}] SSE session removed: {session_id}")

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    async def messages_endpoint(self, request: Request) -> Response:
        """POST /messages?session_id=xxx — 接收 JSON-RPC，转发到 stdio"""
        session_id = request.query_params.get("session_id")
        logger.info(f"[{self.name}] POST /messages session_id={session_id!r}, active_sessions={list(self.sessions.keys())}")
        if not session_id or session_id not in self.sessions:
            return Response(content="Unknown session", status_code=404)

        body = await request.body()
        logger.debug(f"[{self.name}] POST /messages → stdio: {body[:120]}")

        if self.process is None or self.process.returncode is not None:
            return Response(content="Backend process not running", status_code=503)

        self.process.stdin.write(body + b"\n")
        await self.process.stdin.drain()
        return Response(status_code=202)

    async def mcp_endpoint(self, request: Request) -> Response:
        """POST /mcp — streamable-http 端点，直接转发 JSON-RPC 并等待响应。

        这使 MCP Router 的 streamable-http 客户端也能工作，无需 SSE 长连接。
        流程:
          1. 读取 JSON-RPC 请求体
          2. 注册一个 Future 等待对应 id 的响应
          3. 写入 stdio 进程 stdin
          4. 等待 _read_stdio_loop 把响应广播到 mcp_pending dict
          5. 返回 JSON 响应
        """
        if self.process is None or self.process.returncode is not None:
            return Response(content="Backend process not running", status_code=503)

        body = await request.body()
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return Response(content="Invalid JSON", status_code=400)

        req_id = payload.get("id")
        method = payload.get("method", "")
        logger.info(f"[{self.name}] POST /mcp method={method} id={req_id}")
        logger.info(f"[{self.name}] /mcp body: {body.decode()[:500]}")

        # 通知类请求（无 id）直接写入 stdin 不等待响应
        if req_id is None:
            self.process.stdin.write(body + b"\n")
            await self.process.stdin.drain()
            return Response(status_code=202)

        # 注册 Future 等待响应
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self.mcp_pending[req_id] = fut

        try:
            self.process.stdin.write(body + b"\n")
            await self.process.stdin.drain()

            response = await asyncio.wait_for(fut, timeout=self.timeout)
            logger.info(f"[{self.name}] /mcp response: {json.dumps(response)[:500]}")
            return Response(
                content=json.dumps(response),
                media_type="application/json",
            )
        except asyncio.TimeoutError:
            self.mcp_pending.pop(req_id, None)
            logger.error(f"[{self.name}] /mcp timeout for id={req_id}")
            return Response(content="Request timeout", status_code=504)
        except Exception as e:
            self.mcp_pending.pop(req_id, None)
            logger.error(f"[{self.name}] /mcp error: {e}")
            return Response(content=str(e), status_code=500)

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def _stdio_handshake(self):
        """在 stdio 进程启动后立即完成 MCP initialize 握手。
        
        stdio MCP 进程（如 paddleocr_mcp）要求：
        1. 收到 initialize 请求并回复
        2. 收到 notifications/initialized 通知
        才能开始处理 tools/list、tools/call 等请求。
        """
        logger.info(f"[{self.name}] Performing MCP initialize handshake with stdio process...")

        # 注册 Future 等待 initialize 响应
        req_id = 0
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self.mcp_pending[req_id] = fut

        init_request = json.dumps({
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                "clientInfo": {"name": "mcp-proxy", "version": "1.0.0"}
            }
        }).encode()

        self.process.stdin.write(init_request + b"\n")
        await self.process.stdin.drain()

        try:
            response = await asyncio.wait_for(fut, timeout=30.0)
            server_info = response.get("result", {}).get("serverInfo", {})
            logger.info(
                f"[{self.name}] stdio handshake OK: "
                f"{server_info.get('name', 'Unknown')} v{server_info.get('version', 'Unknown')}"
            )
        except asyncio.TimeoutError:
            logger.error(f"[{self.name}] stdio handshake timed out!")
            raise RuntimeError(f"MCP stdio handshake timeout for '{self.name}'")

        # 发送 initialized 通知（无需等待响应）
        notif = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode()
        self.process.stdin.write(notif + b"\n")
        await self.process.stdin.drain()
        logger.info(f"[{self.name}] Sent notifications/initialized")

    async def start(self):
        """启动 stdio 进程 + 握手初始化 + HTTP/SSE 服务器"""
        if self.server_type == 'process':
            await self._start_process()
        elif self.server_type == 'docker':
            await self._start_docker_container()

        self._read_task = asyncio.create_task(self._read_stdio_loop())

        # stdio MCP 进程启动后必须先完成 initialize 握手才能接受其他请求
        await self._stdio_handshake()

        app = Starlette(routes=[
            Route("/sse", self.sse_endpoint, methods=["GET"]),
            Route("/messages", self.messages_endpoint, methods=["POST"]),
            Route("/mcp", self.mcp_endpoint, methods=["POST"]),
        ])
        config = uvicorn.Config(app, host="0.0.0.0", port=self.port, log_level="warning")
        self._server = uvicorn.Server(config)
        asyncio.create_task(self._server.serve())
        self.is_running = True
        logger.info(f"✅ HTTP/SSE proxy for '{self.name}' → http://0.0.0.0:{self.port}/sse")

    async def stop(self):
        if self._server:
            self._server.should_exit = True
        if self._read_task:
            self._read_task.cancel()
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
        self.is_running = False
        logger.info(f"[{self.name}] stopped")


class MCPProxyManager:
    """管理多个 MCPServerWrapper"""

    def __init__(self, config_path: str):
        self.config_path = Path(config_path)
        self.wrappers: Dict[str, MCPServerWrapper] = {}

    def load_config(self) -> Dict[str, Any]:
        logger.info(f"Loading configuration from {self.config_path}")
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config not found: {self.config_path}")
        with open(self.config_path) as f:
            return yaml.safe_load(f)

    def initialize_wrappers(self, config: Dict[str, Any]):
        base_path = self.config_path.parent
        servers = config.get('servers', [])
        logger.info(f"Initializing {len(servers)} MCP servers...")
        for sc in servers:
            name = sc['name']
            if 'cwd' in sc and not Path(sc['cwd']).is_absolute():
                sc['cwd'] = str(base_path / sc['cwd'])
            logger.info(f"  - '{name}' on port {sc['port']}")
            self.wrappers[name] = MCPServerWrapper(name, sc)

    async def start_all(self):
        await asyncio.gather(*[w.start() for w in self.wrappers.values()])
        logger.info("=" * 60)
        logger.info("✅ MCP HTTP/SSE Proxy is running!")
        logger.info("Available MCP servers (Legacy SSE):")
        for name, w in self.wrappers.items():
            logger.info(f"  - {name}: http://localhost:{w.port}/sse")
        logger.info("=" * 60)

    async def stop_all(self):
        await asyncio.gather(*[w.stop() for w in self.wrappers.values()], return_exceptions=True)

    async def run(self):
        await self.start_all()
        stop_event = asyncio.Event()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: stop_event.set())

        await stop_event.wait()
        await self.stop_all()


async def main():
    config_path = Path(__file__).parent.parent / "config" / "mcp-proxy-config.yml"
    if not config_path.exists():
        logger.error(f"Config not found: {config_path}")
        sys.exit(1)

    manager = MCPProxyManager(str(config_path))
    try:
        config = manager.load_config()
        manager.initialize_wrappers(config)
        await manager.run()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

