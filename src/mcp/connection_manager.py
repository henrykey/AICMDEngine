"""
WebSocket Connection Manager for MCP Router

Manages WebSocket connections, client info, and message routing.
"""

from typing import Dict, Optional
import asyncio
from fastapi import WebSocket
import logging

logger = logging.getLogger(__name__)


class ConnectionManager:
    """WebSocket连接管理器"""

    def __init__(self):
        """Initialize connection manager"""
        # client_id -> WebSocket
        self.active_connections: Dict[str, WebSocket] = {}
        # client_id -> client_info
        self.client_info: Dict[str, dict] = {}
        # client_id -> send lock
        self._send_locks: Dict[str, asyncio.Lock] = {}

    async def connect(
        self,
        websocket: WebSocket,
        client_id: str,
        client_info: dict
    ):
        """
        接受新连接

        Args:
            websocket: FastAPI WebSocket connection
            client_id: Unique client identifier
            client_info: Client information dict
        """
        await websocket.accept()
        self.active_connections[client_id] = websocket
        self.client_info[client_id] = client_info

        logger.info(
            f"Client connected: {client_id} "
            f"({client_info.get('name', 'Unknown')})"
        )

    def disconnect(self, client_id: str, websocket: Optional[WebSocket] = None):
        """
        断开连接

        Args:
            client_id: Client identifier to disconnect
            websocket: Optional websocket instance to verify ownership
        """
        current = self.active_connections.get(client_id)
        if websocket is not None and current is not websocket:
            return

        if current:
            try:
                logger.info(f"Client disconnected: {client_id}")
            finally:
                del self.active_connections[client_id]
        if client_id in self.client_info:
            del self.client_info[client_id]
        if client_id in self._send_locks:
            del self._send_locks[client_id]
        else:
            logger.info(f"Client disconnected: {client_id}")

    async def send_message(
        self,
        client_id: str,
        message: dict
    ) -> bool:
        """
        发送消息给指定客户端

        Args:
            client_id: Target client identifier
            message: Message dict to send

        Returns:
            bool: True if sent successfully, False otherwise
        """
        websocket = self.active_connections.get(client_id)
        if not websocket:
            logger.warning(f"Client not found: {client_id}")
            return False

        lock = self._send_locks.get(client_id)
        if lock is None:
            lock = asyncio.Lock()
            self._send_locks[client_id] = lock

        try:
            async with lock:
                await websocket.send_json(message)
            return True
        except Exception as e:
            logger.error(f"Failed to send message to {client_id}: {e}")
            self.disconnect(client_id, websocket)
            return False

    async def broadcast(self, message: dict):
        """
        广播消息给所有连接的客户端

        Args:
            message: Message dict to broadcast
        """
        disconnected = []
        for client_id, websocket in self.active_connections.items():
            try:
                await self.send_message(client_id, message)
            except Exception as e:
                logger.error(f"Failed to broadcast to {client_id}: {e}")
                disconnected.append(client_id)

        # 清理断开的连接
        for client_id in disconnected:
            self.disconnect(client_id)

    def get_connection_count(self) -> int:
        """
        获取当前连接数

        Returns:
            int: Number of active connections
        """
        return len(self.active_connections)

    def get_client_info(self, client_id: str) -> dict:
        """
        获取客户端信息

        Args:
            client_id: Client identifier

        Returns:
            dict: Client information, or empty dict if not found
        """
        return self.client_info.get(client_id, {})

    def is_connected(self, client_id: str) -> bool:
        """
        检查客户端是否连接

        Args:
            client_id: Client identifier

        Returns:
            bool: True if connected, False otherwise
        """
        return client_id in self.active_connections

    def get_all_clients(self) -> Dict[str, dict]:
        """
        获取所有连接的客户端信息

        Returns:
            dict: All client info keyed by client_id
        """
        return self.client_info.copy()
