"""Tests for WebSocket notification service"""

import pytest
from fastapi.testclient import TestClient
from src.main import app
from src.routers.websocket import NotificationService


def test_websocket_connection():
    """Test basic WebSocket connection and ping/pong"""
    client = TestClient(app)

    with client.websocket_connect("/api/llm/ws/notifications") as websocket:
        websocket.send_json({"type": "ping"})
        data = websocket.receive_json()
        assert data["type"] == "pong"


def test_notification_service():
    """Test notification service basic operations"""
    service = NotificationService()

    # Test that service can be instantiated
    assert service.active_connections == []
    assert len(service.active_connections) == 0
