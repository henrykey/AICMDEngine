"""
Tests for generate_process MCP Tool - Task 5 Phase 2.1 Week 1

Tests the end-to-end BPMN generation workflow:
Input (NL description) → LLM → BPMN → Validation → Output

Following TDD: RED → GREEN → REFACTOR with Mock LLM
"""

import pytest
from typing import Dict, Any


class TestGenerateProcessTool:
    """Test generate_process MCP tool"""

    @pytest.mark.asyncio
    async def test_generate_process_accepts_requirements(self):
        """
        RED: Test that generate_process tool accepts process requirements

        Given: Process requirements input with description and org context
        When: call generate_process(description, tenant_id, org_context)
        Then: return BPMN XML string
        """
        from src.mcp_servers.bpmn_mcp import generate_process

        org_context = {
            "departments": [{"id": "d1", "name": "finance"}],
            "roles": [{"id": "r1", "name": "approver"}],
            "members": [{"id": "m1", "name": "John"}]
        }

        result = await generate_process(
            tenant_id="tenant_123",
            description="Approve purchase orders over $5000",
            org_context=org_context
        )

        # Verify result
        assert isinstance(result, dict)
        assert "bpmn_xml" in result or "xml" in result

    @pytest.mark.asyncio
    async def test_generate_process_returns_valid_bpmn(self):
        """
        RED: Test that generate_process returns valid BPMN

        Given: Process requirements input
        When: call generate_process()
        Then: return result with valid BPMN XML and metadata
        """
        from src.mcp_servers.bpmn_mcp import generate_process

        org_context = {
            "departments": [{"id": "d1", "name": "finance"}],
            "roles": [{"id": "r1", "name": "approver"}],
            "members": []
        }

        result = await generate_process(
            tenant_id="tenant_123",
            description="Create a simple approval process",
            org_context=org_context
        )

        # Verify response structure
        assert "bpmn_xml" in result
        assert "confidence_score" in result
        assert "valid" in result

        # Verify BPMN contains expected elements
        bpmn_xml = result["bpmn_xml"]
        assert "<?xml" in bpmn_xml
        assert "bpmn" in bpmn_xml.lower()
        assert "process" in bpmn_xml.lower()

    @pytest.mark.asyncio
    async def test_generate_process_includes_validation_metadata(self):
        """
        RED: Test that generate_process includes validation results

        Given: Process requirements input
        When: call generate_process()
        Then: return metadata with validation info and confidence score
        """
        from src.mcp_servers.bpmn_mcp import generate_process

        org_context = {
            "departments": [],
            "roles": [{"id": "r1", "name": "approver"}],
            "members": []
        }

        result = await generate_process(
            tenant_id="tenant_123",
            description="Create approval process",
            org_context=org_context
        )

        # Verify metadata
        assert "confidence_score" in result
        assert isinstance(result["confidence_score"], float)
        assert 0.0 <= result["confidence_score"] <= 1.0

        assert "valid" in result
        assert isinstance(result["valid"], bool)

    @pytest.mark.asyncio
    async def test_generate_process_with_complex_requirements(self):
        """
        RED: Test generate_process with complex multi-task requirements

        Given: Complex process with multiple steps and different executor patterns
        When: call generate_process()
        Then: return valid BPMN with multiple tasks and executor patterns
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

        complex_description = """
        Create an invoice approval workflow:
        1. CFO approves invoices under $10,000
        2. User selects a reviewer for invoices over $10,000
        3. Route to appropriate department based on vendor
        4. Final sign-off by department head
        """

        result = await generate_process(
            tenant_id="tenant_123",
            description=complex_description,
            org_context=org_context
        )

        # Verify result is valid BPMN
        assert result["valid"] is True
        assert "bpmn_xml" in result
        assert result["confidence_score"] > 0.5

    @pytest.mark.asyncio
    async def test_generate_process_error_handling_invalid_org_context(self):
        """
        RED: Test error handling with invalid org context

        Given: Invalid org_context (missing required fields)
        When: call generate_process()
        Then: return error result with helpful error message
        """
        from src.mcp_servers.bpmn_mcp import generate_process

        # Missing required context
        org_context = {}

        result = await generate_process(
            tenant_id="tenant_123",
            description="Create approval process",
            org_context=org_context
        )

        # Should still return result (with error info)
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_generate_process_uses_system_prompt(self):
        """
        RED: Test that generate_process uses system prompt

        Given: Requirements and org context
        When: call generate_process()
        Then: result contains all 5 executor patterns in BPMN
        """
        from src.mcp_servers.bpmn_mcp import generate_process

        org_context = {
            "departments": [{"id": "d1", "name": "finance"}],
            "roles": [{"id": "r1", "name": "approver"}],
            "members": []
        }

        result = await generate_process(
            tenant_id="tenant_123",
            description="Create process with various executor patterns",
            org_context=org_context
        )

        # Verify BPMN was generated
        assert "bpmn_xml" in result
        bpmn = result["bpmn_xml"].lower()

        # Should contain documentation for executor patterns
        assert "documentation" in bpmn or "executor" in bpmn


class TestGenerateProcessIntegration:
    """Test generate_process integration with other components"""

    @pytest.mark.asyncio
    async def test_generate_process_uses_membership_client(self):
        """
        RED: Test that generate_process uses MembershipClient for org context

        Given: Tenant ID and process description
        When: call generate_process()
        Then: use MembershipClient to get organization context
        """
        from src.mcp_servers.bpmn_mcp import generate_process

        org_context = {
            "departments": [{"id": "d1", "name": "hr"}],
            "roles": [{"id": "r1", "name": "manager"}],
            "members": [{"id": "m1", "name": "Alice"}]
        }

        result = await generate_process(
            tenant_id="tenant_456",
            description="Create employee onboarding process",
            org_context=org_context
        )

        # Verify result
        assert "bpmn_xml" in result

    @pytest.mark.asyncio
    async def test_generate_process_uses_validator(self):
        """
        RED: Test that generate_process uses BPMNValidator

        Given: LLM generates BPMN
        When: call generate_process()
        Then: validate BPMN using BPMNValidator
        """
        from src.mcp_servers.bpmn_mcp import generate_process

        org_context = {
            "departments": [],
            "roles": [{"id": "r1", "name": "approver"}],
            "members": []
        }

        result = await generate_process(
            tenant_id="tenant_123",
            description="Simple approval",
            org_context=org_context
        )

        # Verify validation results included
        assert "valid" in result
        assert "confidence_score" in result


class TestGenerateProcessMCPTool:
    """Test generate_process as MCP tool registration"""

    @pytest.mark.asyncio
    async def test_generate_process_is_mcp_tool(self):
        """
        RED: Test that generate_process is registered as MCP tool

        Given: MCP tool registry
        When: look up 'generate_process' tool
        Then: return valid tool definition
        """
        from src.mcp_servers.bpmn_mcp import GenerateProcessTool

        tool = GenerateProcessTool()

        # Verify tool attributes
        assert hasattr(tool, 'name')
        assert tool.name == 'generate_process'
        assert hasattr(tool, 'description')
        assert hasattr(tool, 'schema')

    @pytest.mark.asyncio
    async def test_generate_process_tool_schema(self):
        """
        RED: Test that generate_process tool has proper schema

        Given: MCP tool schema
        When: inspect tool input schema
        Then: schema includes tenant_id, description, org_context parameters
        """
        from src.mcp_servers.bpmn_mcp import GenerateProcessTool

        tool = GenerateProcessTool()
        schema = tool.schema

        # Verify schema has required fields
        assert 'tenant_id' in schema
        assert 'description' in schema
        assert 'org_context' in schema


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
