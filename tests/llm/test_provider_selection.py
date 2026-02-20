"""Tests for capability-based provider selection"""

import pytest
from src.llm.provider_manager import LLMProviderManager
from src.llm.config_loader import LLMConfig, LLMConfigLoader


class MockConfigLoader(LLMConfigLoader):
    """Mock config loader for testing"""
    def __init__(self, providers):
        self.providers = providers
        self.use_mongodb = False

    def get_api_key(self, key_ref: str) -> str:
        """Return mock API key"""
        return "mock_api_key_" + key_ref

    def load_from_yaml(self) -> dict:
        """Return mock providers"""
        return self.providers

    def get_enabled_providers(self, providers: dict) -> list:
        """Return all providers as enabled"""
        return list(providers.values())


@pytest.fixture
def provider_manager():
    """Create provider manager with test providers"""
    providers = {
        "gpt-4o": LLMConfig(
            name="gpt-4o",
            base_url="https://api.openai.com/v1",
            model="gpt-4o",
            api_key_ref="OPENAI_KEY",
            type="openai",
            enabled=True,
            priority=10,
            capabilities=["chat", "vision"],
            context_window=128000,
            max_tokens=4096,
            cost_per_1k_tokens=0.005,
            embedding_dimensions=None,
        ),
        "claude-3-opus": LLMConfig(
            name="claude-3-opus",
            base_url="https://api.anthropic.com/v1",
            model="claude-3-opus-20240229",
            api_key_ref="ANTHROPIC_KEY",
            type="anthropic",
            enabled=True,
            priority=8,
            capabilities=["chat", "vision"],
            context_window=200000,
            max_tokens=4096,
            cost_per_1k_tokens=0.015,
            embedding_dimensions=None,
        ),
        "text-embedding-3-small": LLMConfig(
            name="text-embedding-3-small",
            base_url="https://api.openai.com/v1",
            model="text-embedding-3-small",
            api_key_ref="OPENAI_KEY",
            type="openai",
            enabled=True,
            priority=5,
            capabilities=["embedding"],
            context_window=8191,
            max_tokens=8191,
            cost_per_1k_tokens=0.00002,
            embedding_dimensions=1536,
        ),
        "text-embedding-3-large": LLMConfig(
            name="text-embedding-3-large",
            base_url="https://api.openai.com/v1",
            model="text-embedding-3-large",
            api_key_ref="OPENAI_KEY",
            type="openai",
            enabled=True,
            priority=5,
            capabilities=["embedding"],
            context_window=8191,
            max_tokens=8191,
            cost_per_1k_tokens=0.00013,
            embedding_dimensions=3072,
        ),
    }

    loader = MockConfigLoader(providers)
    manager = LLMProviderManager(loader)
    manager.providers = providers

    # Mock clients as initialized
    for name in providers:
        manager.clients[name] = True  # Mock client

    return manager


def test_select_by_single_capability(provider_manager):
    """Test selecting provider with single capability requirement"""
    selected = provider_manager.select_provider_by_capabilities(["chat"])

    # Should select gpt-4o (higher priority than claude)
    assert selected == "gpt-4o"


def test_select_by_multiple_capabilities(provider_manager):
    """Test selecting provider with multiple capability requirements"""
    selected = provider_manager.select_provider_by_capabilities(["chat", "vision"])

    # Should select gpt-4o (higher priority than claude)
    assert selected == "gpt-4o"


def test_select_by_embedding_dimensions(provider_manager):
    """Test selecting embedding provider by dimensions"""
    # Select 1536-dimension embedding
    selected = provider_manager.select_provider_by_capabilities(
        ["embedding"],
        embedding_dimensions=1536
    )
    assert selected == "text-embedding-3-small"

    # Select 3072-dimension embedding
    selected = provider_manager.select_provider_by_capabilities(
        ["embedding"],
        embedding_dimensions=3072
    )
    assert selected == "text-embedding-3-large"


def test_select_by_min_context_window(provider_manager):
    """Test selecting provider by minimum context window"""
    # Require large context window (>150k)
    selected = provider_manager.select_provider_by_capabilities(
        ["chat", "vision"],
        min_context_window=150000
    )

    # Should select claude-3-opus (200k context window)
    assert selected == "claude-3-opus"


def test_no_matching_provider(provider_manager):
    """Test when no provider matches requirements"""
    # Request capability that doesn't exist
    selected = provider_manager.select_provider_by_capabilities(["code_execution"])

    assert selected is None


def test_wrong_embedding_dimensions(provider_manager):
    """Test requesting non-existent embedding dimensions"""
    selected = provider_manager.select_provider_by_capabilities(
        ["embedding"],
        embedding_dimensions=9999
    )

    assert selected is None


def test_context_window_too_small(provider_manager):
    """Test when required context window exceeds all providers"""
    selected = provider_manager.select_provider_by_capabilities(
        ["chat"],
        min_context_window=1000000  # 1M tokens - none support this
    )

    assert selected is None


def test_priority_sorting(provider_manager):
    """Test that priority is correctly used in sorting"""
    # Both gpt-4o and claude-3-opus have chat + vision
    # gpt-4o should be selected due to higher priority (10 vs 8)
    selected = provider_manager.select_provider_by_capabilities(["chat", "vision"])

    assert selected == "gpt-4o"


def test_cost_sorting_after_priority(provider_manager):
    """Test that cost is used as secondary sort criterion"""
    # Create a scenario where two providers have same priority but different costs
    provider_manager.providers["low-cost-chat"] = LLMConfig(
        name="low-cost-chat",
        base_url="https://api.cheap.com/v1",
        model="cheap-model",
        api_key_ref="CHEAP_KEY",
        type="openai",
        enabled=True,
        priority=10,  # Same as gpt-4o
        capabilities=["chat"],
        context_window=128000,
        max_tokens=4096,
        cost_per_1k_tokens=0.001,  # Cheaper than gpt-4o
        embedding_dimensions=None,
    )
    provider_manager.clients["low-cost-chat"] = True

    # Should select low-cost-chat due to lower cost (same priority)
    selected = provider_manager.select_provider_by_capabilities(["chat"])
    assert selected == "low-cost-chat"


def test_uninitialized_provider_not_selected(provider_manager):
    """Test that uninitialized providers are not selected"""
    # Remove client for gpt-4o
    del provider_manager.clients["gpt-4o"]

    # Should select claude-3-opus instead (gpt-4o not initialized)
    selected = provider_manager.select_provider_by_capabilities(["chat", "vision"])
    assert selected == "claude-3-opus"
