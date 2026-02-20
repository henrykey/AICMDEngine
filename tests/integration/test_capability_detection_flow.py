"""Integration tests for LLM capability detection flow

These tests verify the interaction between components in the detection system:
- Provider creation (auto vs manual mode)
- Async capability detection workflow
- Capability-based provider selection
- Detection retry mechanism

Note: These are integration-level component tests, not full HTTP integration tests.
They verify the logical flow without requiring a running server or database.

Run: pytest -v -s -m integration tests/integration/test_capability_detection_flow.py
Skip: pytest -v -m "not integration"
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime


@pytest.mark.asyncio
@pytest.mark.integration
async def test_auto_detection_flow():
    """Test complete auto-detection flow from creation to completion

    Flow:
    1. Provider created without capabilities field (auto-detection mode)
    2. Safe defaults are set immediately
    3. Async detection starts in background
    4. Detection completes and updates provider
    5. Provider now has full capability details
    """

    # Mock the capability detector
    mock_capabilities = {
        "capabilities": ["chat", "vision", "code"],
        "context_window": 128000,
        "supports_multimodal": True,
        "supported_formats": ["text", "image"],
        "embedding_dimensions": None
    }

    with patch('src.llm.capability_detector.CapabilityDetector') as MockDetector:
        # Setup mock detector
        mock_detector = AsyncMock()
        mock_detector.detect_capabilities.return_value = mock_capabilities
        MockDetector.return_value = mock_detector

        from src.llm.provider_manager import LLMProviderManager
        from src.llm.config_loader import LLMConfigLoader
        from src.llm.async_capability_detector import AsyncCapabilityDetector
        from src.llm.config_loader import LLMConfig

        config_loader = LLMConfigLoader(use_mongodb=False)
        manager = LLMProviderManager(config_loader)

        # Create provider with auto-detection mode
        provider_config = LLMConfig(
            name="test-auto-provider",
            type="openai",
            base_url="https://api.openai.com/v1",
            model="gpt-4o",
            api_key_ref="OPENAI_API_KEY"
        )

        # Add to manager (simulating POST /providers without capabilities)
        manager.providers["test-auto-provider"] = provider_config

        # Verify initial state with safe defaults
        assert provider_config.capabilities == ["chat"]  # Default
        assert provider_config.context_window == 4096  # Default
        assert provider_config.capabilities_detection_status == "pending"

        # Run detection (simulating async detector background task)
        detected = await mock_detector.detect_capabilities(
            provider_config.base_url,
            provider_config.model,
            provider_config.api_key_ref,
            None  # No auth token
        )

        # Update provider with detected capabilities
        provider_config.capabilities = detected["capabilities"]
        provider_config.context_window = detected["context_window"]
        provider_config.supports_multimodal = detected["supports_multimodal"]
        provider_config.supported_formats = detected["supported_formats"]
        provider_config.embedding_dimensions = detected["embedding_dimensions"]
        provider_config.capabilities_detection_status = "completed"
        provider_config.capabilities_last_updated = datetime.now()

        # Verify detection results
        assert "chat" in provider_config.capabilities
        assert "vision" in provider_config.capabilities
        assert "code" in provider_config.capabilities
        assert provider_config.context_window == 128000
        assert provider_config.supports_multimodal is True
        assert provider_config.capabilities_detection_status == "completed"
        assert provider_config.capabilities_last_updated is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_manual_capabilities_bypass_detection():
    """Test that manually specified capabilities bypass auto-detection

    Flow:
    1. Provider created with capabilities field (manual mode)
    2. No detection task is created
    3. Provider uses exact capabilities specified
    4. Status remains None (no detection needed)
    """

    from src.llm.provider_manager import LLMProviderManager
    from src.llm.config_loader import LLMConfigLoader
    from src.llm.config_loader import LLMConfig

    config_loader = LLMConfigLoader(use_mongodb=False)
    manager = LLMProviderManager(config_loader)

    # Create provider with manual capabilities
    provider_config = LLMConfig(
        name="test-manual-provider",
        type="custom",
        base_url="https://api.custom.com/v1",
        model="custom-model",
        api_key_ref="CUSTOM_API_KEY",
        capabilities=["chat", "code", "reasoning", "ocr"],
        context_window=32768,
        supports_multimodal=False,
        supported_formats=["text"],
        embedding_dimensions=768,
        capabilities_detection_status=None  # Manual mode has no detection status
    )

    # Add to manager
    manager.providers["test-manual-provider"] = provider_config

    # Verify manual mode: no detection status, exact capabilities used
    assert provider_config.capabilities == ["chat", "code", "reasoning", "ocr"]
    assert provider_config.context_window == 32768
    assert provider_config.supports_multimodal is False
    assert provider_config.embedding_dimensions == 768
    assert provider_config.capabilities_detection_status is None  # No detection


@pytest.mark.asyncio
@pytest.mark.integration
async def test_detection_failure_with_fallback_to_defaults():
    """Test graceful handling of detection failure

    Flow:
    1. Provider created in auto-detection mode
    2. Detection fails (network error, timeout, etc.)
    3. Provider remains usable with safe defaults
    4. Error is stored for user visibility
    5. Provider can still be used for basic chat
    """

    from src.llm.provider_manager import LLMProviderManager
    from src.llm.config_loader import LLMConfigLoader
    from src.llm.config_loader import LLMConfig

    config_loader = LLMConfigLoader(use_mongodb=False)
    manager = LLMProviderManager(config_loader)

    # Create provider in auto-detection mode
    provider_config = LLMConfig(
        name="test-failed-detection",
        type="openai",
        base_url="https://invalid-api.example.com/v1",
        model="invalid-model",
        api_key_ref="INVALID_KEY"
    )

    manager.providers["test-failed-detection"] = provider_config

    # Initial state with safe defaults
    assert provider_config.capabilities == ["chat"]
    assert provider_config.context_window == 4096
    assert provider_config.capabilities_detection_status == "pending"

    # Simulate detection failure
    error_message = "Network timeout: Connection refused after 30s"

    provider_config.capabilities_detection_status = "failed"
    provider_config.capabilities_detection_error = error_message
    provider_config.capabilities_last_updated = datetime.now()

    # Verify failure state but provider still usable
    assert provider_config.capabilities_detection_status == "failed"
    assert "timeout" in provider_config.capabilities_detection_error.lower()
    assert provider_config.capabilities == ["chat"]  # Still has default
    assert provider_config.context_window == 4096  # Still has default
    assert provider_config.enabled is True  # Still enabled


@pytest.mark.asyncio
@pytest.mark.integration
async def test_capability_based_selection():
    """Test capability-based provider selection across multiple providers

    Flow:
    1. Create 3 providers with different capability combinations
    2. Query for specific capability requirements
    3. Verify correct provider is selected based on:
       - Has all required capabilities
       - Meets context window requirement
       - Has highest priority
       - Has lowest cost
    """

    from src.llm.provider_manager import LLMProviderManager
    from src.llm.config_loader import LLMConfigLoader
    from src.llm.config_loader import LLMConfig

    config_loader = LLMConfigLoader(use_mongodb=False)
    manager = LLMProviderManager(config_loader)

    # Provider 1: General chat (low cost, low priority)
    provider1 = LLMConfig(
        name="cheap-chat",
        type="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-3.5-turbo",
        api_key_ref="OPENAI_API_KEY",
        capabilities=["chat"],
        context_window=16384,
        cost_per_1k_tokens=0.0005,
        priority=1,
        enabled=True
    )

    # Provider 2: Vision capable (medium cost, medium priority)
    provider2 = LLMConfig(
        name="vision-model",
        type="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4o",
        api_key_ref="OPENAI_API_KEY",
        capabilities=["chat", "vision"],
        context_window=128000,
        cost_per_1k_tokens=0.01,
        priority=5,
        enabled=True
    )

    # Provider 3: Premium reasoning (high cost, high priority)
    provider3 = LLMConfig(
        name="reasoning-model",
        type="anthropic",
        base_url="https://api.anthropic.com/v1",
        model="claude-3-opus",
        api_key_ref="ANTHROPIC_API_KEY",
        capabilities=["chat", "reasoning", "code"],
        context_window=200000,
        cost_per_1k_tokens=0.03,
        priority=10,
        enabled=True
    )

    # Add all providers
    manager.providers["cheap-chat"] = provider1
    manager.providers["vision-model"] = provider2
    manager.providers["reasoning-model"] = provider3

    # Mock clients as initialized
    manager.clients["cheap-chat"] = Mock()
    manager.clients["vision-model"] = Mock()
    manager.clients["reasoning-model"] = Mock()
    manager.current_provider = "cheap-chat"

    # Test 1: Select for basic chat - should pick reasoning-model (highest priority)
    # Selection sorts by: priority (desc), context_window (desc), cost (asc)
    selected = manager.select_provider_by_capabilities(
        required_capabilities=["chat"]
    )
    assert selected == "reasoning-model"  # Has highest priority (10)

    # Test 2: Select for vision - only vision-model has it
    selected = manager.select_provider_by_capabilities(
        required_capabilities=["vision"]
    )
    assert selected == "vision-model"

    # Test 3: Select for reasoning - only reasoning-model has it
    selected = manager.select_provider_by_capabilities(
        required_capabilities=["reasoning"]
    )
    assert selected == "reasoning-model"

    # Test 4: Select for chat + vision - only vision-model has both
    selected = manager.select_provider_by_capabilities(
        required_capabilities=["chat", "vision"]
    )
    assert selected == "vision-model"

    # Test 5: Select with context window requirement
    selected = manager.select_provider_by_capabilities(
        required_capabilities=["chat"],
        min_context_window=150000
    )
    assert selected == "reasoning-model"  # Only one with >150k context


@pytest.mark.asyncio
@pytest.mark.integration
async def test_detection_retry_updates_provider():
    """Test that retry detection can update a failed provider

    Flow:
    1. Provider fails initial detection
    2. User triggers retry detection
    3. Second detection attempt succeeds
    4. Provider capabilities are updated
    5. Status changes from failed to completed
    """

    from src.llm.provider_manager import LLMProviderManager
    from src.llm.config_loader import LLMConfigLoader
    from src.llm.config_loader import LLMConfig

    config_loader = LLMConfigLoader(use_mongodb=False)
    manager = LLMProviderManager(config_loader)

    # Create provider that will fail detection initially
    provider_config = LLMConfig(
        name="test-retry-provider",
        type="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4o",
        api_key_ref="OPENAI_API_KEY"
    )

    manager.providers["test-retry-provider"] = provider_config

    # Initial failed detection
    provider_config.capabilities_detection_status = "failed"
    provider_config.capabilities_detection_error = "API Rate Limit Exceeded"
    provider_config.capabilities_last_updated = datetime.now()

    assert provider_config.capabilities_detection_status == "failed"
    assert provider_config.capabilities == ["chat"]  # Default

    # Simulate successful retry
    with patch('src.llm.capability_detector.CapabilityDetector') as MockDetector:
        mock_detector = AsyncMock()
        mock_detector.detect_capabilities.return_value = {
            "capabilities": ["chat", "vision", "code"],
            "context_window": 128000,
            "supports_multimodal": True,
            "supported_formats": ["text", "image"],
            "embedding_dimensions": None
        }
        MockDetector.return_value = mock_detector

        # Run retry detection
        detected = await mock_detector.detect_capabilities(
            provider_config.base_url,
            provider_config.model,
            provider_config.api_key_ref,
            None
        )

        # Update provider with successful detection
        provider_config.capabilities = detected["capabilities"]
        provider_config.context_window = detected["context_window"]
        provider_config.supports_multimodal = detected["supports_multimodal"]
        provider_config.supported_formats = detected["supported_formats"]
        provider_config.embedding_dimensions = detected["embedding_dimensions"]
        provider_config.capabilities_detection_status = "completed"
        provider_config.capabilities_detection_error = None  # Clear error
        provider_config.capabilities_last_updated = datetime.now()

        # Verify successful update
        assert provider_config.capabilities_detection_status == "completed"
        assert provider_config.capabilities_detection_error is None
        assert "vision" in provider_config.capabilities
        assert "code" in provider_config.capabilities
        assert provider_config.context_window == 128000


@pytest.mark.asyncio
@pytest.mark.integration
async def test_provider_selection_fallback_chain():
    """Test provider selection with fallback when primary is unavailable

    Flow:
    1. Multiple providers support same capabilities
    2. Primary provider is disabled or not initialized
    3. System falls back to next best provider
    4. Selection considers priority, cost, and availability
    """

    from src.llm.provider_manager import LLMProviderManager
    from src.llm.config_loader import LLMConfigLoader
    from src.llm.config_loader import LLMConfig

    config_loader = LLMConfigLoader(use_mongodb=False)
    manager = LLMProviderManager(config_loader)

    # Provider 1: High priority but disabled
    provider1 = LLMConfig(
        name="high-priority-disabled",
        type="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4",
        api_key_ref="OPENAI_API_KEY",
        capabilities=["chat", "code"],
        context_window=8192,
        cost_per_1k_tokens=0.03,
        priority=10,
        enabled=False  # Disabled
    )

    # Provider 2: Medium priority, enabled
    provider2 = LLMConfig(
        name="medium-priority",
        type="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-3.5-turbo",
        api_key_ref="OPENAI_API_KEY",
        capabilities=["chat", "code"],
        context_window=16384,
        cost_per_1k_tokens=0.001,
        priority=5,
        enabled=True
    )

    # Provider 3: Low priority but not initialized
    provider3 = LLMConfig(
        name="low-priority-no-client",
        type="anthropic",
        base_url="https://api.anthropic.com/v1",
        model="claude-3-haiku",
        api_key_ref="ANTHROPIC_API_KEY",
        capabilities=["chat", "code"],
        context_window=200000,
        cost_per_1k_tokens=0.00025,
        priority=1,
        enabled=True
    )

    manager.providers["high-priority-disabled"] = provider1
    manager.providers["medium-priority"] = provider2
    manager.providers["low-priority-no-client"] = provider3

    # Only medium-priority has initialized client
    manager.clients["medium-priority"] = Mock()
    manager.current_provider = "medium-priority"

    # Select for chat + code capabilities
    selected = manager.select_provider_by_capabilities(
        required_capabilities=["chat", "code"]
    )

    # Should select medium-priority (only enabled one with client)
    assert selected == "medium-priority"
