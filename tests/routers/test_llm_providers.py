"""Tests for LLM provider endpoints with capability detection"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, AsyncMock, patch
from src.main import app
from src.routers.llm import get_provider_manager, async_detector


@pytest.fixture
def mock_manager():
    """Mock provider manager"""
    manager = Mock()
    manager.get_providers.return_value = {}
    manager.db_client = Mock()
    manager.config_loader = Mock()
    manager.config_loader.load_from_mongodb = AsyncMock(return_value={})
    manager.initialize = AsyncMock()
    return manager


@pytest.fixture
def mock_async_detector():
    """Mock async capability detector"""
    detector = Mock()
    detector.start_detection = AsyncMock(return_value="detect_test-provider_1234567890")
    return detector


@pytest.mark.asyncio
async def test_create_provider_auto_detection(mock_manager, mock_async_detector):
    """Test creating provider without capabilities (auto-detection mode)"""
    from src.routers.llm import create_provider

    provider_data = {
        "name": "test-provider",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
        "api_key_ref": "OPENAI_API_KEY",
        "provider_type": "openai"
    }

    # Mock MongoDB operations
    mock_collection = Mock()
    mock_collection.insert_one = AsyncMock()
    mock_manager.db_client.nl_tps.llm_providers = mock_collection

    # Patch async_detector
    with patch('src.routers.llm.async_detector', mock_async_detector):
        result = await create_provider(provider_data, mock_manager)

    assert result["success"] is True
    assert result["action"] == "created"
    assert result["capabilities_mode"] == "auto"
    assert result["capabilities_detection_status"] == "pending"

    # Verify async detection was started
    mock_async_detector.start_detection.assert_called_once()


@pytest.mark.asyncio
async def test_create_provider_manual_capabilities(mock_manager, mock_async_detector):
    """Test creating provider with manual capabilities (manual mode)"""
    from src.routers.llm import create_provider

    provider_data = {
        "name": "test-provider-manual",
        "base_url": "https://api.anthropic.com/v1",
        "model": "claude-3-opus",
        "api_key_ref": "ANTHROPIC_API_KEY",
        "provider_type": "anthropic",
        "capabilities": ["chat", "vision"],
        "context_window": 200000,
        "max_tokens": 4096,
        "supports_multimodal": True
    }

    # Mock MongoDB operations
    mock_collection = Mock()
    mock_collection.insert_one = AsyncMock()
    mock_manager.db_client.nl_tps.llm_providers = mock_collection

    # Patch async_detector
    with patch('src.routers.llm.async_detector', mock_async_detector):
        result = await create_provider(provider_data, mock_manager)

    assert result["success"] is True
    assert result["action"] == "created"
    # Manual mode should not include these fields
    assert "capabilities_mode" not in result
    assert "capabilities_detection_status" not in result

    # Verify async detection was NOT started
    mock_async_detector.start_detection.assert_not_called()


@pytest.mark.asyncio
async def test_create_provider_missing_name():
    """Test creating provider without name raises HTTPException"""
    from src.routers.llm import create_provider
    from fastapi import HTTPException

    mock_manager = Mock()
    mock_manager.get_providers.return_value = {}

    provider_data = {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o"
    }

    with pytest.raises(HTTPException) as exc_info:
        await create_provider(provider_data, mock_manager)

    assert exc_info.value.status_code == 400
    assert "Provider name is required" in exc_info.value.detail


@pytest.mark.asyncio
async def test_create_provider_defaults_set(mock_manager, mock_async_detector):
    """Test that safe defaults are set in auto-detection mode"""
    from src.routers.llm import create_provider

    provider_data = {
        "name": "test-provider-defaults",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o"
    }

    # Mock MongoDB operations
    mock_collection = Mock()
    mock_collection.insert_one = AsyncMock()
    mock_manager.db_client.nl_tps.llm_providers = mock_collection

    # Patch async_detector
    with patch('src.routers.llm.async_detector', mock_async_detector):
        result = await create_provider(provider_data, mock_manager)

    provider = result["provider"]

    # Verify defaults were set
    assert provider["capabilities"] == ["chat"]
    assert provider["context_window"] == 4096
    assert provider["max_tokens"] == 2048
    assert provider["supports_multimodal"] is False
    assert provider["supported_formats"] == []
