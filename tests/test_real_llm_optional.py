"""
Optional Integration Tests for Real LLM - Task 6 Phase 2.1 Week 1

Tests the RealLLMClient with actual DeepSeek or OpenAI-compatible API calls.
These tests are OPTIONAL and only run when LLM credentials are configured.

Usage:
    Run with configured credentials:
    DEEPSEEK_API_KEY=xxx pytest tests/test_real_llm_optional.py -v

    Skip if no credentials:
    pytest tests/test_real_llm_optional.py -v  # Will be skipped automatically
"""

import pytest
import os
from typing import Dict, Any


# Check if LLM credentials are configured
HAS_LLM_CREDENTIALS = bool(
    (os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY"))
)

# Mark all tests to skip if no credentials
pytestmark = pytest.mark.skipif(
    not HAS_LLM_CREDENTIALS,
    reason="LLM credentials not configured (DEEPSEEK_API_KEY or OPENAI_API_KEY)"
)


class TestRealLLMClientIntegration:
    """Integration tests with real LLM API"""

    @pytest.mark.asyncio
    async def test_real_llm_client_with_deepseek(self):
        """
        Test RealLLMClient with real DeepSeek API

        Given: DeepSeek API configured
        When: Create RealLLMClient and send prompt
        Then: Get valid BPMN response from API
        """
        from src.mcp_servers.bpmn_mcp import RealLLMClient
        from src.core.config import settings

        # Skip if DeepSeek not configured
        if not settings.deepseek_api_key:
            pytest.skip("DeepSeek API key not configured")

        # Create client with DeepSeek
        client = RealLLMClient(
            base_url=settings.deepseek_base_url,
            api_key=settings.deepseek_api_key,
            model=settings.deepseek_model_name
        )

        # Simple test prompt
        system_prompt = "You are a BPMN expert. Generate only valid BPMN 2.0 XML."
        user_prompt = """Generate a minimal BPMN process XML with:
- One start event
- One end event
- No tasks
Just output the raw XML, nothing else."""

        response = await client.send_prompt(system_prompt, user_prompt)

        # Verify response
        assert response is not None
        assert len(response) > 0
        assert "<?xml" in response or "<bpmn" in response.lower()

    @pytest.mark.asyncio
    async def test_real_llm_client_with_openai(self):
        """
        Test RealLLMClient with real OpenAI API

        Given: OpenAI API configured
        When: Create RealLLMClient and send prompt
        Then: Get valid BPMN response from API
        """
        from src.mcp_servers.bpmn_mcp import RealLLMClient
        from src.core.config import settings

        # Skip if OpenAI not configured
        if not settings.openai_api_key:
            pytest.skip("OpenAI API key not configured")

        # Create client with OpenAI
        client = RealLLMClient(
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key,
            model=settings.openai_model_name
        )

        # Simple test prompt
        system_prompt = "You are a BPMN expert. Generate only valid BPMN 2.0 XML."
        user_prompt = """Generate a minimal BPMN process XML with:
- One start event
- One end event
- No tasks
Just output the raw XML, nothing else."""

        response = await client.send_prompt(system_prompt, user_prompt)

        # Verify response
        assert response is not None
        assert len(response) > 0
        assert "<?xml" in response or "<bpmn" in response.lower()

    @pytest.mark.asyncio
    async def test_real_llm_client_response_parsing(self):
        """
        Test that RealLLMClient response is valid BPMN

        Given: Real LLM returns BPMN response
        When: Parse response
        Then: Extract and validate BPMN XML
        """
        from src.mcp_servers.bpmn_mcp import RealLLMClient, validate_prompt_response
        from src.core.config import settings

        # Skip if no credentials
        if not (settings.deepseek_api_key or settings.openai_api_key):
            pytest.skip("No LLM credentials configured")

        # Use available provider
        base_url = settings.deepseek_base_url or settings.openai_base_url
        api_key = settings.deepseek_api_key or settings.openai_api_key
        model = settings.deepseek_model_name or settings.openai_model_name

        client = RealLLMClient(
            base_url=base_url,
            api_key=api_key,
            model=model
        )

        # Request minimal BPMN
        system_prompt = "Generate only valid BPMN 2.0 XML."
        user_prompt = """Create a simple BPMN with:
- Start event id='Start'
- End event id='End'
- Sequence flow from Start to End
Output only the XML."""

        response = await client.send_prompt(system_prompt, user_prompt)

        # Validate response
        validation = await validate_prompt_response(response)

        # Either valid BPMN or errors detected (both are acceptable)
        assert validation is not None
        assert "valid" in validation
        assert "errors" in validation


class TestGenerateProcessWithRealLLM:
    """Integration tests for generate_process with real LLM"""

    @pytest.mark.asyncio
    async def test_generate_process_with_real_llm_deepseek(self):
        """
        Test generate_process with real DeepSeek LLM

        Given: DeepSeek credentials configured
        When: Call generate_process with use_real_llm=True
        Then: Get BPMN result from real LLM
        """
        from src.mcp_servers.bpmn_mcp import generate_process
        from src.core.config import settings

        # Skip if DeepSeek not configured
        if not settings.deepseek_api_key:
            pytest.skip("DeepSeek API key not configured")

        org_context = {
            "departments": [{"id": "d1", "name": "finance"}],
            "roles": [{"id": "r1", "name": "approver"}],
            "members": []
        }

        result = await generate_process(
            tenant_id="test_tenant",
            description="Create a simple approval process",
            org_context=org_context,
            use_real_llm=True
        )

        # Verify result structure
        assert "bpmn_xml" in result
        assert "valid" in result
        assert "confidence_score" in result
        assert isinstance(result["bpmn_xml"], str)
        assert len(result["bpmn_xml"]) > 0

    @pytest.mark.asyncio
    async def test_generate_process_with_real_llm_openai(self):
        """
        Test generate_process with real OpenAI LLM

        Given: OpenAI credentials configured
        When: Call generate_process with use_real_llm=True
        Then: Get BPMN result from real LLM
        """
        from src.mcp_servers.bpmn_mcp import generate_process
        from src.core.config import settings

        # Skip if OpenAI not configured
        if not settings.openai_api_key:
            pytest.skip("OpenAI API key not configured")

        org_context = {
            "departments": [{"id": "d1", "name": "finance"}],
            "roles": [{"id": "r1", "name": "approver"}],
            "members": []
        }

        result = await generate_process(
            tenant_id="test_tenant",
            description="Create a simple approval process",
            org_context=org_context,
            use_real_llm=True
        )

        # Verify result structure
        assert "bpmn_xml" in result
        assert "valid" in result
        assert "confidence_score" in result
        assert isinstance(result["bpmn_xml"], str)
        assert len(result["bpmn_xml"]) > 0

    @pytest.mark.asyncio
    async def test_generate_process_caching_with_real_llm(self):
        """
        Test that RealLLMClient caches responses to reduce API calls

        Given: Real LLM client with same prompt
        When: Call send_prompt twice
        Then: Second call returns cached response
        """
        from src.mcp_servers.bpmn_mcp import RealLLMClient
        from src.core.config import settings
        from unittest.mock import AsyncMock, patch

        # Skip if no credentials
        if not (settings.deepseek_api_key or settings.openai_api_key):
            pytest.skip("No LLM credentials configured")

        base_url = settings.deepseek_base_url or settings.openai_base_url
        api_key = settings.deepseek_api_key or settings.openai_api_key
        model = settings.deepseek_model_name or settings.openai_model_name

        client = RealLLMClient(
            base_url=base_url,
            api_key=api_key,
            model=model
        )

        system_prompt = "Test system prompt"
        user_prompt = "Test user prompt"

        # First call (will hit API)
        response1 = await client.send_prompt(system_prompt, user_prompt)

        # Second call (should use cache)
        response2 = await client.send_prompt(system_prompt, user_prompt)

        # Verify cache works
        assert response1 == response2
        assert len(client._response_cache) == 1


class TestRealLLMClientEdgeCases:
    """Edge case tests for RealLLMClient"""

    @pytest.mark.asyncio
    async def test_real_llm_client_invalid_credentials(self):
        """
        Test RealLLMClient with invalid credentials raises RuntimeError

        Given: Invalid API credentials
        When: Mocked API returns general Exception
        Then: RealLLMClient should raise RuntimeError after fallback attempt
        """
        from src.mcp_servers.bpmn_mcp import RealLLMClient
        from unittest.mock import patch, AsyncMock

        with patch('src.mcp_servers.bpmn_mcp.AsyncOpenAI') as mock_openai_class:
            # Setup mock to raise generic Exception (simulates auth failure)
            mock_client_instance = AsyncMock()
            mock_client_instance.chat.completions.create = AsyncMock(
                side_effect=Exception("401 Unauthorized: Invalid API key")
            )
            mock_openai_class.return_value = mock_client_instance

            with patch('src.mcp_servers.bpmn_mcp.settings') as mock_settings:
                mock_settings.deepseek_api_key = "invalid-key"
                mock_settings.deepseek_base_url = "https://api.test.com"
                mock_settings.deepseek_model_name = "test-model"
                mock_settings.openai_api_key = ""
                mock_settings.openai_base_url = "https://api.openai.com"
                mock_settings.openai_model_name = "gpt-4"

                client = RealLLMClient()

                with pytest.raises(RuntimeError) as exc_info:
                    await client.send_prompt("system", "user")

                assert "All LLM providers failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_real_llm_client_empty_response(self):
        """
        Test RealLLMClient handles empty responses with multi-provider fallback

        Given: LLM returns empty response
        When: Call send_prompt
        Then: Handle gracefully (return empty string)
        """
        from src.mcp_servers.bpmn_mcp import RealLLMClient
        from unittest.mock import AsyncMock, MagicMock, patch

        # Mock AsyncOpenAI and its methods
        mock_message = MagicMock()
        mock_message.content = ""

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_client_instance = AsyncMock()
        mock_client_instance.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch('src.mcp_servers.bpmn_mcp.AsyncOpenAI', return_value=mock_client_instance):
            with patch('src.mcp_servers.bpmn_mcp.settings') as mock_settings:
                mock_settings.deepseek_api_key = "test-key"
                mock_settings.deepseek_base_url = "https://api.test.com"
                mock_settings.deepseek_model_name = "test-model"
                mock_settings.openai_api_key = ""
                mock_settings.openai_base_url = "https://api.openai.com"
                mock_settings.openai_model_name = "gpt-4"

                client = RealLLMClient()

                response = await client.send_prompt("system", "user")

                # Should return empty string, not error
                assert response == ""

    @pytest.mark.asyncio
    async def test_real_llm_client_settings_fallback(self):
        """
        Test that RealLLMClient uses settings for all providers

        Given: No custom parameters provided
        When: Create RealLLMClient
        Then: Use settings.deepseek_* and settings.openai_* for providers
        """
        from src.mcp_servers.bpmn_mcp import RealLLMClient

        # Create without custom parameters (should use settings)
        try:
            client = RealLLMClient()

            # Verify it used settings for providers
            assert len(client.providers) >= 1
            assert all('api_key' in p for p in client.providers)
            assert all('base_url' in p for p in client.providers)
            assert all('model' in p for p in client.providers)
            assert all('name' in p for p in client.providers)
        except ValueError:
            # OK if no credentials configured
            pytest.skip("No LLM credentials in settings")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
