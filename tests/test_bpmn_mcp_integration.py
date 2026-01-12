"""
Integration tests for BPMN-MCP in MCP Registry.

Tests that BPMN-MCP is properly registered and can be discovered/executed
through the MCP Registry system.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.mcp.registry import MCPRegistry
from src.mcp_servers.bpmn_mcp import BPMN_MCP


class TestBPMNMCPIntegration:
    """Integration tests for BPMN-MCP with MCP Registry"""

    @pytest.mark.asyncio
    async def test_bpmn_mcp_initialization(self):
        """RED: Test BPMN-MCP initializes properly"""
        mcp = BPMN_MCP(
            membership_base_url="http://localhost:8080",
            use_real_llm=False
        )

        assert mcp.name == "bpmn_mcp"
        assert mcp.version == "1.0.0"
        assert mcp.validator is not None

    @pytest.mark.asyncio
    async def test_bpmn_mcp_list_tools(self):
        """RED: Test BPMN-MCP lists available tools"""
        mcp = BPMN_MCP(
            membership_base_url="http://localhost:8080",
            use_real_llm=False
        )

        tools = await mcp.list_tools(tenant_id="test_tenant")

        tool_names = [t["name"] for t in tools]
        assert "generate_process" in tool_names
        assert "validate_process" in tool_names
        assert "suggest_executors" in tool_names
        assert "analyze_process_semantics" in tool_names

    @pytest.mark.asyncio
    async def test_bpmn_mcp_registration(self):
        """RED: Test BPMN-MCP can be registered in MCP registry"""
        registry = MCPRegistry()
        mcp = BPMN_MCP(
            membership_base_url="http://localhost:8080",
            use_real_llm=False
        )

        registry.register_mcp(mcp)

        # Verify registration
        assert registry.has_mcp("bpmn_mcp")
        assert registry.get_mcp("bpmn_mcp") == mcp

    @pytest.mark.asyncio
    async def test_bpmn_mcp_generate_process_tool(self):
        """RED: Test generate_process tool execution"""
        mcp = BPMN_MCP(
            membership_base_url="http://localhost:8080",
            use_real_llm=False
        )

        # Mock MembershipClient
        with patch('src.mcp_servers.bpmn_mcp.MembershipClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get_org_context = AsyncMock(return_value={
                "departments": [{"id": "dept_1", "name": "finance"}],
                "roles": [{"id": "role_1", "name": "approver"}],
                "members": [{"id": "mem_1", "name": "Alice"}]
            })
            mock_client_class.return_value = mock_client

            result = await mcp.execute_tool(
                tool_name="generate_process",
                params={
                    "process_name": "Approval Process",
                    "description": "A comprehensive approval process for all requests"
                },
                tenant_id="test_tenant"
            )

            assert result["success"] is True
            assert "bpmn_xml" in result

    @pytest.mark.asyncio
    async def test_bpmn_mcp_validate_process_tool(self):
        """RED: Test validate_process tool execution"""
        mcp = BPMN_MCP(
            membership_base_url="http://localhost:8080",
            use_real_llm=False
        )

        valid_bpmn = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Definitions_Test">
  <bpmn:process id="Process_Test" isExecutable="true">
    <bpmn:startEvent id="Start" name="Start"/>
    <bpmn:userTask id="Task1" name="Approve"/>
    <bpmn:endEvent id="End" name="End"/>
    <bpmn:sequenceFlow id="Flow1" sourceRef="Start" targetRef="Task1"/>
    <bpmn:sequenceFlow id="Flow2" sourceRef="Task1" targetRef="End"/>
  </bpmn:process>
</bpmn:definitions>"""

        result = await mcp.execute_tool(
            tool_name="validate_process",
            params={"bpmn_xml": valid_bpmn},
            tenant_id="test_tenant"
        )

        assert result["success"] is True
        assert "valid" in result

    @pytest.mark.asyncio
    async def test_bpmn_mcp_suggest_executors_tool(self):
        """RED: Test suggest_executors tool execution"""
        mcp = BPMN_MCP(
            membership_base_url="http://localhost:8080",
            use_real_llm=False
        )

        result = await mcp.execute_tool(
            tool_name="suggest_executors",
            params={
                "task_description": "Route the approval request to different departments based on amount"
            },
            tenant_id="test_tenant"
        )

        assert result["success"] is True
        assert "recommended_executors" in result
        assert len(result["recommended_executors"]) > 0

    @pytest.mark.asyncio
    async def test_bpmn_mcp_analyze_semantics_tool(self):
        """RED: Test analyze_process_semantics tool execution"""
        mcp = BPMN_MCP(
            membership_base_url="http://localhost:8080",
            use_real_llm=False
        )

        valid_bpmn = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Definitions_Test">
  <bpmn:process id="Process_Test" isExecutable="true">
    <bpmn:startEvent id="Start" name="Start"/>
    <bpmn:userTask id="Task1" name="Review"/>
    <bpmn:userTask id="Task2" name="Approve"/>
    <bpmn:endEvent id="End" name="End"/>
    <bpmn:exclusiveGateway id="Decision" name="Decision"/>
    <bpmn:sequenceFlow id="Flow1" sourceRef="Start" targetRef="Task1"/>
    <bpmn:sequenceFlow id="Flow2" sourceRef="Task1" targetRef="Decision"/>
    <bpmn:sequenceFlow id="Flow3" sourceRef="Decision" targetRef="Task2"/>
    <bpmn:sequenceFlow id="Flow4" sourceRef="Task2" targetRef="End"/>
  </bpmn:process>
</bpmn:definitions>"""

        result = await mcp.execute_tool(
            tool_name="analyze_process_semantics",
            params={"bpmn_xml": valid_bpmn, "knowledge_base_enabled": True},
            tenant_id="test_tenant"
        )

        assert result["success"] is True
        assert "process_intent" in result
        assert "identified_patterns" in result

    @pytest.mark.asyncio
    async def test_bpmn_mcp_missing_required_params(self):
        """RED: Test error handling for missing parameters"""
        mcp = BPMN_MCP(
            membership_base_url="http://localhost:8080",
            use_real_llm=False
        )

        # Missing process_name
        result = await mcp.execute_tool(
            tool_name="generate_process",
            params={"description": "A brief description here"},
            tenant_id="test_tenant"
        )

        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_bpmn_mcp_invalid_tool_name(self):
        """RED: Test error handling for invalid tool names"""
        mcp = BPMN_MCP(
            membership_base_url="http://localhost:8080",
            use_real_llm=False
        )

        result = await mcp.execute_tool(
            tool_name="nonexistent_tool",
            params={},
            tenant_id="test_tenant"
        )

        assert result["success"] is False
        assert "Unknown tool" in result["error"]

    @pytest.mark.asyncio
    async def test_bpmn_mcp_multiple_mcps_in_registry(self):
        """RED: Test multiple MCPs can coexist in registry"""
        from src.mcp_servers.test_mcp import TestMCPServer

        registry = MCPRegistry()

        # Register both test and BPMN MCPs
        test_mcp = TestMCPServer()
        bpmn_mcp = BPMN_MCP(
            membership_base_url="http://localhost:8080",
            use_real_llm=False
        )

        registry.register_mcp(test_mcp)
        registry.register_mcp(bpmn_mcp)

        # Verify both are registered
        assert registry.has_mcp("test")
        assert registry.has_mcp("bpmn_mcp")
        assert len(registry.get_all_mcps()) == 2
