"""Tests for GET /providers endpoint with capability status"""

import pytest
from unittest.mock import Mock
from src.routers.llm import list_providers
from src.llm.config_loader import LLMConfig
from datetime import datetime


@pytest.fixture
def mock_manager():
    """Mock provider manager with capability detection status"""
    manager = Mock()
    manager.get_current_provider.return_value = "gpt-4o"
    manager.clients = {"gpt-4o": Mock(), "claude-3-opus": Mock()}

    # Create provider with detection status
    provider1 = LLMConfig(
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

    provider2 = LLMConfig(
        name="claude-3-opus",
        type="anthropic",
        base_url="https://api.anthropic.com/v1",
        model="claude-3-opus-20240229",
        api_key_ref="ANTHROPIC_API_KEY",
        capabilities=["chat"],
        context_window=200000,
        max_tokens=4096,
        supports_multimodal=False,
        supported_formats=["text"],
        embedding_dimensions=None,
        capabilities_detection_status="failed",
        capabilities_last_updated=datetime(2026, 2, 20, 11, 0, 0),
        capabilities_detection_error="Network timeout"
    )

    manager.get_providers.return_value = {
        "gpt-4o": provider1,
        "claude-3-opus": provider2
    }

    return manager


@pytest.mark.asyncio
async def test_list_providers_includes_capability_status(mock_manager):
    """Test that GET /providers includes capability detection status"""
    result = await list_providers(mock_manager)

    assert "providers" in result
    providers = result["providers"]
    assert len(providers) == 2

    # Check first provider (gpt-4o)
    gpt4o = next(p for p in providers if p["name"] == "gpt-4o")
    assert gpt4o["capabilities"] == ["chat", "vision"]
    assert gpt4o["context_window"] == 128000
    assert gpt4o["supports_multimodal"] is True
    assert gpt4o["supported_formats"] == ["text", "image"]
    assert gpt4o["capabilities_detection_status"] == "completed"
    assert gpt4o["capabilities_last_updated"] == "2026-02-20T12:00:00"
    assert gpt4o["capabilities_detection_error"] is None
    assert gpt4o["is_current"] is True
    assert gpt4o["is_initialized"] is True

    # Check second provider (claude-3-opus)
    claude = next(p for p in providers if p["name"] == "claude-3-opus")
    assert claude["capabilities"] == ["chat"]
    assert claude["context_window"] == 200000
    assert claude["capabilities_detection_status"] == "failed"
    assert claude["capabilities_detection_error"] == "Network timeout"
    assert claude["is_current"] is False
    assert claude["is_initialized"] is True


@pytest.mark.asyncio
async def test_list_providers_uninitialized_provider():
    """Test that uninitialized providers are marked correctly"""
    manager = Mock()
    manager.get_current_provider.return_value = "gpt-4o"
    manager.clients = {}  # No clients initialized

    provider = LLMConfig(
        name="gpt-4o",
        type="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4o",
        api_key_ref="OPENAI_API_KEY"
    )

    manager.get_providers.return_value = {"gpt-4o": provider}

    result = await list_providers(manager)

    providers = result["providers"]
    assert len(providers) == 1
    assert providers[0]["is_initialized"] is False
    assert providers[0]["is_current"] is True


@pytest.mark.asyncio
async def test_list_providers_empty():
    """Test listing providers when none exist"""
    manager = Mock()
    manager.get_current_provider.return_value = None
    manager.clients = {}
    manager.get_providers.return_value = {}

    result = await list_providers(manager)

    assert result["providers"] == []


@pytest.mark.asyncio
async def test_list_providers_pending_detection():
    """Test provider with pending detection status"""
    manager = Mock()
    manager.get_current_provider.return_value = None
    manager.clients = {}

    provider = LLMConfig(
        name="new-provider",
        type="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4o",
        api_key_ref="OPENAI_API_KEY",
        capabilities_detection_status="pending",
        capabilities_last_updated=None
    )

    manager.get_providers.return_value = {"new-provider": provider}

    result = await list_providers(manager)

    providers = result["providers"]
    assert len(providers) == 1
    assert providers[0]["capabilities_detection_status"] == "pending"
    assert providers[0]["capabilities_last_updated"] is None
    assert providers[0]["is_initialized"] is False
