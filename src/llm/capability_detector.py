"""
Auto-detect LLM model capabilities through multi-tier strategy:
1. Predefined registry (high confidence)
2. Name-based inference (medium confidence)
3. LLM self-description query (high confidence)
"""

import logging
from typing import Optional, Dict, Any
from .model_capabilities import get_predefined_capabilities

logger = logging.getLogger(__name__)


class CapabilityDetector:
    """Auto-detect LLM model capabilities"""

    def __init__(self, provider_manager):
        self.provider_manager = provider_manager

    async def detect_capabilities(
        self,
        base_url: str,
        model: str,
        api_key_ref: str,
        auth_token: str
    ) -> Dict[str, Any]:
        """
        Detect model capabilities through multi-tier strategy:
        1. Predefined registry (high confidence)
        2. Name-based inference (medium confidence)
        3. LLM self-description query (high confidence)
        """
        logger.info(f"Detecting capabilities for model: {model}")

        # Tier 1: Predefined
        predefined = get_predefined_capabilities(model)
        if predefined:
            predefined["detection_method"] = "predefined"
            predefined["confidence"] = "high"
            logger.info(f"Found predefined config for {model}")
            return predefined

        # Tier 2: Name inference
        inferred = self._infer_from_name(model)
        if inferred:
            inferred["detection_method"] = "name_inference"
            inferred["confidence"] = "medium"
            logger.info(f"Inferred capabilities for {model}")
            return inferred

        # Tier 3: Ask LLM
        discovered = await self._ask_llm_self_description(
            base_url, model, auth_token
        )
        if discovered:
            discovered["detection_method"] = "llm_query"
            discovered["confidence"] = "high"
            return discovered

        # Fallback: Default
        return self._get_default_capabilities()

    def _infer_from_name(self, model: str) -> Optional[Dict[str, Any]]:
        """Infer capabilities from model name"""
        name_lower = model.lower()
        capabilities = []

        if "embedding" in name_lower:
            return {
                "capabilities": ["embedding"],
                "embedding_dimensions": 1536,
                "confidence": "high"
            }

        if any(x in name_lower for x in ["vision", "vl-", "multimodal", "4o"]):
            capabilities.extend(["vision", "ocr"])

        if "coder" in name_lower:
            capabilities.append("code")

        if "o1" in name_lower or "reasoning" in name_lower:
            capabilities.append("reasoning")

        capabilities.append("chat")  # Almost all models can chat

        return {
            "capabilities": list(set(capabilities)),
            "context_window": 4096,
            "max_tokens": 2048
        } if capabilities else None

    async def _ask_llm_self_description(
        self,
        base_url: str,
        model: str,
        auth_token: str
    ) -> Optional[Dict[str, Any]]:
        """Query LLM to describe its own capabilities"""
        # Will be implemented in Task 4
        pass

    def _get_default_capabilities(self) -> Dict[str, Any]:
        """Safe default capabilities"""
        return {
            "capabilities": ["chat"],
            "context_window": 4096,
            "max_tokens": 2048,
            "detection_method": "default",
            "confidence": "low",
            "warning": "Could not auto-detect. Using safe defaults."
        }
