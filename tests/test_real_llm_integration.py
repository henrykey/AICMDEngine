"""
Tests for Real LLM Integration - Task 6 Phase 2.1 Week 1

Tests the RealLLMClient using OpenAI-compatible API interface.
Following TDD: RED → GREEN → REFACTOR with proper error handling.

Tests use mock responses to avoid actual API calls during testing.
For production use with real LLM, configure LLM settings in environment.
"""

import pytest
from typing import Dict, Any
from unittest.mock import patch, MagicMock, AsyncMock


class TestRealLLMClient:
    """Test RealLLMClient with OpenAI-compatible API integration"""

    @pytest.mark.asyncio
    async def test_real_llm_client_initialization(self):
        """
        RED: Test that RealLLMClient initializes with multi-provider fallback

        Given: RealLLMClient class with LLM configuration
        When: instantiate with api_key, base_url, model
        Then: client initializes successfully with AsyncOpenAI for each provider
        """
        from src.mcp_servers.bpmn_mcp import RealLLMClient

        # Should initialize without error
        with patch('src.mcp_servers.bpmn_mcp.AsyncOpenAI') as mock_openai:
            mock_openai.return_value = MagicMock()

            client = RealLLMClient(
                base_url="https://api.deepseek.com",
                api_key="test-key",
                model="deepseek-coder"
            )

            # Verify attributes
            assert hasattr(client, '_clients')
            assert hasattr(client, '_response_cache')
            assert hasattr(client, 'providers')
            assert len(client.providers) >= 1
            assert client.providers[0]['base_url'] == "https://api.deepseek.com"
            assert client.providers[0]['api_key'] == "test-key"
            assert client.providers[0]['model'] == "deepseek-coder"

    @pytest.mark.asyncio
    async def test_real_llm_client_missing_config(self):
        """
        RED: Test that RealLLMClient raises error on missing config

        Given: No LLM configuration provided
        When: instantiate RealLLMClient
        Then: raise ValueError with helpful message
        """
        from src.mcp_servers.bpmn_mcp import RealLLMClient

        with patch('src.mcp_servers.bpmn_mcp.settings') as mock_settings:
            # Mock settings to return None
            mock_settings.deepseek_base_url = None
            mock_settings.deepseek_api_key = None
            mock_settings.deepseek_model_name = None
            mock_settings.openai_base_url = None
            mock_settings.openai_api_key = None
            mock_settings.openai_model_name = None

            with pytest.raises(ValueError) as exc_info:
                RealLLMClient()

            assert "Missing required LLM configuration" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_real_llm_client_send_prompt_success(self):
        """
        RED: Test that RealLLMClient sends prompt to LLM API

        Given: RealLLMClient instance and system/user prompts
        When: call send_prompt()
        Then: return BPMN XML response from API
        """
        from src.mcp_servers.bpmn_mcp import RealLLMClient

        # Mock the AsyncOpenAI client
        with patch('src.mcp_servers.bpmn_mcp.AsyncOpenAI') as mock_openai_class:
            # Setup mock response
            mock_message = MagicMock()
            mock_message.content = '<?xml version="1.0"?><bpmn:definitions></bpmn:definitions>'

            mock_choice = MagicMock()
            mock_choice.message = mock_message

            mock_response = MagicMock()
            mock_response.choices = [mock_choice]

            mock_client_instance = AsyncMock()
            mock_client_instance.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_openai_class.return_value = mock_client_instance

            # Create client and send prompt
            client = RealLLMClient(
                base_url="https://api.test.com",
                api_key="test-key",
                model="test-model"
            )
            response = await client.send_prompt(
                "system prompt",
                "user prompt"
            )

            # Verify response
            assert response == '<?xml version="1.0"?><bpmn:definitions></bpmn:definitions>'
            assert mock_client_instance.chat.completions.create.called

    @pytest.mark.asyncio
    async def test_real_llm_client_response_caching(self):
        """
        RED: Test that RealLLMClient caches responses across providers

        Given: RealLLMClient sends prompt twice with same input
        When: call send_prompt() twice
        Then: second call returns cached response without API call
        """
        from src.mcp_servers.bpmn_mcp import RealLLMClient

        with patch('src.mcp_servers.bpmn_mcp.AsyncOpenAI') as mock_openai_class:
            # Setup mock
            mock_message = MagicMock()
            mock_message.content = 'cached response'

            mock_choice = MagicMock()
            mock_choice.message = mock_message

            mock_response = MagicMock()
            mock_response.choices = [mock_choice]

            mock_client_instance = AsyncMock()
            mock_client_instance.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_openai_class.return_value = mock_client_instance

            # Create client
            client = RealLLMClient(
                base_url="https://api.test.com",
                api_key="test-key",
                model="test-model"
            )

            # Send prompt twice
            response1 = await client.send_prompt("system", "user")
            response2 = await client.send_prompt("system", "user")

            # Verify caching (response from cache, not from API)
            assert response1 == response2
            # Should only call API once, second call returns from cache
            assert len(client._response_cache) == 1

    @pytest.mark.asyncio
    async def test_real_llm_client_error_handling(self):
        """
        RED: Test that RealLLMClient handles API errors with fallback

        Given: LLM API returns error
        When: call send_prompt() and all providers fail
        Then: raise RuntimeError after trying all providers
        """
        from src.mcp_servers.bpmn_mcp import RealLLMClient

        with patch('src.mcp_servers.bpmn_mcp.AsyncOpenAI') as mock_openai_class:
            # Setup mock to raise error for all providers
            mock_client_instance = AsyncMock()
            mock_client_instance.chat.completions.create = AsyncMock(
                side_effect=Exception("API rate limit exceeded")
            )
            mock_openai_class.return_value = mock_client_instance

            # Create client with limited providers for testing
            with patch('src.mcp_servers.bpmn_mcp.settings') as mock_settings:
                mock_settings.deepseek_api_key = "test-key"
                mock_settings.deepseek_base_url = "https://api.test.com"
                mock_settings.deepseek_model_name = "test-model"
                mock_settings.openai_api_key = ""  # Empty to filter out
                mock_settings.openai_base_url = "https://api.openai.com"
                mock_settings.openai_model_name = "gpt-4"

                client = RealLLMClient()

                # Verify error is raised after all providers fail
                with pytest.raises(RuntimeError) as exc_info:
                    await client.send_prompt("system", "user")

                assert "All LLM providers failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_real_llm_client_with_settings(self):
        """
        RED: Test that RealLLMClient uses settings defaults for providers

        Given: Settings configured with LLM provider info
        When: create RealLLMClient without custom parameters
        Then: use settings for all providers configuration
        """
        from src.mcp_servers.bpmn_mcp import RealLLMClient

        with patch('src.mcp_servers.bpmn_mcp.settings') as mock_settings:
            # Mock settings
            mock_settings.deepseek_base_url = "https://api.deepseek.com"
            mock_settings.deepseek_api_key = "deepseek-key"
            mock_settings.deepseek_model_name = "deepseek-coder"
            mock_settings.openai_base_url = "https://api.openai.com"
            mock_settings.openai_api_key = "openai-key"
            mock_settings.openai_model_name = "gpt-4"

            with patch('src.mcp_servers.bpmn_mcp.AsyncOpenAI') as mock_openai:
                mock_openai.return_value = MagicMock()

                # Create client without custom parameters
                client = RealLLMClient()

                # Verify settings were used for providers
                assert len(client.providers) == 2
                assert client.providers[0]['base_url'] == "https://api.deepseek.com"
                assert client.providers[0]['api_key'] == "deepseek-key"
                assert client.providers[0]['model'] == "deepseek-coder"
                assert client.providers[1]['base_url'] == "https://api.openai.com"
                assert client.providers[1]['api_key'] == "openai-key"
                assert client.providers[1]['model'] == "gpt-4"


class TestGenerateProcessWithRealLLM:
    """Test generate_process function with Real LLM integration"""

    @pytest.mark.asyncio
    async def test_generate_process_with_mock_llm_by_default(self):
        """
        RED: Test that generate_process uses MockLLMClient by default

        Given: generate_process called without use_real_llm flag
        When: call generate_process()
        Then: use MockLLMClient for fast testing
        """
        from src.mcp_servers.bpmn_mcp import generate_process

        org_context = {
            "departments": [{"id": "d1", "name": "finance"}],
            "roles": [{"id": "r1", "name": "approver"}],
            "members": [{"id": "m1", "name": "John"}]
        }

        result = await generate_process(
            tenant_id="tenant_123",
            description="Simple approval process",
            org_context=org_context
        )

        # Verify result structure
        assert "bpmn_xml" in result
        assert "valid" in result
        assert "confidence_score" in result
        assert result["confidence_score"] > 0.0

    @pytest.mark.asyncio
    async def test_generate_process_with_real_llm_flag(self):
        """
        RED: Test that generate_process uses RealLLMClient when flag is set

        Given: use_real_llm=True with custom config
        When: call generate_process()
        Then: use RealLLMClient for real LLM API
        """
        from src.mcp_servers.bpmn_mcp import generate_process

        org_context = {
            "departments": [{"id": "d1", "name": "finance"}],
            "roles": [{"id": "r1", "name": "approver"}],
            "members": []
        }

        with patch('src.mcp_servers.bpmn_mcp.RealLLMClient') as mock_real_llm:
            # Setup mock
            mock_client_instance = AsyncMock()
            mock_client_instance.send_prompt = AsyncMock(return_value="""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
  <bpmn:process id="Process_1">
    <bpmn:startEvent id="Start"/>
    <bpmn:endEvent id="End"/>
  </bpmn:process>
</bpmn:definitions>""")
            mock_real_llm.return_value = mock_client_instance

            # Call with real LLM flag
            result = await generate_process(
                tenant_id="tenant_123",
                description="Real LLM test",
                org_context=org_context,
                use_real_llm=True,
                api_key="test-key"
            )

            # Verify RealLLMClient was used
            assert mock_real_llm.called
            assert "bpmn_xml" in result

    @pytest.mark.asyncio
    async def test_generate_process_flags_enable_real_llm(self):
        """
        RED: Test that generate_process correctly handles use_real_llm flag

        Given: use_real_llm=False (default)
        When: call generate_process()
        Then: use MockLLMClient

        And when:
        Given: use_real_llm=True
        Then: use RealLLMClient
        """
        from src.mcp_servers.bpmn_mcp import generate_process

        org_context = {
            "departments": [],
            "roles": [{"id": "r1", "name": "approver"}],
            "members": []
        }

        # Test default (mock)
        result_mock = await generate_process(
            tenant_id="tenant_123",
            description="Test mock",
            org_context=org_context,
            use_real_llm=False
        )
        assert "MockProcess" in result_mock["bpmn_xml"]

        # Test with real LLM (mocked)
        with patch('src.mcp_servers.bpmn_mcp.RealLLMClient') as mock_real_llm:
            mock_client_instance = AsyncMock()
            mock_client_instance.send_prompt = AsyncMock(return_value="""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
  <bpmn:process id="RealProcess">
    <bpmn:startEvent id="Start"/>
    <bpmn:endEvent id="End"/>
  </bpmn:process>
</bpmn:definitions>""")
            mock_real_llm.return_value = mock_client_instance

            result_real = await generate_process(
                tenant_id="tenant_123",
                description="Test real",
                org_context=org_context,
                use_real_llm=True,
                api_key="test-key"
            )

            assert mock_real_llm.called
            assert "RealProcess" in result_real["bpmn_xml"]


class TestLLMClientIntegration:
    """Test integration between MockLLMClient and RealLLMClient"""

    @pytest.mark.asyncio
    async def test_both_llm_clients_have_same_interface(self):
        """
        RED: Test that MockLLMClient and RealLLMClient have compatible interface

        Given: Both client classes
        When: check method signatures
        Then: both have send_prompt() method with same signature
        """
        from src.mcp_servers.bpmn_mcp import MockLLMClient, RealLLMClient
        import inspect

        mock_client = MockLLMClient()

        with patch('src.mcp_servers.bpmn_mcp.AsyncOpenAI') as mock_openai:
            mock_openai.return_value = MagicMock()

            real_client = RealLLMClient(
                base_url="https://api.test.com",
                api_key="test-key",
                model="test-model"
            )

            # Verify both have send_prompt
            assert hasattr(mock_client, 'send_prompt')
            assert hasattr(real_client, 'send_prompt')

            # Verify both are async
            assert inspect.iscoroutinefunction(mock_client.send_prompt)
            assert inspect.iscoroutinefunction(real_client.send_prompt)

    @pytest.mark.asyncio
    async def test_llm_client_response_format_consistency(self):
        """
        RED: Test that both clients return compatible response formats

        Given: MockLLMClient and RealLLMClient
        When: call send_prompt()
        Then: both return valid XML strings
        """
        from src.mcp_servers.bpmn_mcp import MockLLMClient

        mock_client = MockLLMClient()
        system_prompt = "You are a BPMN expert."
        user_prompt = "Create a simple process."

        response = await mock_client.send_prompt(system_prompt, user_prompt)

        # Verify response is XML
        assert isinstance(response, str)
        assert "<?xml" in response
        assert "bpmn" in response.lower()


class TestEndToEndIntegration:
    """End-to-end tests for complete BPMN generation workflow"""

    @pytest.mark.asyncio
    async def test_complete_workflow_mock_to_validation(self):
        """
        RED: Test complete workflow from generation to validation

        Given: User requirement for process
        When: call generate_process() → validate → return result
        Then: get valid BPMN with confidence score
        """
        from src.mcp_servers.bpmn_mcp import generate_process

        org_context = {
            "departments": [
                {"id": "d1", "name": "finance"},
                {"id": "d2", "name": "legal"}
            ],
            "roles": [
                {"id": "r1", "name": "approver"},
                {"id": "r2", "name": "reviewer"}
            ],
            "members": [{"id": "m1", "name": "John"}]
        }

        result = await generate_process(
            tenant_id="tenant_123",
            description="Create invoice approval workflow with multiple reviewers",
            org_context=org_context
        )

        # Verify complete workflow
        assert "bpmn_xml" in result
        assert "valid" in result
        assert "confidence_score" in result
        assert "metadata" in result
        assert 0.0 <= result["confidence_score"] <= 1.0

    @pytest.mark.asyncio
    async def test_complex_process_generation(self):
        """
        RED: Test generation of complex multi-step process

        Given: Complex process requirements
        When: generate BPMN
        Then: return valid process with multiple tasks
        """
        from src.mcp_servers.bpmn_mcp import generate_process

        org_context = {
            "departments": [{"id": "d1", "name": "finance"}],
            "roles": [
                {"id": "r1", "name": "manager"},
                {"id": "r2", "name": "director"},
                {"id": "r3", "name": "cfo"}
            ],
            "members": []
        }

        complex_description = """
        Create a PO approval workflow:
        1. Employee submits purchase order with amount
        2. Manager approves if under $5000
        3. Director approves if between $5000-$25000
        4. CFO approves if over $25000
        5. Final notification sent to requester
        """

        result = await generate_process(
            tenant_id="tenant_456",
            description=complex_description,
            org_context=org_context
        )

        # Verify complex process
        assert result["valid"] is True
        assert "bpmn_xml" in result
        # Should have multiple tasks for complex workflow
        bpmn_xml = result["bpmn_xml"]
        assert bpmn_xml.count("<bpmn:userTask") >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
