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
        1. Predefined registry (high confidence) - use if available
        2. LLM self-description query (high confidence) - default for unknown models
        3. Name-based inference (low confidence) - fallback if query fails
        4. Default capabilities (safe defaults) - last resort
        """
        logger.info(f"Detecting capabilities for model: {model}")

        # Tier 1: Predefined (highest confidence)
        predefined = get_predefined_capabilities(model)
        if predefined:
            predefined["detection_method"] = "predefined"
            predefined["confidence"] = "high"
            logger.info(f"Found predefined config for {model}")
            return predefined

        # Tier 2: Ask LLM directly (primary method for unknown models)
        logger.info(f"No predefined config for {model}, querying model...")
        discovered = await self._ask_llm_self_description(
            base_url, model, auth_token
        )
        if discovered:
            discovered["detection_method"] = "llm_query"
            discovered["confidence"] = "high"
            logger.info(f"Successfully queried {model} for capabilities")
            return discovered

        # Tier 3: Name inference (fallback if query fails)
        logger.info(f"LLM query failed for {model}, using name inference as fallback")
        inferred = self._infer_from_name(model)
        if inferred:
            inferred["detection_method"] = "name_inference"
            inferred["confidence"] = "low"
            inferred["warning"] = "Could not query model, used name inference (may be inaccurate)"
            logger.info(f"Inferred capabilities from name for {model}")
            return inferred

        # Tier 4: Default capabilities (last resort)
        logger.warning(f"All detection methods failed for {model}, using defaults")
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
        prompt = f'''You are configured as model "{model}". Please describe YOUR capabilities (not other models) in JSON format:
{{
  "model_name": "{model}",
  "capabilities": ["chat", "embedding", "vision", "ocr", "code", "reasoning", "multimodal", "function_calling"],
  "context_window": max tokens (integer),
  "max_tokens": max output tokens (integer),
  "supports_multimodal": true/false,
  "supported_formats": ["png", "jpg", "webp"] (if applicable),
  "embedding_dimensions": integer (if embedding model)
}}

Only include capabilities you ACTUALLY have as model "{model}". Return valid JSON only.'''

        try:
            # Use longer timeout for local models (up to 2 minutes)
            timeout = httpx.Timeout(120.0, connect=10.0)

            request_payload = {
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

            logger.info(f"[{model}] Sending capability detection request to {base_url}")
            logger.debug(f"[{model}] Request payload: {request_payload}")

            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {auth_token}",
                        "Content-Type": "application/json"
                    },
                    json=request_payload
                )

                logger.info(f"[{model}] Response status: {response.status_code}")

                if response.status_code != 200:
                    logger.error(f"[{model}] LLM query failed: {response.status_code} - {response.text}")
                    return None

                data = response.json()
                content = data["choices"][0]["message"]["content"].strip()

                logger.info(f"[{model}] Raw response: {content[:200]}...")  # Log first 200 chars

                # Clean markdown code blocks if present
                if content.startswith("```"):
                    # Remove ```json or ``` at start
                    lines = content.split("\n")
                    if lines[0].startswith("```"):
                        lines = lines[1:]  # Remove first line
                    # Remove ``` at end
                    if lines and lines[-1].startswith("```"):
                        lines = lines[:-1]  # Remove last line
                    content = "\n".join(lines).strip()
                    logger.debug(f"[{model}] Cleaned response: {content[:200]}...")

                # Parse JSON response
                parsed = json.loads(content)
                logger.info(f"[{model}] Parsed capabilities: {parsed.get('capabilities', [])}")

                # Validate and return
                result = {
                    "capabilities": parsed.get("capabilities", ["chat"]),
                    "context_window": parsed.get("context_window", 4096),
                    "max_tokens": parsed.get("max_tokens", 2048),
                    "supports_multimodal": parsed.get("supports_multimodal", False),
                    "supported_formats": parsed.get("supported_formats", []),
                    "embedding_dimensions": parsed.get("embedding_dimensions")
                }
                logger.info(f"[{model}] Final detection result: {result}")
                return result

        except json.JSONDecodeError as e:
            logger.error(f"[{model}] JSON parse error: {e}")
            logger.error(f"[{model}] Response content was: {content if 'content' in locals() else 'N/A'}")
            return None
        except Exception as e:
            logger.error(f"[{model}] Error querying LLM: {e}", exc_info=True)
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
