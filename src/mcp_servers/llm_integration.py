"""
Unified LLM Integration Module for MCP Servers

Provides consistent LLM client interface for both BPMN-MCP and FORM-MCP.
Supports multiple providers (DeepSeek, OpenAI) with automatic fallback.

Usage:
    from src.mcp_servers.llm_integration import get_llm_client, LLMClientFactory

    # Get appropriate client based on configuration
    client = LLMClientFactory.create(use_real_llm=True)
    response = await client.send_prompt(system_prompt, user_prompt)
"""

from typing import Dict, List, Optional, Any, Protocol
from abc import ABC, abstractmethod
import logging
import json
import re
from openai import AsyncOpenAI, RateLimitError, APIError, APIConnectionError, AuthenticationError

from src.core.config import settings

logger = logging.getLogger(__name__)


class LLMClientProtocol(Protocol):
    """Protocol defining the LLM client interface."""

    async def send_prompt(self, system_prompt: str, user_prompt: str) -> str:
        """Send prompt to LLM and return response."""
        ...


class BaseLLMClient(ABC):
    """Abstract base class for LLM clients."""

    def __init__(self):
        """Initialize base LLM client."""
        self._response_cache: Dict[str, str] = {}

    @abstractmethod
    async def send_prompt(self, system_prompt: str, user_prompt: str) -> str:
        """Send prompt to LLM and return response."""
        pass

    def _get_cache_key(self, system_prompt: str, user_prompt: str) -> str:
        """Generate cache key from prompts."""
        return f"{hash(system_prompt)}:::{hash(user_prompt)}"

    def _get_cached_response(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        """Get cached response if available."""
        cache_key = self._get_cache_key(system_prompt, user_prompt)
        return self._response_cache.get(cache_key)

    def _cache_response(self, system_prompt: str, user_prompt: str, response: str) -> None:
        """Cache response for future use."""
        cache_key = self._get_cache_key(system_prompt, user_prompt)
        self._response_cache[cache_key] = response


class MockLLMClient(BaseLLMClient):
    """
    Mock LLM client for testing without API calls.
    Returns deterministic responses based on input patterns.
    """

    def __init__(self):
        """Initialize Mock LLM client."""
        super().__init__()
        logger.info("MockLLMClient initialized")

    async def send_prompt(self, system_prompt: str, user_prompt: str) -> str:
        """
        Return mock response based on prompt content.

        Args:
            system_prompt: System context prompt
            user_prompt: User's request

        Returns:
            Mock response (BPMN XML or Form JSON based on context)
        """
        # Check cache first
        cached = self._get_cached_response(system_prompt, user_prompt)
        if cached:
            return cached

        # Detect response type from system prompt
        if "BPMN" in system_prompt or "bpmn" in system_prompt.lower():
            response = self._generate_mock_bpmn()
        elif "form" in system_prompt.lower():
            response = self._generate_mock_form()
        else:
            response = self._generate_mock_bpmn()  # Default to BPMN

        # Cache and return
        self._cache_response(system_prompt, user_prompt, response)
        return response

    def _generate_mock_bpmn(self) -> str:
        """Generate mock BPMN XML response."""
        return """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Definitions_Mock">
  <bpmn:process id="MockProcess" isExecutable="true">
    <bpmn:startEvent id="MockStart" name="Start"/>
    <bpmn:userTask id="MockTask" name="Task">
      <bpmn:incoming>MockFlow1</bpmn:incoming>
      <bpmn:outgoing>MockFlow2</bpmn:outgoing>
      <bpmn:documentation>{"executor_pattern": "static", "executor_config": {"type": "role", "value": "approver"}}</bpmn:documentation>
    </bpmn:userTask>
    <bpmn:endEvent id="MockEnd" name="End"/>
    <bpmn:sequenceFlow id="MockFlow1" sourceRef="MockStart" targetRef="MockTask"/>
    <bpmn:sequenceFlow id="MockFlow2" sourceRef="MockTask" targetRef="MockEnd"/>
  </bpmn:process>
</bpmn:definitions>"""

    def _generate_mock_form(self) -> str:
        """Generate mock Form JSON response."""
        import uuid
        mock_form = {
            "formId": f"form-{str(uuid.uuid4())[:8]}",
            "version": "1.0.0",
            "title": "Generated Form",
            "description": "Form generated from requirements",
            "controls": [
                {
                    "id": "field-001",
                    "type": "text",
                    "label": "Applicant Name",
                    "props": {"required": True, "maxLength": 100},
                    "width": "100%",
                    "permissions": {
                        "view": {"condition": "*", "applies_to": ["*"]},
                        "edit": {"condition": "*", "applies_to": ["*"]},
                        "required": {"condition": "True", "applies_to": ["*"]}
                    },
                    "data_binding": {
                        "bpmn_variable": "applicant_name",
                        "source_type": "user_input"
                    }
                }
            ],
            "validation": {
                "rules": {
                    "field-001": [
                        {"type": "required", "message": "Applicant name is required"}
                    ]
                }
            },
            "form_type": "standalone",
            "confidence_score": 0.85
        }
        return json.dumps(mock_form)


class RealLLMClient(BaseLLMClient):
    """
    Real LLM client using OpenAI-compatible API.
    Supports multiple providers with automatic fallback.

    Provider priority:
    1. DeepSeek (if configured)
    2. OpenAI (if configured)

    Fallback triggers:
    - Rate limit errors
    - Authentication errors
    - Connection errors
    - Recoverable API errors
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096
    ):
        """
        Initialize Real LLM client with multi-provider support.

        Args:
            base_url: Optional custom base URL (overrides settings)
            api_key: Optional API key (overrides settings)
            model: Optional model name (overrides settings)
            temperature: LLM temperature (default: 0.3 for consistency)
            max_tokens: Maximum tokens in response (default: 4096)
        """
        super().__init__()

        self.temperature = temperature
        self.max_tokens = max_tokens

        # Define provider list
        self.providers: List[Dict[str, Any]] = []

        # Add DeepSeek if configured
        deepseek_key = api_key or settings.deepseek_api_key
        if deepseek_key:
            self.providers.append({
                'name': 'deepseek',
                'base_url': base_url or settings.deepseek_base_url,
                'api_key': deepseek_key,
                'model': model or settings.deepseek_model_name
            })

        # Add OpenAI if configured (and not already using custom key)
        if not api_key and settings.openai_api_key:
            self.providers.append({
                'name': 'openai',
                'base_url': settings.openai_base_url,
                'api_key': settings.openai_api_key,
                'model': settings.openai_model_name
            })

        if not self.providers:
            raise ValueError(
                "No LLM provider configured. Set DEEPSEEK_API_KEY or OPENAI_API_KEY environment variable."
            )

        # Initialize clients
        self._clients: Dict[str, AsyncOpenAI] = {}
        for provider in self.providers:
            self._clients[provider['name']] = AsyncOpenAI(
                api_key=provider['api_key'],
                base_url=provider['base_url']
            )

        self.current_provider_index = 0

        logger.info(
            f"RealLLMClient initialized with {len(self.providers)} provider(s): "
            f"{', '.join(p['name'] for p in self.providers)}"
        )

    async def send_prompt(self, system_prompt: str, user_prompt: str) -> str:
        """
        Send prompt to LLM with automatic provider fallback.

        Args:
            system_prompt: System context prompt
            user_prompt: User's request

        Returns:
            LLM response string

        Raises:
            RuntimeError: If all providers fail
        """
        # Check cache first
        cached = self._get_cached_response(system_prompt, user_prompt)
        if cached:
            logger.debug("Returning cached LLM response")
            return cached

        last_error: Optional[Exception] = None

        # Try all providers with fallback
        for attempt in range(len(self.providers)):
            current_provider = self.providers[self.current_provider_index]
            client = self._clients[current_provider['name']]

            try:
                logger.info(
                    f"LLM call attempt {attempt + 1}/{len(self.providers)}: "
                    f"provider='{current_provider['name']}', model='{current_provider['model']}'"
                )

                response = await client.chat.completions.create(
                    model=current_provider['model'],
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=self.temperature,
                    max_tokens=self.max_tokens
                )

                text_response = response.choices[0].message.content
                logger.info(f"LLM call successful: provider='{current_provider['name']}'")

                # Cache and return
                self._cache_response(system_prompt, user_prompt, text_response)
                return text_response

            except RateLimitError as e:
                last_error = e
                logger.warning(f"Rate limit error with '{current_provider['name']}': {e}")
                self._switch_provider()

            except AuthenticationError as e:
                last_error = e
                logger.error(f"Authentication error with '{current_provider['name']}': {e}")
                self._switch_provider()

            except APIConnectionError as e:
                last_error = e
                logger.warning(f"Connection error with '{current_provider['name']}': {e}")
                self._switch_provider()

            except APIError as e:
                last_error = e
                logger.warning(f"API error with '{current_provider['name']}': {e}")
                if self._is_recoverable_error(e):
                    self._switch_provider()
                else:
                    raise RuntimeError(f"LLM API error: {e}") from e

            except Exception as e:
                last_error = e
                logger.error(f"Unexpected error with '{current_provider['name']}': {e}", exc_info=True)
                self._switch_provider()

        # All providers failed
        error_msg = f"All LLM providers failed. Last error: {last_error}"
        logger.error(error_msg)
        raise RuntimeError(error_msg) from last_error

    def _switch_provider(self) -> None:
        """Switch to next available provider."""
        self.current_provider_index = (self.current_provider_index + 1) % len(self.providers)
        next_provider = self.providers[self.current_provider_index]
        logger.info(f"Switched to provider: '{next_provider['name']}'")

    def _is_recoverable_error(self, error: APIError) -> bool:
        """Check if API error should trigger provider switch."""
        error_msg = str(error).lower()
        recoverable_keywords = [
            'rate limit', 'quota', 'throttled', 'exceeded',
            'internal server error', 'timeout', 'service unavailable'
        ]
        return any(kw in error_msg for kw in recoverable_keywords)


class LLMClientFactory:
    """
    Factory for creating LLM clients.

    Usage:
        client = LLMClientFactory.create(use_real_llm=True)
        response = await client.send_prompt(system, user)
    """

    @staticmethod
    def create(
        use_real_llm: bool = False,
        **kwargs
    ) -> BaseLLMClient:
        """
        Create appropriate LLM client.

        Args:
            use_real_llm: If True, create RealLLMClient; else MockLLMClient
            **kwargs: Additional arguments passed to RealLLMClient

        Returns:
            LLM client instance
        """
        if use_real_llm:
            return RealLLMClient(**kwargs)
        else:
            return MockLLMClient()


# Convenience function
def get_llm_client(use_real_llm: bool = False, **kwargs) -> BaseLLMClient:
    """
    Get LLM client instance.

    Args:
        use_real_llm: Whether to use real LLM API
        **kwargs: Additional arguments for RealLLMClient

    Returns:
        LLM client instance
    """
    return LLMClientFactory.create(use_real_llm=use_real_llm, **kwargs)


# JSON extraction utilities
def extract_json_from_response(response: str) -> Optional[Dict[str, Any]]:
    """
    Extract JSON from LLM response that may contain markdown or extra text.

    Args:
        response: Raw LLM response string

    Returns:
        Parsed JSON dict, or None if extraction fails
    """
    # Try direct parse first
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        pass

    # Try to extract JSON from markdown code block
    patterns = [
        r'```json\s*([\s\S]*?)\s*```',  # ```json ... ```
        r'```\s*([\s\S]*?)\s*```',       # ``` ... ```
        r'\{[\s\S]*\}',                   # Raw JSON object
    ]

    for pattern in patterns:
        match = re.search(pattern, response)
        if match:
            try:
                json_str = match.group(1) if '```' in pattern else match.group(0)
                return json.loads(json_str)
            except (json.JSONDecodeError, IndexError):
                continue

    return None


def extract_xml_from_response(response: str) -> Optional[str]:
    """
    Extract XML from LLM response that may contain markdown or extra text.

    Args:
        response: Raw LLM response string

    Returns:
        XML string, or None if extraction fails
    """
    # Try to find XML declaration or root element
    patterns = [
        r'(<\?xml[\s\S]*</[^>]+>)',      # Full XML with declaration
        r'(<bpmn:definitions[\s\S]*</bpmn:definitions>)',  # BPMN definitions
        r'```xml\s*([\s\S]*?)\s*```',    # ```xml ... ```
        r'(<[^>]+>[\s\S]*</[^>]+>)',     # Any XML-like content
    ]

    for pattern in patterns:
        match = re.search(pattern, response)
        if match:
            xml_str = match.group(1) if match.lastindex else match.group(0)
            # Basic validation
            if xml_str.strip().startswith('<') and xml_str.strip().endswith('>'):
                return xml_str.strip()

    # If response looks like XML already, return it
    stripped = response.strip()
    if stripped.startswith('<') and stripped.endswith('>'):
        return stripped

    return None
