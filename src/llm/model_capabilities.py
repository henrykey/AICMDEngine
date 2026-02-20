"""Predefined capabilities for known LLM models"""

from typing import Optional, Dict, Any

PREDEFINED_MODEL_CAPABILITIES = {
    # OpenAI
    "gpt-4o": {
        "capabilities": ["chat", "vision", "ocr", "code", "reasoning", "function_calling"],
        "context_window": 128000,
        "max_tokens": 4096,
        "supports_multimodal": True
    },
    "gpt-4o-mini": {
        "capabilities": ["chat", "vision", "code", "function_calling"],
        "context_window": 128000,
        "max_tokens": 16384,
        "supports_multimodal": True
    },
    "text-embedding-3-small": {
        "capabilities": ["embedding"],
        "embedding_dimensions": 1536
    },
    "text-embedding-3-large": {
        "capabilities": ["embedding"],
        "embedding_dimensions": 3072
    },
    "o1-preview": {
        "capabilities": ["chat", "reasoning", "code"],
        "context_window": 128000,
        "reasoning_model": True
    },
    "o1-mini": {
        "capabilities": ["chat", "reasoning", "code"],
        "context_window": 128000,
        "reasoning_model": True
    },

    # Anthropic
    "claude-3-5-sonnet-20241022": {
        "capabilities": ["chat", "vision", "code", "reasoning", "function_calling"],
        "context_window": 200000,
        "max_tokens": 8192
    },
    "claude-3-5-haiku-20241022": {
        "capabilities": ["chat", "vision", "code"],
        "context_window": 200000,
        "max_tokens": 8192
    },

    # DeepSeek
    "deepseek-chat": {
        "capabilities": ["chat", "code", "reasoning"],
        "context_window": 64000,
        "max_tokens": 4096
    },
    "deepseek-coder": {
        "capabilities": ["chat", "code"],
        "context_window": 64000,
        "max_tokens": 4096
    },

    # Qwen
    "qwen-vl-max": {
        "capabilities": ["chat", "vision", "ocr"],
        "context_window": 32000,
        "max_tokens": 8192
    },
}


def get_predefined_capabilities(model_name: str) -> Optional[Dict[str, Any]]:
    """
    Get predefined capabilities for a model.

    Args:
        model_name: Exact model name to look up

    Returns:
        Dictionary of capabilities if found, None otherwise
    """
    if model_name in PREDEFINED_MODEL_CAPABILITIES:
        return PREDEFINED_MODEL_CAPABILITIES[model_name].copy()

    # Try fuzzy match for versioned models
    base_name = model_name.split("-")[0]
    for key, caps in PREDEFINED_MODEL_CAPABILITIES.items():
        if key.startswith(base_name):
            result = caps.copy()
            result["_matched_pattern"] = key
            return result

    return None
