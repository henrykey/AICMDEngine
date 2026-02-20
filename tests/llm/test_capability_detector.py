"""Tests for capability detector"""

import pytest
from src.llm.capability_detector import CapabilityDetector


# Mock provider manager
class MockProviderManager:
    pass


@pytest.mark.asyncio
async def test_detect_predefined_model():
    """Test detection of predefined model"""
    detector = CapabilityDetector(MockProviderManager())
    result = await detector.detect_capabilities(
        "https://api.openai.com/v1",
        "gpt-4o",
        "OPENAI_API_KEY",
        "sk-test"
    )
    assert result["detection_method"] == "predefined"
    assert "chat" in result["capabilities"]
    assert "vision" in result["capabilities"]


def test_infer_from_name():
    """Test name-based inference"""
    detector = CapabilityDetector(None)
    result = detector._infer_from_name("text-embedding-3-small")
    assert result["capabilities"] == ["embedding"]
    assert result["embedding_dimensions"] == 1536


def test_infer_vision_from_name():
    """Test inferring vision capabilities from name"""
    detector = CapabilityDetector(None)
    result = detector._infer_from_name("gpt-4o-vision")
    assert "vision" in result["capabilities"]
    assert "ocr" in result["capabilities"]


def test_infer_coder_from_name():
    """Test inferring code capabilities from name"""
    detector = CapabilityDetector(None)
    result = detector._infer_from_name("deepseek-coder")
    assert "code" in result["capabilities"]
    assert "chat" in result["capabilities"]


def test_get_default_capabilities():
    """Test default capabilities fallback"""
    detector = CapabilityDetector(None)
    result = detector._get_default_capabilities()
    assert result["capabilities"] == ["chat"]
    assert result["context_window"] == 4096
    assert result["detection_method"] == "default"
    assert result["confidence"] == "low"
