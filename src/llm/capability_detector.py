"""
Auto-detect LLM model capabilities through multi-tier strategy:
1. Predefined registry (high confidence)
2. Name-based inference (medium confidence)
3. LLM self-description query (high confidence)
"""

import logging
import httpx
import json
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
        """Query LLM to describe its capabilities"""
        prompt = '''Please describe your capabilities in JSON format:
{
  "model_name": "your exact model name",
  "capabilities": ["chat", "embedding", "vision", "ocr", "code", "reasoning", "multimodal", "function_calling"],
  "context_window": max tokens (integer),
  "max_tokens": max output tokens (integer),
  "supports_multimodal": true/false,
  "supported_formats": ["png", "jpg", "webp"] (if applicable),
  "embedding_dimensions": integer (if embedding model)
}

Only include capabilities you ACTUALLY have. Return valid JSON only.'''

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {auth_token}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": model,
                        "messages": [
                            {
                                "role": "system",
                                "content": "You are a helpful AI assistant. Answer with JSON only."
                            },
                            {
                                "role": "user",
                                "content": prompt
                            }
                        ],
                        "temperature": 0,
                        "max_tokens": 500
                    }
                )

                if response.status_code != 200:
                    logger.error(f"LLM query failed: {response.status_code}")
                    return None

                data = response.json()
                content = data["choices"][0]["message"]["content"]

                # Parse JSON response
                parsed = json.loads(content)

                # Validate and return
                return {
                    "capabilities": parsed.get("capabilities", ["chat"]),
                    "context_window": parsed.get("context_window", 4096),
                    "max_tokens": parsed.get("max_tokens", 2048),
                    "supports_multimodal": parsed.get("supports_multimodal", False),
                    "supported_formats": parsed.get("supported_formats", []),
                    "embedding_dimensions": parsed.get("embedding_dimensions")
                }

        except Exception as e:
            logger.error(f"Error querying LLM: {e}")
            return None

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
