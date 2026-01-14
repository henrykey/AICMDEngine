"""
Tests for Unified LLM Integration Module

Tests cover:
- MockLLMClient functionality
- RealLLMClient initialization and fallback
- LLMClientFactory
- JSON/XML extraction utilities
- Error handling and provider switching
"""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch

from src.mcp_servers.llm_integration import (
    MockLLMClient,
    RealLLMClient,
    LLMClientFactory,
    get_llm_client,
    extract_json_from_response,
    extract_xml_from_response,
    BaseLLMClient
)


class TestMockLLMClient:
    """Tests for MockLLMClient."""

    @pytest.mark.asyncio
    async def test_mock_client_returns_bpmn_for_bpmn_prompt(self):
        """MockLLMClient returns BPMN XML for BPMN-related prompts."""
        client = MockLLMClient()
        response = await client.send_prompt(
            system_prompt="You are a BPMN expert",
            user_prompt="Generate a simple approval process"
        )

        assert "<?xml" in response
        assert "bpmn:definitions" in response
        assert "bpmn:process" in response
        assert "bpmn:startEvent" in response
        assert "bpmn:endEvent" in response

    @pytest.mark.asyncio
    async def test_mock_client_returns_json_for_form_prompt(self):
        """MockLLMClient returns JSON for form-related prompts."""
        client = MockLLMClient()
        response = await client.send_prompt(
            system_prompt="You are a form generation expert",
            user_prompt="Generate a simple form"
        )

        # Should be valid JSON
        form_def = json.loads(response)
        assert "formId" in form_def
        assert "controls" in form_def

    @pytest.mark.asyncio
    async def test_mock_client_caches_responses(self):
        """MockLLMClient caches responses for identical prompts."""
        client = MockLLMClient()

        response1 = await client.send_prompt("system", "user")
        response2 = await client.send_prompt("system", "user")

        assert response1 == response2

    @pytest.mark.asyncio
    async def test_mock_client_different_prompts_same_response_type(self):
        """MockLLMClient returns consistent type for same category prompts."""
        client = MockLLMClient()

        response1 = await client.send_prompt("BPMN expert", "Process 1")
        response2 = await client.send_prompt("BPMN expert", "Process 2")

        # Both should be XML
        assert "<?xml" in response1
        assert "<?xml" in response2


class TestRealLLMClientInitialization:
    """Tests for RealLLMClient initialization."""

    def test_raises_error_without_api_key(self):
        """RealLLMClient raises error when no API key configured."""
        with patch('src.mcp_servers.llm_integration.settings') as mock_settings:
            mock_settings.deepseek_api_key = ""
            mock_settings.openai_api_key = ""

            with pytest.raises(ValueError, match="No LLM provider configured"):
                RealLLMClient()

    def test_initializes_with_deepseek_key(self):
        """RealLLMClient initializes with DeepSeek API key."""
        with patch('src.mcp_servers.llm_integration.settings') as mock_settings:
            mock_settings.deepseek_api_key = "test-key"
            mock_settings.deepseek_base_url = "https://api.deepseek.com/v1"
            mock_settings.deepseek_model_name = "deepseek-chat"
            mock_settings.openai_api_key = ""

            client = RealLLMClient()
            assert len(client.providers) == 1
            assert client.providers[0]['name'] == 'deepseek'

    def test_initializes_with_both_providers(self):
        """RealLLMClient initializes with both providers when configured."""
        with patch('src.mcp_servers.llm_integration.settings') as mock_settings:
            mock_settings.deepseek_api_key = "deepseek-key"
            mock_settings.deepseek_base_url = "https://api.deepseek.com/v1"
            mock_settings.deepseek_model_name = "deepseek-chat"
            mock_settings.openai_api_key = "openai-key"
            mock_settings.openai_base_url = "https://api.openai.com/v1"
            mock_settings.openai_model_name = "gpt-4"

            client = RealLLMClient()
            assert len(client.providers) == 2
            provider_names = [p['name'] for p in client.providers]
            assert 'deepseek' in provider_names
            assert 'openai' in provider_names

    def test_custom_api_key_overrides_settings(self):
        """Custom API key parameter overrides settings."""
        with patch('src.mcp_servers.llm_integration.settings') as mock_settings:
            mock_settings.deepseek_api_key = ""
            mock_settings.deepseek_base_url = "https://api.deepseek.com/v1"
            mock_settings.deepseek_model_name = "deepseek-chat"
            mock_settings.openai_api_key = ""

            client = RealLLMClient(api_key="custom-key")
            assert len(client.providers) == 1
            assert client.providers[0]['api_key'] == "custom-key"


class TestLLMClientFactory:
    """Tests for LLMClientFactory."""

    def test_creates_mock_client_by_default(self):
        """Factory creates MockLLMClient when use_real_llm is False."""
        client = LLMClientFactory.create(use_real_llm=False)
        assert isinstance(client, MockLLMClient)

    def test_creates_real_client_when_requested(self):
        """Factory creates RealLLMClient when use_real_llm is True."""
        with patch('src.mcp_servers.llm_integration.settings') as mock_settings:
            mock_settings.deepseek_api_key = "test-key"
            mock_settings.deepseek_base_url = "https://api.deepseek.com/v1"
            mock_settings.deepseek_model_name = "deepseek-chat"
            mock_settings.openai_api_key = ""

            client = LLMClientFactory.create(use_real_llm=True)
            assert isinstance(client, RealLLMClient)

    def test_get_llm_client_convenience_function(self):
        """get_llm_client returns appropriate client."""
        client = get_llm_client(use_real_llm=False)
        assert isinstance(client, MockLLMClient)


class TestJSONExtraction:
    """Tests for extract_json_from_response."""

    def test_extracts_raw_json(self):
        """Extracts JSON from raw JSON string."""
        response = '{"key": "value", "number": 42}'
        result = extract_json_from_response(response)

        assert result is not None
        assert result["key"] == "value"
        assert result["number"] == 42

    def test_extracts_json_from_markdown_block(self):
        """Extracts JSON from markdown code block."""
        response = '''Here is the form:
```json
{"formId": "test-123", "controls": []}
```
That's the form definition.'''

        result = extract_json_from_response(response)

        assert result is not None
        assert result["formId"] == "test-123"
        assert result["controls"] == []

    def test_extracts_json_from_plain_code_block(self):
        """Extracts JSON from plain code block."""
        response = '''
```
{"formId": "test-456"}
```
'''
        result = extract_json_from_response(response)

        assert result is not None
        assert result["formId"] == "test-456"

    def test_extracts_embedded_json_object(self):
        """Extracts JSON object embedded in text."""
        response = 'The result is: {"success": true, "data": {"id": 1}} and that is all.'
        result = extract_json_from_response(response)

        assert result is not None
        assert result["success"] is True

    def test_returns_none_for_invalid_json(self):
        """Returns None when no valid JSON found."""
        response = "This is just plain text without any JSON"
        result = extract_json_from_response(response)

        assert result is None

    def test_handles_complex_nested_json(self):
        """Handles complex nested JSON structures."""
        response = '''```json
{
  "formId": "form-001",
  "controls": [
    {"id": "f1", "type": "text", "label": "Name"},
    {"id": "f2", "type": "number", "label": "Age"}
  ],
  "validation": {
    "rules": {"f1": [{"type": "required"}]}
  }
}
```'''
        result = extract_json_from_response(response)

        assert result is not None
        assert len(result["controls"]) == 2
        assert result["validation"]["rules"]["f1"][0]["type"] == "required"


class TestXMLExtraction:
    """Tests for extract_xml_from_response."""

    def test_extracts_raw_xml(self):
        """Extracts XML from raw XML string."""
        response = '''<?xml version="1.0"?>
<root><child>value</child></root>'''

        result = extract_xml_from_response(response)

        assert result is not None
        assert "<?xml" in result
        assert "<root>" in result

    def test_extracts_bpmn_definitions(self):
        """Extracts BPMN definitions from response."""
        response = '''Here is the process:
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
  <bpmn:process id="test"/>
</bpmn:definitions>
That's the BPMN.'''

        result = extract_xml_from_response(response)

        assert result is not None
        assert "bpmn:definitions" in result
        assert "bpmn:process" in result

    def test_extracts_xml_from_markdown_block(self):
        """Extracts XML from markdown code block."""
        response = '''```xml
<root><element attr="value"/></root>
```'''

        result = extract_xml_from_response(response)

        assert result is not None
        assert "<root>" in result

    def test_returns_none_for_non_xml(self):
        """Returns None when no XML found."""
        response = "This is just plain text"
        result = extract_xml_from_response(response)

        assert result is None


class TestRealLLMClientProviderFallback:
    """Tests for RealLLMClient provider fallback mechanism."""

    @pytest.mark.asyncio
    async def test_switches_provider_on_rate_limit(self):
        """Client switches provider on rate limit error."""
        with patch('src.mcp_servers.llm_integration.settings') as mock_settings:
            mock_settings.deepseek_api_key = "key1"
            mock_settings.deepseek_base_url = "https://api.deepseek.com/v1"
            mock_settings.deepseek_model_name = "deepseek-chat"
            mock_settings.openai_api_key = "key2"
            mock_settings.openai_base_url = "https://api.openai.com/v1"
            mock_settings.openai_model_name = "gpt-4"

            client = RealLLMClient()
            initial_index = client.current_provider_index

            # Simulate provider switch
            client._switch_provider()

            assert client.current_provider_index != initial_index

    def test_is_recoverable_error_rate_limit(self):
        """Rate limit errors are recoverable."""
        with patch('src.mcp_servers.llm_integration.settings') as mock_settings:
            mock_settings.deepseek_api_key = "key"
            mock_settings.deepseek_base_url = "https://api.deepseek.com/v1"
            mock_settings.deepseek_model_name = "deepseek-chat"
            mock_settings.openai_api_key = ""

            client = RealLLMClient()

            mock_error = MagicMock()
            mock_error.__str__ = MagicMock(return_value="Rate limit exceeded")

            assert client._is_recoverable_error(mock_error) is True

    def test_is_recoverable_error_timeout(self):
        """Timeout errors are recoverable."""
        with patch('src.mcp_servers.llm_integration.settings') as mock_settings:
            mock_settings.deepseek_api_key = "key"
            mock_settings.deepseek_base_url = "https://api.deepseek.com/v1"
            mock_settings.deepseek_model_name = "deepseek-chat"
            mock_settings.openai_api_key = ""

            client = RealLLMClient()

            mock_error = MagicMock()
            mock_error.__str__ = MagicMock(return_value="Request timeout")

            assert client._is_recoverable_error(mock_error) is True

    def test_non_recoverable_error(self):
        """Non-recoverable errors are identified."""
        with patch('src.mcp_servers.llm_integration.settings') as mock_settings:
            mock_settings.deepseek_api_key = "key"
            mock_settings.deepseek_base_url = "https://api.deepseek.com/v1"
            mock_settings.deepseek_model_name = "deepseek-chat"
            mock_settings.openai_api_key = ""

            client = RealLLMClient()

            mock_error = MagicMock()
            mock_error.__str__ = MagicMock(return_value="Invalid request format")

            assert client._is_recoverable_error(mock_error) is False


class TestLLMClientResponseCaching:
    """Tests for response caching in LLM clients."""

    @pytest.mark.asyncio
    async def test_mock_client_caches_identical_prompts(self):
        """MockLLMClient caches responses for identical prompts."""
        client = MockLLMClient()

        # First call
        response1 = await client.send_prompt("system", "user")

        # Second call with same prompts
        response2 = await client.send_prompt("system", "user")

        # Should be identical (cached)
        assert response1 == response2

    @pytest.mark.asyncio
    async def test_mock_client_different_prompts_different_cache_keys(self):
        """MockLLMClient uses different cache keys for different prompts."""
        client = MockLLMClient()

        # Generate cache keys
        key1 = client._get_cache_key("system1", "user1")
        key2 = client._get_cache_key("system2", "user2")

        assert key1 != key2


class TestBaseLLMClientInterface:
    """Tests for BaseLLMClient abstract interface."""

    def test_mock_client_is_base_llm_client(self):
        """MockLLMClient is a BaseLLMClient."""
        client = MockLLMClient()
        assert isinstance(client, BaseLLMClient)

    def test_real_client_is_base_llm_client(self):
        """RealLLMClient is a BaseLLMClient."""
        with patch('src.mcp_servers.llm_integration.settings') as mock_settings:
            mock_settings.deepseek_api_key = "key"
            mock_settings.deepseek_base_url = "https://api.deepseek.com/v1"
            mock_settings.deepseek_model_name = "deepseek-chat"
            mock_settings.openai_api_key = ""

            client = RealLLMClient()
            assert isinstance(client, BaseLLMClient)
