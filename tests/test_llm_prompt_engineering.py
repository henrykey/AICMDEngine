"""
Tests for LLM Prompt Engineering - Task 4 Phase 2.1 Week 1

Tests the system prompt, few-shot examples, and input context template
for BPMN generation using Mock LLM client.

Following TDD: RED → GREEN → REFACTOR
"""

import pytest
from typing import Dict, Any, List


class TestSystemPromptBuilder:
    """Test system prompt builder for BPMN generation"""

    @pytest.mark.asyncio
    async def test_system_prompt_includes_all_executor_patterns(self):
        """
        RED: Test that system prompt includes all 5 executor patterns

        Given: system prompt builder is called
        When: call build_system_prompt()
        Then: return prompt string containing all 5 executor pattern names
        """
        from src.mcp_servers.bpmn_mcp import build_system_prompt

        prompt = await build_system_prompt()

        # Verify all 5 executor patterns are mentioned
        assert "static" in prompt.lower()
        assert "form_driven" in prompt.lower() or "form-driven" in prompt.lower()
        assert "dynamic" in prompt.lower()
        assert "queue_claim" in prompt.lower() or "queue-claim" in prompt.lower()
        assert "automation" in prompt.lower()

    @pytest.mark.asyncio
    async def test_system_prompt_includes_bpmn_structure_guidance(self):
        """
        RED: Test that system prompt includes BPMN structure guidance

        Given: system prompt builder is called
        When: call build_system_prompt()
        Then: return prompt containing BPMN structure guidance
        """
        from src.mcp_servers.bpmn_mcp import build_system_prompt

        prompt = await build_system_prompt()

        # Verify BPMN guidance
        assert "bpmn" in prompt.lower()
        assert "xml" in prompt.lower() or "start" in prompt.lower()
        assert "process" in prompt.lower()

    @pytest.mark.asyncio
    async def test_system_prompt_includes_json_documentation_format(self):
        """
        RED: Test that system prompt specifies JSON documentation format

        Given: system prompt builder is called
        When: call build_system_prompt()
        Then: return prompt containing JSON format specification
        """
        from src.mcp_servers.bpmn_mcp import build_system_prompt

        prompt = await build_system_prompt()

        # Verify JSON format specification
        assert "json" in prompt.lower()
        assert "documentation" in prompt.lower()


class TestFewShotExamples:
    """Test few-shot examples for BPMN generation"""

    @pytest.mark.asyncio
    async def test_few_shot_examples_structure(self):
        """
        RED: Test that few-shot examples have correct structure

        Given: few-shot examples builder is called
        When: call get_few_shot_examples()
        Then: return list with 3-5 examples, each with input/output
        """
        from src.mcp_servers.bpmn_mcp import get_few_shot_examples

        examples = await get_few_shot_examples()

        # Verify structure
        assert isinstance(examples, list)
        assert len(examples) >= 3
        assert len(examples) <= 5

        # Verify each example has input and output
        for example in examples:
            assert isinstance(example, dict)
            assert "input" in example
            assert "output" in example

    @pytest.mark.asyncio
    async def test_few_shot_examples_include_different_patterns(self):
        """
        RED: Test that few-shot examples cover different executor patterns

        Given: few-shot examples builder is called
        When: call get_few_shot_examples()
        Then: return examples demonstrating different executor patterns
        """
        from src.mcp_servers.bpmn_mcp import get_few_shot_examples

        examples = await get_few_shot_examples()

        # Check that examples demonstrate various patterns
        outputs = [example["output"] for example in examples]
        combined_output = " ".join(outputs).lower()

        # Should have examples of at least 3 different patterns
        patterns_found = 0
        if "static" in combined_output:
            patterns_found += 1
        if "form" in combined_output:
            patterns_found += 1
        if "dynamic" in combined_output:
            patterns_found += 1

        assert patterns_found >= 2  # At least 2 different patterns in examples

    @pytest.mark.asyncio
    async def test_few_shot_examples_output_contains_valid_bpmn(self):
        """
        RED: Test that few-shot example outputs contain valid BPMN XML

        Given: few-shot examples builder is called
        When: call get_few_shot_examples()
        Then: return examples with BPMN XML in output
        """
        from src.mcp_servers.bpmn_mcp import get_few_shot_examples

        examples = await get_few_shot_examples()

        # Verify examples contain BPMN XML
        for example in examples:
            output = example["output"]
            assert "bpmn" in output.lower() or "<?xml" in output
            assert "process" in output.lower()


class TestInputContextTemplate:
    """Test input context template for BPMN generation"""

    @pytest.mark.asyncio
    async def test_input_context_template_structure(self):
        """
        RED: Test that input context template has required fields

        Given: input context template builder is called
        When: call build_input_context(tenant_id, description, org_context)
        Then: return context dict with required fields
        """
        from src.mcp_servers.bpmn_mcp import build_input_context

        org_context = {
            "departments": [{"id": "d1", "name": "finance"}],
            "roles": [{"id": "r1", "name": "approver"}],
            "members": [{"id": "m1", "name": "John"}]
        }

        context = await build_input_context(
            tenant_id="tenant_123",
            description="Approve purchase orders over $5000",
            org_context=org_context
        )

        # Verify required fields
        assert "description" in context
        assert "org_context" in context
        assert "available_executor_patterns" in context

    @pytest.mark.asyncio
    async def test_input_context_includes_org_entities(self):
        """
        RED: Test that input context includes organization entities

        Given: org_context with departments, roles, members
        When: call build_input_context()
        Then: return context with formatted org entities
        """
        from src.mcp_servers.bpmn_mcp import build_input_context

        org_context = {
            "departments": [{"id": "d1", "name": "finance"}],
            "roles": [{"id": "r1", "name": "approver"}, {"id": "r2", "name": "reviewer"}],
            "members": [{"id": "m1", "name": "John"}]
        }

        context = await build_input_context(
            tenant_id="tenant_123",
            description="Test process",
            org_context=org_context
        )

        # Verify org entities are included
        org_in_context = context["org_context"]
        assert "departments" in org_in_context
        assert "roles" in org_in_context
        assert "members" in org_in_context


class TestMockLLMClient:
    """Test Mock LLM client for testing BPMN generation"""

    @pytest.mark.asyncio
    async def test_mock_llm_client_responds_to_prompt(self):
        """
        RED: Test that Mock LLM client responds to prompts

        Given: Mock LLM client is instantiated
        When: call send_prompt(system_prompt, user_prompt)
        Then: return response string
        """
        from src.mcp_servers.bpmn_mcp import MockLLMClient

        client = MockLLMClient()

        system_prompt = "You are a BPMN expert."
        user_prompt = "Create a simple approval process."

        response = await client.send_prompt(system_prompt, user_prompt)

        # Verify response
        assert isinstance(response, str)
        assert len(response) > 0

    @pytest.mark.asyncio
    async def test_mock_llm_client_returns_consistent_responses(self):
        """
        RED: Test that Mock LLM client returns consistent responses

        Given: Same prompts sent twice
        When: call send_prompt() twice with same inputs
        Then: return same response both times
        """
        from src.mcp_servers.bpmn_mcp import MockLLMClient

        client = MockLLMClient()

        system_prompt = "You are a BPMN expert."
        user_prompt = "Create a simple approval process."

        response1 = await client.send_prompt(system_prompt, user_prompt)
        response2 = await client.send_prompt(system_prompt, user_prompt)

        # Mock client should return consistent responses
        assert response1 == response2


class TestPromptValidation:
    """Test prompt validation with Mock LLM"""

    @pytest.mark.asyncio
    async def test_prompt_validation_detects_valid_bpmn(self):
        """
        RED: Test that prompt validation detects valid BPMN in response

        Given: Mock LLM returns valid BPMN XML
        When: call validate_prompt_response(response)
        Then: return {valid: True, confidence: >= 0.8}
        """
        from src.mcp_servers.bpmn_mcp import validate_prompt_response

        # Valid BPMN response
        response = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
  <bpmn:process id="Process_1">
    <bpmn:startEvent id="StartEvent_1"/>
    <bpmn:endEvent id="EndEvent_1"/>
  </bpmn:process>
</bpmn:definitions>"""

        result = await validate_prompt_response(response)

        assert result["valid"] is True
        assert result.get("confidence", 1.0) >= 0.7

    @pytest.mark.asyncio
    async def test_prompt_validation_detects_invalid_bpmn(self):
        """
        RED: Test that prompt validation rejects invalid BPMN

        Given: Mock LLM returns invalid XML
        When: call validate_prompt_response(response)
        Then: return {valid: False, errors: [...]}
        """
        from src.mcp_servers.bpmn_mcp import validate_prompt_response

        # Invalid XML response
        response = """Invalid XML <process>"""

        result = await validate_prompt_response(response)

        assert result["valid"] is False
        assert "errors" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
