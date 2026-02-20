"""Tests for model capabilities registry"""

import pytest
from src.llm.model_capabilities import get_predefined_capabilities


def test_get_predefined_capabilities_exact_match():
    """Test exact match for known model"""
    caps = get_predefined_capabilities("gpt-4o")
    assert caps is not None
    assert "chat" in caps["capabilities"]
    assert "vision" in caps["capabilities"]
    assert caps["context_window"] == 128000
    assert caps["supports_multimodal"] is True


def test_get_predefined_capabilities_fuzzy_match():
    """Test fuzzy match for versioned models"""
    caps = get_predefined_capabilities("gpt-4o-20240808")
    assert caps is not None
    assert "_matched_pattern" in caps
    assert "chat" in caps["capabilities"]


def test_get_predefined_capabilities_not_found():
    """Test unknown model returns None"""
    caps = get_predefined_capabilities("unknown-model-xyz")
    assert caps is None


def test_embedding_model_capabilities():
    """Test embedding model has dimensions"""
    caps = get_predefined_capabilities("text-embedding-3-small")
    assert caps is not None
    assert caps["capabilities"] == ["embedding"]
    assert caps["embedding_dimensions"] == 1536


def test_reasoning_model_capabilities():
    """Test reasoning model has flag"""
    caps = get_predefined_capabilities("o1-preview")
    assert caps is not None
    assert "reasoning" in caps["capabilities"]
    assert caps.get("reasoning_model") is True
