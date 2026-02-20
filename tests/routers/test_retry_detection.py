"""Tests for retry provider detection endpoint"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from src.routers.llm import retry_provider_detection
from src.llm.config_loader import LLMConfig
from fastapi import HTTPException


@pytest.fixture
def mock_manager():
    """Mock provider manager"""
    manager = Mock()
    manager.get_provider = Mock()
    return manager


@pytest.fixture
def mock_provider():
    """Mock LLM provider config"""
    return LLMConfig(
        name="test-provider",
        type="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4o",
        api_key_ref="OPENAI_API_KEY"
    )


@pytest.mark.asyncio
async def test_retry_detection_success(mock_manager, mock_provider):
    """Test successful retry of provider detection"""
    # Mock provider exists
    mock_manager.get_provider.return_value = mock_provider

    # Mock async detector
    mock_detector = Mock()
    mock_detector.start_detection = AsyncMock(return_value="detect_test-provider_1234567890")

    with patch('src.routers.llm.async_detector', mock_detector):
        result = await retry_provider_detection("test-provider", mock_manager)

    assert result["success"] is True
    assert result["provider"] == "test-provider"
    assert result["task_id"] == "detect_test-provider_1234567890"
    assert "restarted" in result["message"].lower()

    # Verify detection was started
    mock_detector.start_detection.assert_called_once()


@pytest.mark.asyncio
async def test_retry_detection_provider_not_found(mock_manager):
    """Test retry detection for non-existent provider"""
    # Mock provider doesn't exist
    mock_manager.get_provider.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        await retry_provider_detection("nonexistent", mock_manager)

    assert exc_info.value.status_code == 404
    assert "not found" in exc_info.value.detail


@pytest.mark.asyncio
async def test_retry_detection_no_detector(mock_manager, mock_provider):
    """Test retry detection when async detector not initialized"""
    # Mock provider exists
    mock_manager.get_provider.return_value = mock_provider

    # Mock async detector is None
    with patch('src.routers.llm.async_detector', None):
        with pytest.raises(HTTPException) as exc_info:
            await retry_provider_detection("test-provider", mock_manager)

    assert exc_info.value.status_code == 500
    assert "not initialized" in exc_info.value.detail


@pytest.mark.asyncio
async def test_retry_detection_start_error(mock_manager, mock_provider):
    """Test retry detection when detector raises error"""
    # Mock provider exists
    mock_manager.get_provider.return_value = mock_provider

    # Mock detector that raises error
    mock_detector = Mock()
    mock_detector.start_detection = AsyncMock(
        side_effect=Exception("Database connection error")
    )

    with patch('src.routers.llm.async_detector', mock_detector):
        with pytest.raises(HTTPException) as exc_info:
            await retry_provider_detection("test-provider", mock_manager)

    assert exc_info.value.status_code == 500
    assert "Database connection error" in exc_info.value.detail


@pytest.mark.asyncio
async def test_retry_detection_with_detection_status(mock_manager, mock_provider):
    """Test retry detection preserves provider data"""
    # Add detection status to provider
    mock_provider.capabilities_detection_status = "failed"
    mock_provider.capabilities_detection_error = "Network timeout"

    mock_manager.get_provider.return_value = mock_provider

    # Mock async detector
    mock_detector = Mock()
    mock_detector.start_detection = AsyncMock(return_value="detect_test-provider_9876543210")

    with patch('src.routers.llm.async_detector', mock_detector):
        result = await retry_provider_detection("test-provider", mock_manager)

    assert result["success"] is True

    # Verify provider data was passed to detector
    call_args = mock_detector.start_detection.call_args
    provider_data = call_args[0][1]  # Second positional argument

    assert provider_data["name"] == "test-provider"
    assert provider_data["base_url"] == "https://api.openai.com/v1"
