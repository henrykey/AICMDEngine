"""Tests for manual capability detection endpoint"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from src.routers.llm import detect_provider_capabilities
from fastapi import HTTPException


@pytest.fixture
def mock_manager():
    """Mock provider manager"""
    manager = Mock()
    manager.config_loader = Mock()
    return manager


@pytest.mark.asyncio
async def test_detect_capabilities_success(mock_manager):
    """Test successful capability detection"""
    provider_data = {
        "name": "test-provider",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
        "api_key_ref": "OPENAI_API_KEY"
    }

    # Mock API key retrieval
    mock_manager.config_loader.get_api_key.return_value = "sk-test-key"

    # Mock capability detector
    mock_detected = {
        "capabilities": ["chat", "vision"],
        "context_window": 128000,
        "max_tokens": 4096,
        "supports_multimodal": True,
        "supported_formats": ["text", "image"],
        "embedding_dimensions": None
    }

    with patch('src.llm.capability_detector.CapabilityDetector') as MockDetector:
        mock_detector_instance = Mock()
        mock_detector_instance.detect_capabilities = AsyncMock(return_value=mock_detected)
        MockDetector.return_value = mock_detector_instance

        result = await detect_provider_capabilities(provider_data, mock_manager)

    assert result["success"] is True
    assert result["capabilities"] == mock_detected
    assert result["provider_preview"]["capabilities"] == ["chat", "vision"]
    assert result["provider_preview"]["context_window"] == 128000
    assert result["provider_preview"]["model"] == "gpt-4o"


@pytest.mark.asyncio
async def test_detect_capabilities_missing_base_url(mock_manager):
    """Test detection with missing base_url"""
    provider_data = {
        "model": "gpt-4o"
    }

    mock_manager.config_loader.get_api_key.return_value = "sk-test-key"

    with pytest.raises(HTTPException) as exc_info:
        await detect_provider_capabilities(provider_data, mock_manager)

    assert exc_info.value.status_code == 400
    assert "base_url and model are required" in exc_info.value.detail


@pytest.mark.asyncio
async def test_detect_capabilities_missing_model(mock_manager):
    """Test detection with missing model"""
    provider_data = {
        "base_url": "https://api.openai.com/v1"
    }

    mock_manager.config_loader.get_api_key.return_value = "sk-test-key"

    with pytest.raises(HTTPException) as exc_info:
        await detect_provider_capabilities(provider_data, mock_manager)

    assert exc_info.value.status_code == 400
    assert "base_url and model are required" in exc_info.value.detail


@pytest.mark.asyncio
async def test_detect_capabilities_missing_api_key(mock_manager):
    """Test detection with missing API key"""
    provider_data = {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
        "api_key_ref": "MISSING_KEY"
    }

    # Mock API key not found
    mock_manager.config_loader.get_api_key.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        await detect_provider_capabilities(provider_data, mock_manager)

    assert exc_info.value.status_code == 400
    assert "API key not found" in exc_info.value.detail


@pytest.mark.asyncio
async def test_detect_capabilities_with_auth_token(mock_manager):
    """Test detection using auth_token instead of api_key_ref"""
    provider_data = {
        "base_url": "https://api.anthropic.com/v1",
        "model": "claude-3-opus",
        "auth_token": "sk-ant-test-token"
    }

    # Mock detected capabilities
    mock_detected = {
        "capabilities": ["chat"],
        "context_window": 200000,
        "max_tokens": 4096,
        "supports_multimodal": False,
        "supported_formats": ["text"],
        "embedding_dimensions": None
    }

    with patch('src.llm.capability_detector.CapabilityDetector') as MockDetector:
        mock_detector_instance = Mock()
        mock_detector_instance.detect_capabilities = AsyncMock(return_value=mock_detected)
        MockDetector.return_value = mock_detector_instance

        result = await detect_provider_capabilities(provider_data, mock_manager)

    assert result["success"] is True
    assert result["provider_preview"]["context_window"] == 200000
    # Verify auth_token was used (not api_key_ref)
    mock_manager.config_loader.get_api_key.assert_not_called()


@pytest.mark.asyncio
async def test_detect_capabilities_detector_error(mock_manager):
    """Test detection when detector raises an error"""
    provider_data = {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
        "api_key_ref": "OPENAI_API_KEY"
    }

    mock_manager.config_loader.get_api_key.return_value = "sk-test-key"

    with patch('src.llm.capability_detector.CapabilityDetector') as MockDetector:
        mock_detector_instance = Mock()
        mock_detector_instance.detect_capabilities = AsyncMock(
            side_effect=Exception("Network error")
        )
        MockDetector.return_value = mock_detector_instance

        with pytest.raises(HTTPException) as exc_info:
            await detect_provider_capabilities(provider_data, mock_manager)

    assert exc_info.value.status_code == 500
    assert "Network error" in exc_info.value.detail


@pytest.mark.asyncio
async def test_detect_capabilities_default_values(mock_manager):
    """Test detection returns safe defaults when detection fails gracefully"""
    provider_data = {
        "name": "minimal-provider",
        "base_url": "https://api.test.com/v1",
        "model": "test-model",
        "api_key_ref": "TEST_KEY"
    }

    mock_manager.config_loader.get_api_key.return_value = "test-key"

    # Mock detector returns minimal data
    mock_detected = {
        "capabilities": ["chat"]  # Only basic capability detected
    }

    with patch('src.llm.capability_detector.CapabilityDetector') as MockDetector:
        mock_detector_instance = Mock()
        mock_detector_instance.detect_capabilities = AsyncMock(return_value=mock_detected)
        MockDetector.return_value = mock_detector_instance

        result = await detect_provider_capabilities(provider_data, mock_manager)

    # Verify defaults are set
    preview = result["provider_preview"]
    assert preview["context_window"] == 4096  # Default
    assert preview["max_tokens"] == 2048  # Default
    assert preview["supports_multimodal"] is False  # Default
    assert preview["supported_formats"] == []  # Default
    assert preview["embedding_dimensions"] is None
