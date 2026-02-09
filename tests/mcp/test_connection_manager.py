"""
Tests for MCP Connection Manager
"""

import pytest
from fastapi import WebSocket
from src.mcp.connection_manager import ConnectionManager


@pytest.mark.asyncio
async def test_connect_and_disconnect():
    """测试连接和断开"""
    manager = ConnectionManager()

    # 创建模拟WebSocket
    # 注意：实际测试需要使用TestClient的websocket

    client_id = "test-client-1"
    client_info = {
        "name": "Test Client",
        "tenant_id": 1
    }

    # 测试断开
    manager.disconnect(client_id)

    assert not manager.is_connected(client_id)
    assert manager.get_connection_count() == 0


@pytest.mark.asyncio
async def test_get_client_info():
    """测试获取客户端信息"""
    manager = ConnectionManager()

    client_id = "test-client-1"
    client_info = {
        "name": "Test Client",
        "tenant_id": 1
    }

    # 手动设置（模拟连接）
    manager.client_info[client_id] = client_info

    retrieved = manager.get_client_info(client_id)
    assert retrieved["name"] == "Test Client"
    assert retrieved["tenant_id"] == 1


@pytest.mark.asyncio
async def test_get_connection_count():
    """测试获取连接数"""
    manager = ConnectionManager()

    # 初始状态
    assert manager.get_connection_count() == 0

    # 手动添加几个客户端
    manager.active_connections["client-1"] = None
    manager.active_connections["client-2"] = None
    manager.active_connections["client-3"] = None

    assert manager.get_connection_count() == 3


@pytest.mark.asyncio
async def test_get_all_clients():
    """测试获取所有客户端"""
    manager = ConnectionManager()

    client_1 = {"name": "Client 1", "tenant_id": 1}
    client_2 = {"name": "Client 2", "tenant_id": 2}

    manager.client_info["client-1"] = client_1
    manager.client_info["client-2"] = client_2

    all_clients = manager.get_all_clients()

    assert len(all_clients) == 2
    assert "client-1" in all_clients
    assert "client-2" in all_clients
    assert all_clients["client-1"]["name"] == "Client 1"
