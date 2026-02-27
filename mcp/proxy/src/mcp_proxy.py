#!/usr/bin/env python3
"""
MCP WebSocket Proxy Server

将 stdio MCP 服务器（进程或 Docker 容器）转换为 WebSocket 服务器，
使 MCP Router 可以通过网络连接外部 MCP。

用法:
    python -m mcp_proxy

支持两种模式:
    1. 进程模式 (type: process) - 启动本地 stdio MCP 进程
    2. 容器模式 (type: docker) - 连接到 Docker 容器中的 stdio MCP
"""

import asyncio
import json
import logging
import signal
import sys
from pathlib import Path
from typing import Dict, Any, Optional, List

import websockets
import yaml
import aiohttp

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class DockerContainerManager:
    """管理 Docker 容器中的 MCP 服务器"""

    def __init__(self, container_name: str):
        """
        初始化 Docker 容器管理器

        Args:
            container_name: Docker 容器名称
        """
        self.container_name = container_name
        self.docker_api = None

    async def _get_docker_session(self):
        """获取 aiohttp session 用于 Docker API 调用"""
        if self.docker_api is None:
            self.docker_api = aiohttp.ClientSession(
                base_url="http://localhost/v1.41",
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self.docker_api

    async def attach_to_container(self):
        """
        附加到 Docker 容器的 stdin/stdout

        Returns:
            (stdin_write, stdout_read, stderr_read)
        """
        session = await self._get_docker_session()

        # 检查容器是否运行
        async with session.get(f"/containers/{self.container_name}/json") as resp:
            if resp.status != 200:
                raise RuntimeError(f"Container {self.container_name} not found")
            container_info = await resp.json()
            if container_info["State"]["Running"] != True:
                raise RuntimeError(f"Container {self.container_name} is not running")

        logger.info(f"Attaching to container '{self.container_name}'")

        # 附加到容器
        async with session.post(
            f"/containers/{self.container_name}/attach",
            params={"stdin": 1, "stdout": 1, "stderr": 1, "stream": 1},
            headers={"Content-Type": "application/json"}
        ) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Failed to attach to container: {await resp.text()}")

            # 返回 WebSocket 连接用于双向通信
            # 注意：这里需要使用 Docker API 的 WebSocket 升级
            # 为简化实现，我们使用 docker exec 命令的方式
            pass

        # 由于 Docker API 的 attach 复杂性，我们使用 docker exec 方式
        # 这样更简单可靠
        return await self._exec_in_container()

    async def _exec_in_container(self):
        """
        在容器中执行命令并返回 stdin/stdout

        Returns:
            (process, stdin_write, stdout_read, stderr_read)
        """
        import os

        # 使用 docker exec 命令
        cmd = [
            "docker", "exec", "-i",  # 交互模式
            self.container_name,
            # 容器中的命令（由配置决定）
        ]

        logger.info(f"Executing in container: {' '.join(cmd)}")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        logger.info(f"Attached to container '{self.container_name}' with PID {process.pid}")
        return process

    async def close(self):
        """关闭 Docker API session"""
        if self.docker_api:
            await self.docker_api.close()
            self.docker_api = None


class MCPServerWrapper:
    """包装一个 stdio MCP 进程或 Docker 容器，提供 WebSocket 接口"""

    def __init__(self, name: str, config: Dict[str, Any]):
        """
        初始化 MCP 服务器包装器

        Args:
            name: MCP 服务器名称
            config: 配置字典，包含:
                - type: "process" 或 "docker"
                - port: WebSocket 端口
                - 对于 type="process":
                    - cwd: 工作目录
                    - command: 启动命令
                    - args: 命令参数
                    - env: 环境变量
                - 对于 type="docker":
                    - container: Docker 容器名称
                    - command: 容器内要执行的命令（可选）
        """
        self.name = name
        self.port = config['port']
        self.server_type = config.get('type', 'process')  # 默认为进程模式

        self.server: Optional[websockets.WebSocketServer] = None
        self.is_running = False

        # 进程模式配置
        if self.server_type == 'process':
            self.cwd = config.get('cwd', '.')
            self.command = config['command']
            self.args = config.get('args', [])
            self.env = config.get('env', {})
            self.docker_manager = None
        # Docker 容器模式配置
        elif self.server_type == 'docker':
            self.container_name = config['container']
            self.container_cmd = config.get('command', [])
            self.docker_manager = DockerContainerManager(self.container_name)
        else:
            raise ValueError(f"Unknown server type: {self.server_type}")

    async def handle_client(self, websocket):
        """处理客户端 WebSocket 连接"""
        logger.info(f"New WebSocket connection for '{self.name}' from {websocket.remote_address}")

        # 启动 stdio MCP 进程
        process = await self._start_stdio_process()

        try:
            # 创建两个转发任务
            receive_task = asyncio.create_task(
                self._forward_stdio_to_websocket(process, websocket)
            )
            send_task = asyncio.create_task(
                self._forward_websocket_to_stdio(websocket, process)
            )

            # 等待两个任务都完成（而不是任一完成）
            # 这样可以确保只要 WebSocket 或 stdio 有一个保持打开，进程就能继续运行
            # 当 PaddleOCR 等处理延迟时，stdout 暂时没有数据但仍保持打开，
            # 不会导致进程被意外终止
            done, pending = await asyncio.wait(
                [receive_task, send_task],
                return_when=asyncio.ALL_COMPLETED
            )

            # 获取异常信息（如果有）
            for task in done:
                try:
                    await task
                except Exception as e:
                    logger.debug(f"Task exception: {e}")

        except websockets.exceptions.ConnectionClosed:
            logger.info(f"WebSocket connection closed for '{self.name}'")
        except Exception as e:
            logger.error(f"Error handling client for '{self.name}': {e}")
        finally:
            # 清理进程
            if process.returncode is None:
                logger.info(f"Terminating stdio process for '{self.name}'")
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()

    async def _start_stdio_process(self):
        """启动 stdio MCP 进程或连接到 Docker 容器"""
        if self.server_type == 'process':
            return await self._start_process()
        elif self.server_type == 'docker':
            return await self._start_docker_container()
        else:
            raise RuntimeError(f"Unknown server type: {self.server_type}")

    async def _start_process(self):
        """启动本地 stdio MCP 进程"""
        import os
        env = os.environ.copy()
        env.update(self.env)

        logger.info(f"Starting stdio MCP '{self.name}': {' '.join(self.command + self.args)}")

        process = await asyncio.create_subprocess_exec(
            *self.command,
            *self.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.cwd),
            env=env
        )

        logger.info(f"Started stdio process for '{self.name}' with PID {process.pid}")
        return process

    async def _start_docker_container(self):
        """连接到 Docker 容器中的 stdio MCP"""
        logger.info(f"Connecting to Docker container '{self.container_name}' for '{self.name}'")

        # 构建 docker exec 命令
        cmd = ["docker", "exec", "-i", self.container_name]
        if self.container_cmd:
            cmd.extend(self.container_cmd)

        logger.info(f"Executing in container: {' '.join(cmd)}")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        logger.info(f"Connected to container '{self.container_name}' with PID {process.pid}")
        return process

    async def _forward_stdio_to_websocket(self, process, websocket):
        """将 stdio 输出转发到 WebSocket"""
        try:
            # 创建stderr读取任务
            async def read_stderr():
                while True:
                    line = await process.stderr.readline()
                    if not line:
                        break
                    logger.warning(f"{self.name} stderr: {line.decode().strip()}")

            asyncio.create_task(read_stderr())

            while True:
                line = await process.stdout.readline()
                if not line:
                    logger.warning(f"stdio process '{self.name}' closed stdout")
                    break

                line = line.decode().strip()
                if not line:
                    continue

                logger.debug(f"{self.name} -> WebSocket: {line[:100]}...")
                await websocket.send(line)

        except Exception as e:
            logger.error(f"Error forwarding stdio to WebSocket for '{self.name}': {e}")
            raise

    async def _forward_websocket_to_stdio(self, websocket, process):
        """将 WebSocket 消息转发到 stdio 输入"""
        try:
            async for message in websocket:
                logger.debug(f"WebSocket -> {self.name}: {message[:100]}...")
                process.stdin.write((message + '\n').encode())
                await process.stdin.drain()

        except Exception as e:
            logger.error(f"Error forwarding WebSocket to stdio for '{self.name}': {e}")
            raise

    async def start(self):
        """启动 WebSocket 服务器"""
        logger.info(f"Starting WebSocket server for '{self.name}' on port {self.port}")

        self.server = await websockets.serve(
            self.handle_client,
            "0.0.0.0",
            self.port,
            ping_interval=20,
            ping_timeout=120,  # 增加到120秒，适应PaddleOCR等慢速MCP
            max_size=10 * 1024 * 1024  # 10MB
        )

        self.is_running = True
        logger.info(f"✅ WebSocket server for '{self.name}' is running on ws://0.0.0.0:{self.port}")

    async def stop(self):
        """停止 WebSocket 服务器"""
        if self.server:
            logger.info(f"Stopping WebSocket server for '{self.name}'")
            self.server.close()
            await self.server.wait_closed()
            self.is_running = False


class MCPProxyManager:
    """管理多个 MCP 服务器包装器"""

    def __init__(self, config_path: str):
        """
        初始化代理管理器

        Args:
            config_path: 配置文件路径
        """
        self.config_path = Path(config_path)
        self.wrappers: Dict[str, MCPServerWrapper] = {}
        self.is_running = False

    def load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        logger.info(f"Loading configuration from {self.config_path}")

        if not self.config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")

        with open(self.config_path, 'r') as f:
            config = yaml.safe_load(f)

        return config

    def initialize_wrappers(self, config: Dict[str, Any]):
        """初始化所有 MCP 包装器"""
        logger.info(f"Initializing {len(config['servers'])} MCP servers...")

        base_path = self.config_path.parent

        for server_config in config['servers']:
            name = server_config['name']
            port = server_config['port']

            # 处理相对路径
            if 'cwd' in server_config:
                cwd = server_config['cwd']
                if not Path(cwd).is_absolute():
                    server_config['cwd'] = str(base_path / cwd)

            logger.info(f"Initializing MCP '{name}' on port {port}")
            wrapper = MCPServerWrapper(name, server_config)
            self.wrappers[name] = wrapper

        logger.info(f"Initialized {len(self.wrappers)} MCP servers")

    async def start_all(self):
        """启动所有 MCP 服务器"""
        logger.info("Starting all MCP WebSocket servers...")

        tasks = [wrapper.start() for wrapper in self.wrappers.values()]
        await asyncio.gather(*tasks)

        self.is_running = True
        logger.info("=" * 60)
        logger.info("✅ MCP WebSocket Proxy is running!")
        logger.info("=" * 60)
        logger.info("Available MCP servers:")
        for name, wrapper in self.wrappers.items():
            logger.info(f"  - {name}: ws://localhost:{wrapper.port}")
        logger.info("=" * 60)

    async def stop_all(self):
        """停止所有 MCP 服务器"""
        logger.info("Stopping all MCP WebSocket servers...")

        tasks = [wrapper.stop() for wrapper in self.wrappers.values()]
        await asyncio.gather(*tasks, return_exceptions=True)

        self.is_running = False
        logger.info("All MCP WebSocket servers stopped")

    async def run(self):
        """运行代理服务（阻塞）"""
        await self.start_all()

        # 等待中断信号
        stop_event = asyncio.Event()

        def signal_handler():
            logger.info("Received shutdown signal")
            stop_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda s, f: signal_handler())

        await stop_event.wait()
        await self.stop_all()


async def main():
    """主函数"""
    # 配置文件路径
    config_path = Path(__file__).parent.parent / "config" / "mcp-proxy-config.yml"

    if not config_path.exists():
        logger.error(f"Configuration file not found: {config_path}")
        logger.info("Please create a configuration file first.")
        sys.exit(1)

    # 创建并运行代理管理器
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
