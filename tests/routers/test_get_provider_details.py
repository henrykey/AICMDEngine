"""Tests for GET /providers/{name} endpoint with capability details"""

import pytest
from unittest.mock import Mock
from fastapi import HTTPException
from src.routers.llm import get_provider
from src.llm.config_loader import LLMConfig
from datetime import datetime


@pytest.fixture
def mock_manager():
    """Mock provider manager with capability detection status"""
    manager = Mock()
    manager.get_current_provider.return_value = "gpt-4o"
    manager.clients = {"gpt-4o": Mock()}

    # Create provider with full capability details
    provider = LLMConfig(
        name="gpt-4o",
        type="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4o",
        api_key_ref="OPENAI_API_KEY",
        capabilities=["chat", "vision"],
        context_window=128000,
        max_tokens=4096,
        supports_multimodal=True,
        supported_formats=["text", "image"],
        embedding_dimensions=None,
        capabilities_detection_status="completed",
        capabilities_last_updated=datetime(2026, 2, 20, 12, 0, 0),
        capabilities_detection_error=None
    )

    manager.get_provider_info.return_value = provider.to_dict()
    manager.get_provider_info.return_value.update({
        "cost_accumulated": 0.5,
        "is_current": True,
        "is_initialized": True,
    })

    return manager


@pytest.mark.asyncio
async def test_get_provider_includes_capability_details(mock_manager):
    """Test that GET /providers/{name} includes full capability information"""
    result = await get_provider("gpt-4o", mock_manager)

    # Verify basic provider info
    assert result["name"] == "gpt-4o"
    assert result["type"] == "openai"
    assert result["model"] == "gpt-4o"
    assert result["base_url"] == "https://api.openai.com/v1"

    # Verify capability fields are present
    assert result["capabilities"] == ["chat", "vision"]
    assert result["context_window"] == 128000
    assert result["supports_multimodal"] is True
    assert result["supported_formats"] == ["text", "image"]
    assert result["embedding_dimensions"] is None

    # Verify detection status fields are present
    assert result["capabilities_detection_status"] == "completed"
    assert result["capabilities_last_updated"] == "2026-02-20T12:00:00"
    assert result["capabilities_detection_error"] is None

    # Verify status fields
    assert result["is_current"] is True
    assert result["is_initialized"] is True
    assert result["cost_accumulated"] == 0.5


@pytest.mark.asyncio
async def test_get_provider_with_failed_detection():
    """Test GET /providers/{name} with failed detection status"""
    manager = Mock()
    manager.get_current_provider.return_value = "claude-3-opus"
    manager.clients = {}

    provider = LLMConfig(
        name="claude-3-opus",
        type="anthropic",
        base_url="https://api.anthropic.com/v1",
        model="claude-3-opus-20240229",
        api_key_ref="ANTHROPIC_API_KEY",
        capabilities_detection_status="failed",
        capabilities_last_updated=datetime(2026, 2, 20, 11, 0, 0),
        capabilities_detection_error="Network timeout"
    )

    manager.get_provider_info.return_value = provider.to_dict()
    manager.get_provider_info.return_value.update({
        "cost_accumulated": 0.0,
        "is_current": True,
        "is_initialized": False,
    })

    result = await get_provider("claude-3-opus", manager)

    # Verify failed detection status is included
    assert result["capabilities_detection_status"] == "failed"
    assert result["capabilities_detection_error"] == "Network timeout"
    assert result["capabilities_last_updated"] == "2026-02-20T11:00:00"
    assert result["is_initialized"] is False


@pytest.mark.asyncio
async def test_get_provider_not_found():
    """Test GET /providers/{name} with non-existent provider"""
    manager = Mock()
    manager.get_provider_info.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        await get_provider("nonexistent", manager)

    assert exc_info.value.status_code == 404
    assert "not found" in exc_info.value.detail


@pytest.mark.asyncio
async def test_get_provider_with_manual_capabilities():
    """Test GET /providers/{name} with manually configured capabilities"""
    manager = Mock()
    manager.get_current_provider.return_value = "custom-provider"
    manager.clients = {"custom-provider": Mock()}

    provider = LLMConfig(
        name="custom-provider",
        type="custom",
        base_url="https://api.custom.com/v1",
        model="custom-model-v1",
        api_key_ref="CUSTOM_API_KEY",
        capabilities=["chat", "code"],
        context_window=32768,
        max_tokens=2048,
        supports_multimodal=False,
        supported_formats=["text"],
        embedding_dimensions=1536,
        capabilities_detection_status="completed"  # Manually set
    )

    manager.get_provider_info.return_value = provider.to_dict()
    manager.get_provider_info.return_value.update({
        "cost_accumulated": 0.1,
        "is_current": True,
        "is_initialized": True,
    })

    result = await get_provider("custom-provider", manager)

    # Verify manually configured capabilities are included
    assert result["capabilities"] == ["chat", "code"]
    assert result["context_window"] == 32768
    assert result["embedding_dimensions"] == 1536
    assert result["supports_multimodal"] is False
    assert result["supported_formats"] == ["text"]
