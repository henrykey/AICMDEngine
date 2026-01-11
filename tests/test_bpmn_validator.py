"""
Tests for BPMN XML Validator.

Following TDD methodology to validate BPMN 2.0 XML structures.
"""

import pytest
from typing import Dict, Any
import xml.etree.ElementTree as ET


class TestBPMNValidatorBasicStructure:
    """Test BPMN validator for basic structure validation"""

    @pytest.mark.asyncio
    async def test_validate_valid_minimal_bpmn(self):
        """
        RED: Test that validator accepts minimal valid BPMN

        Given: Valid minimal BPMN with startEvent, endEvent, and connection
        When: call validate_bpmn()
        Then: return {"valid": True} with no errors
        """
        from src.mcp_servers.bpmn_mcp import BPMNValidator

        valid_bpmn = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                   id="Definitions_1" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_1" isExecutable="true">
    <bpmn:startEvent id="StartEvent_1" name="Start">
      <bpmn:outgoing>Flow_1</bpmn:outgoing>
    </bpmn:startEvent>
    <bpmn:endEvent id="EndEvent_1" name="End">
      <bpmn:incoming>Flow_1</bpmn:incoming>
    </bpmn:endEvent>
    <bpmn:sequenceFlow id="Flow_1" sourceRef="StartEvent_1" targetRef="EndEvent_1"/>
  </bpmn:process>
</bpmn:definitions>"""

        validator = BPMNValidator()
        result = await validator.validate_bpmn("tenant_123", valid_bpmn)

        assert result["valid"] is True
        assert len(result.get("errors", [])) == 0

    @pytest.mark.asyncio
    async def test_validate_invalid_xml_syntax(self):
        """
        RED: Test that validator rejects invalid XML

        Given: Malformed XML (missing closing tag)
        When: call validate_bpmn()
        Then: return {"valid": False, "errors": [...]} with XML error
        """
        from src.mcp_servers.bpmn_mcp import BPMNValidator

        invalid_xml = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
  <bpmn:process id="Process_1">
    <bpmn:startEvent id="StartEvent_1"
  </bpmn:process>
</bpmn:definitions>"""

        validator = BPMNValidator()
        result = await validator.validate_bpmn("tenant_123", invalid_xml)

        assert result["valid"] is False
        assert len(result["errors"]) > 0
        assert any("XML" in e or "parse" in e.lower() for e in result["errors"])

    @pytest.mark.asyncio
    async def test_validate_missing_start_event(self):
        """
        RED: Test that validator catches missing startEvent

        Given: BPMN without startEvent
        When: call validate_bpmn()
        Then: return {"valid": False, "errors": [...]} with "startEvent" error
        """
        from src.mcp_servers.bpmn_mcp import BPMNValidator

        no_start_event = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                   id="Definitions_1" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_1" isExecutable="true">
    <bpmn:endEvent id="EndEvent_1" name="End">
      <bpmn:incoming>Flow_1</bpmn:incoming>
    </bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>"""

        validator = BPMNValidator()
        result = await validator.validate_bpmn("tenant_123", no_start_event)

        assert result["valid"] is False
        assert any("startevent" in e.lower() for e in result["errors"])

    @pytest.mark.asyncio
    async def test_validate_missing_end_event(self):
        """
        RED: Test that validator catches missing endEvent

        Given: BPMN without endEvent
        When: call validate_bpmn()
        Then: return {"valid": False, "errors": [...]} with "endEvent" error
        """
        from src.mcp_servers.bpmn_mcp import BPMNValidator

        no_end_event = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                   id="Definitions_1" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_1" isExecutable="true">
    <bpmn:startEvent id="StartEvent_1" name="Start">
      <bpmn:outgoing>Flow_1</bpmn:outgoing>
    </bpmn:startEvent>
  </bpmn:process>
</bpmn:definitions>"""

        validator = BPMNValidator()
        result = await validator.validate_bpmn("tenant_123", no_end_event)

        assert result["valid"] is False
        assert any("endevent" in e.lower() for e in result["errors"])

    @pytest.mark.asyncio
    async def test_validate_broken_sequence_flow(self):
        """
        RED: Test that validator catches broken sequenceFlow connections

        Given: BPMN with sequenceFlow referencing non-existent task
        When: call validate_bpmn()
        Then: return {"valid": False, "errors": [...]} with "targetRef" error
        """
        from src.mcp_servers.bpmn_mcp import BPMNValidator

        broken_flow = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                   id="Definitions_1" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_1" isExecutable="true">
    <bpmn:startEvent id="StartEvent_1" name="Start">
      <bpmn:outgoing>Flow_1</bpmn:outgoing>
    </bpmn:startEvent>
    <bpmn:endEvent id="EndEvent_1" name="End">
      <bpmn:incoming>Flow_1</bpmn:incoming>
    </bpmn:endEvent>
    <bpmn:sequenceFlow id="Flow_1" sourceRef="StartEvent_1" targetRef="NonExistentTask_1"/>
  </bpmn:process>
</bpmn:definitions>"""

        validator = BPMNValidator()
        result = await validator.validate_bpmn("tenant_123", broken_flow)

        assert result["valid"] is False
        assert any("targetRef" in e or "reference" in e.lower() for e in result["errors"])


class TestBPMNValidatorWithExecutorPatterns:
    """Test BPMN validator for executor pattern validation"""

    @pytest.mark.asyncio
    async def test_validate_static_executor_pattern_valid(self):
        """
        RED: Test that validator accepts valid static executor pattern

        Given: BPMN with valid static executor pattern documentation
        When: call validate_bpmn()
        Then: return {"valid": True}
        """
        from src.mcp_servers.bpmn_mcp import BPMNValidator

        bpmn_with_static = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                   id="Definitions_1" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_1" isExecutable="true">
    <bpmn:startEvent id="StartEvent_1" name="Start">
      <bpmn:outgoing>Flow_1</bpmn:outgoing>
    </bpmn:startEvent>
    <bpmn:userTask id="Task_1" name="Approve">
      <bpmn:incoming>Flow_1</bpmn:incoming>
      <bpmn:outgoing>Flow_2</bpmn:outgoing>
      <bpmn:documentation>{
        "executor_pattern": "static",
        "executor_config": {
          "type": "role",
          "value": "approver"
        }
      }</bpmn:documentation>
    </bpmn:userTask>
    <bpmn:endEvent id="EndEvent_1" name="End">
      <bpmn:incoming>Flow_2</bpmn:incoming>
    </bpmn:endEvent>
    <bpmn:sequenceFlow id="Flow_1" sourceRef="StartEvent_1" targetRef="Task_1"/>
    <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="EndEvent_1"/>
  </bpmn:process>
</bpmn:definitions>"""

        validator = BPMNValidator()
        result = await validator.validate_bpmn("tenant_123", bpmn_with_static)

        assert result["valid"] is True


class TestBPMNValidatorConfidenceScore:
    """Test confidence score calculation"""

    @pytest.mark.asyncio
    async def test_confidence_score_perfect_bpmn(self):
        """
        RED: Test that confidence score is high for perfect BPMN

        Given: Valid, well-formed BPMN with proper executor patterns
        When: call validate_bpmn()
        Then: return confidence_score >= 0.9
        """
        from src.mcp_servers.bpmn_mcp import BPMNValidator

        valid_bpmn = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                   id="Definitions_1" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_1" isExecutable="true">
    <bpmn:startEvent id="StartEvent_1" name="Start">
      <bpmn:outgoing>Flow_1</bpmn:outgoing>
    </bpmn:startEvent>
    <bpmn:endEvent id="EndEvent_1" name="End">
      <bpmn:incoming>Flow_1</bpmn:incoming>
    </bpmn:endEvent>
    <bpmn:sequenceFlow id="Flow_1" sourceRef="StartEvent_1" targetRef="EndEvent_1"/>
  </bpmn:process>
</bpmn:definitions>"""

        validator = BPMNValidator()
        result = await validator.validate_bpmn("tenant_123", valid_bpmn)

        assert result["valid"] is True
        assert result["confidence_score"] >= 0.9
        assert isinstance(result["confidence_score"], float)
        assert 0.0 <= result["confidence_score"] <= 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
