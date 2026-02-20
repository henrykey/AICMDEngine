"""
WebSocket notification service for real-time capability detection updates.
Keeps frontend UI synchronized with detection status changes.
"""

from fastapi import WebSocket
from typing import List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class NotificationService:
    """WebSocket notification service"""

    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        """Accept and track WebSocket connection"""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        """Remove disconnected WebSocket"""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket disconnected. Total: {len(self.active_connections)}")

    async def notify_detection_status(self, provider_name: str, status: str):
        """Broadcast detection status change"""
        message = {
            "type": "capability_detection_status",
            "provider_name": provider_name,
            "status": status,
            "timestamp": datetime.utcnow().isoformat()
        }
        await self._broadcast(message)

    async def notify_capability_update(self, provider_name: str, capabilities: dict):
        """Broadcast capability update"""
        message = {
            "type": "capability_update",
            "provider_name": provider_name,
            "capabilities": capabilities,
            "timestamp": datetime.utcnow().isoformat()
        }
        await self._broadcast(message)

    async def _broadcast(self, message: dict):
        """Broadcast to all connected clients"""
        if not self.active_connections:
            return

        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"WebSocket send error: {e}")
                disconnected.append(connection)

        # Cleanup disconnected
        for conn in disconnected:
            self.active_connections.remove(conn)
