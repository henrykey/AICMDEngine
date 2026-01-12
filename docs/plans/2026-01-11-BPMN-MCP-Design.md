# BPMN-MCP Detailed Design PRD

**Version**: 1.0
**Date**: 2026-01-11
**Status**: Design Phase - Ready for Implementation
**Phase**: 2.1 (Weeks 1-2)
**Team**: Backend (2), LLM/AI (1)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this PRD task-by-task.

---

## Executive Summary

The BPMN-MCP (Model Context Protocol) server is responsible for intelligently generating BPMN 2.0 process definitions from natural language requirements. It's the cornerstone of the workflow generation platform, handling:

1. **Understanding** natural language process descriptions
2. **Generating** valid BPMN 2.0 XML that Flowable can execute
3. **Managing** 5 executor patterns (static, form-driven, dynamic, queue-based, automation)
4. **Validating** processes against organization structure (Membership org/role/member data)
5. **Analyzing** responses from the knowledge base to make intelligent routing decisions

**Goal**: Enable non-technical users to describe a process in plain language and automatically get a production-ready BPMN definition that works with Membership.

---

## Architecture Overview

### BPMN-MCP Position in System

```
User Natural Language Input
        │
        ▼
┌──────────────────────────────────┐
│  BPMN-MCP Server                 │
├──────────────────────────────────┤
│  - LLM (Claude) for generation   │
│  - BPMN validator                │
│  - Executor pattern handler      │
│  - Knowledge base queries        │
│  - Membership integration        │
└────────┬─────────────┬───────────┘
         │             │
    ┌────▼──────┐  ┌───▼──────────────┐
    │ BPMN 2.0  │  │  Membership KB    │
    │ XML out   │  │  (semantic search)│
    └───────────┘  └──────────────────┘
         │
         ▼
  ProcessEditor UI
  (for human refinement)
```

### Key Responsibilities

| Responsibility | Owner | Details |
|---|---|---|
| **Generation** | LLM-driven | Prompt engineering for BPMN structure |
| **Validation** | Validator | Against BPMN 2.0 spec + Flowable support |
| **Executor Binding** | Executor Handler | Map NL description to executor patterns |
| **Knowledge Integration** | KB Client | Query for policies, routing rules at generation time |
| **Organization Verification** | Membership Client | Verify dept/role/member exist before generating |

---

## Detailed Design

### 1. MCP Tool Interface

#### Tool 1: `generate_process`

**Purpose**: Generate BPMN 2.0 XML from natural language requirement

**Input Schema**:
```json
{
  "tenant_id": "integer (required)",
  "process_name": "string (required) - e.g., 'Drug Approval Process'",
  "description": "string (required) - Natural language description of the process",
  "context": {
    "departments": ["array of dept names"],
    "roles": ["array of role names"],
    "form_fields": ["array of common field names"],
    "process_type": "string enum: approval, workflow, notification, automation"
  }
}
```

**Output Schema**:
```json
{
  "success": "boolean",
  "bpmn_xml": "string - Valid BPMN 2.0 XML",
  "process_id": "string - Unique process ID",
  "process_name": "string",
  "stats": {
    "task_count": "integer",
    "gateway_count": "integer",
    "executor_modes_used": ["array"],
    "confidence_score": "0.0-1.0"
  },
  "validation_warnings": ["array of warnings"],
  "generated_at": "ISO8601 timestamp"
}
```

**Execution Flow**:

1. **Input Validation**
   - Tenant exists in Membership
   - Process name is unique in tenant
   - Description is meaningful (>20 characters)

2. **LLM Prompt Engineering** (See Section 3)
   - Provide organization context from Membership
   - Include department, role, member data
   - Specify BPMN 2.0 requirements

3. **Knowledge Base Query**
   - Search KB for similar processes
   - Extract policy constraints (e.g., "approval > 10k requires CFO")
   - Get process templates from KB if available

4. **BPMN Generation**
   - Call LLM with context to generate BPMN XML structure
   - Include executor pattern tags (See Section 2.2)

5. **Validation** (See Section 4)
   - Parse XML to ensure validity
   - Check against Flowable compatibility rules
   - Verify all referenced org/role/member exist in Membership
   - Generate confidence score

6. **Return Result**
   - BPMN XML ready for ProcessEditor
   - Warnings for manual review

**Error Handling**:
```
- Invalid tenant: Return 404
- Invalid context data: Return 400 with details
- LLM generation fails: Return 500 with fallback template
- Validation fails: Return with warnings + best-effort BPMN
```

---

#### Tool 2: `validate_process`

**Purpose**: Validate BPMN XML and check executor patterns

**Input Schema**:
```json
{
  "tenant_id": "integer (required)",
  "bpmn_xml": "string (required)",
  "strict_mode": "boolean (optional, default: false)"
}
```

**Output Schema**:
```json
{
  "valid": "boolean",
  "errors": ["array of critical errors"],
  "warnings": ["array of warnings"],
  "issues": {
    "executor_patterns": ["array of unresolved patterns"],
    "missing_fields": ["array of required fields"],
    "org_mismatches": ["dept/role that don't exist in Membership"],
    "flowable_incompatibilities": ["potential Flowable issues"]
  },
  "confidence_score": "0.0-1.0",
  "suggestions": ["array of improvement suggestions"]
}
```

**Validation Rules**:

1. **BPMN 2.0 Structure**
   - Valid XML namespace
   - Required elements present (process, startEvent, etc.)
   - All references resolve (targetRef, sourceRef, etc.)

2. **Flowable Compatibility**
   - Task types supported by Flowable
   - Documentation tags follow our executor pattern spec
   - Gateway conditions are evaluable expressions

3. **Executor Pattern Validation**
   - Static: Referenced dept/role exist in Membership
   - Form-driven: Form variables defined in process
   - Dynamic: KB queries are valid
   - Queue: Role exists, can support concurrent claims
   - Automation: MCP tool names are registered

4. **Data Flow**
   - Process variables defined before use
   - Input/output mappings are valid
   - No dangling variables

---

#### Tool 3: `suggest_executors`

**Purpose**: Recommend executor patterns based on process structure

**Input Schema**:
```json
{
  "tenant_id": "integer (required)",
  "task_description": "string (required)",
  "context": {
    "departments": ["array"],
    "roles": ["array"],
    "available_forms": ["array"],
    "automation_capabilities": ["array of available MCP tools"]
  }
}
```

**Output Schema**:
```json
{
  "recommended_executors": [
    {
      "executor_mode": "string enum: static, form_driven, dynamic, queue_claim, automation",
      "confidence": "0.0-1.0",
      "rationale": "string explanation",
      "implementation": "string - code/config snippet",
      "pros": ["array"],
      "cons": ["array"],
      "examples": ["array of task names this works for"]
    }
  ],
  "primary_recommendation": "executor_mode string"
}
```

**Logic**:

For task: "Route approval to finance department if amount > 1000, otherwise to manager"

- ✅ **Dynamic** (confidence: 0.95): "Uses data analysis (amount > 1000) for routing"
- ⚠️ **Form-driven** (confidence: 0.3): "Could ask user to select, but data-driven is better"
- ✅ **Queue-claim** (confidence: 0.7): "Finance team can claim from queue"

---

#### Tool 4: `analyze_process_semantics`

**Purpose**: Understand process intent and suggest improvements

**Input Schema**:
```json
{
  "tenant_id": "integer (required)",
  "bpmn_xml": "string (required)",
  "knowledge_base_enabled": "boolean (optional, default: true)"
}
```

**Output Schema**:
```json
{
  "process_intent": "string - 1-2 sentence description",
  "identified_patterns": ["array of recognized process patterns"],
  "policy_constraints": ["array of policies from KB"],
  "optimization_opportunities": [
    {
      "type": "string enum: parallelization, simplification, automation, dynamic_routing",
      "description": "string",
      "impact": "string - potential benefit",
      "effort": "string enum: low, medium, high"
    }
  ],
  "kb_suggestions": [
    {
      "policy": "string - relevant policy from KB",
      "applies_to_task": "string - task name",
      "suggested_change": "string"
    }
  ]
}
```

---

### 2. Executor Pattern Implementation

#### 2.1 Executor Pattern Specification

Each task in BPMN can be assigned an executor pattern via documentation tags. The tag format:

```xml
<bpmn:task id="Task_Approve" name="Approve Application">
  <bpmn:documentation>
{
  "executor_pattern": "static",
  "executor_config": {
    "department": "finance",
    "role": "approver"
  }
}
  </bpmn:documentation>
</bpmn:task>
```

#### 2.2 Five Executor Patterns

##### Pattern 1: Static (部门/角色)

**Use Case**: Role or department clearly defined in process requirement

**BPMN Configuration**:
```json
{
  "executor_pattern": "static",
  "executor_config": {
    "type": "role|department|member",
    "value": "string - role name, dept name, or member ID"
  }
}
```

**Flowable Implementation**:
```java
// Flowable receives process variable: executor_dept_name = "finance"
// Standard Flowable task assignment:
<bpmn:userTask id="ApprovalTask" name="Approve">
  <bpmn:potentialOwner>
    <bpmn:resourceAssignmentExpression>
      <bpmn:formalExpression>
        dept:${executor_dept_name},role:${executor_role_name}
      </bpmn:formalExpression>
    </bpmn:resourceAssignmentExpression>
  </bpmn:potentialOwner>
</bpmn:userTask>
```

**Generation Example**:
```
NL: "The finance team should approve all applications"
→ executor_pattern: static
→ executor_config: {type: "department", value: "finance"}
→ BPMN tag: <documentation>{"executor_pattern": "static", ...}</documentation>
```

---

##### Pattern 2: Form-Driven (用户选择)

**Use Case**: Executor determined dynamically during process start via user selection

**Process Start Form**:
```json
{
  "form_fields": [
    {
      "name": "approver_selection",
      "label": "Select Approver",
      "type": "select",
      "source": "membership:role:approver",
      "description": "Choose who will approve this request"
    }
  ]
}
```

**BPMN Configuration**:
```json
{
  "executor_pattern": "form_driven",
  "executor_config": {
    "form_field": "approver_selection",
    "form_source": "membership:role:approver"
  }
}
```

**Flowable Implementation**:
```java
// Process start form captures: approver_id = "user_123"
// Task uses process variable:
<bpmn:userTask id="ApprovalTask">
  <bpmn:potentialOwner>
    <bpmn:resourceAssignmentExpression>
      <bpmn:formalExpression>${approver_id}</bpmn:formalExpression>
    </bpmn:resourceAssignmentExpression>
  </bpmn:potentialOwner>
</bpmn:userTask>
```

**Generation Example**:
```
NL: "At the start, ask the user to select who should review the document"
→ executor_pattern: form_driven
→ form_field: "reviewer_selection"
→ Generate start form with member selector
→ BPMN task uses ${reviewer_selection} variable
```

---

##### Pattern 3: Dynamic Multi-Route (数据分析驱动)

**Use Case**: Routing decision based on analyzing data at runtime via MCP/KB

**BPMN Configuration**:
```json
{
  "executor_pattern": "dynamic",
  "executor_config": {
    "decision_logic": "MCP query",
    "kb_query": "Find approval dept based on: amount=${amount}, category=${category}",
    "mcp_tool": "route_to_department",
    "fallback": "default_approver"
  }
}
```

**Implementation Pattern**:
```
Process receives: amount=50000, category="pharmaceutical"
  │
  ├─ MCP queries KB: "What's approval policy for pharma > 50k?"
  │  → Returns: "Route to director + CFO committee"
  │
  └─ Dynamic gateway creates tasks for both approvers

<bpmn:serviceTask id="RouteDecision" name="Determine Approvers">
  <bpmn:documentation>
  {
    "executor_pattern": "dynamic",
    "mcp_service_call": "route_to_department",
    "kb_query": "approval_policy",
    "input_variables": ["amount", "category"],
    "output_variable": "approver_dept"
  }
  </bpmn:documentation>
</bpmn:serviceTask>
```

**Generation Example**:
```
NL: "Route approval to different departments based on the application amount:
     < 5k → manager
     5k-50k → director
     > 50k → CFO committee"
→ executor_pattern: dynamic
→ Create exclusive gateway with conditions:
   - condition: ${amount < 5000} → manager task
   - condition: ${amount >= 5000 && amount <= 50000} → director task
   - condition: ${amount > 50000} → cfo_committee task
→ Generate KB queries to validate policies
```

---

##### Pattern 4: Role-Queue Claim (竞争认领)

**Use Case**: Task assigned to entire role/department; first person to claim gets it

**BPMN Configuration**:
```json
{
  "executor_pattern": "queue_claim",
  "executor_config": {
    "claim_group": "department|role",
    "group_name": "sales",
    "priority": "integer optional",
    "timeout": "duration optional"
  }
}
```

**Flowable Implementation**:
```java
<bpmn:userTask id="ClaimableTask" name="Process Application">
  <bpmn:potentialOwner>
    <bpmn:resourceAssignmentExpression>
      <bpmn:formalExpression>role:${role_name}</bpmn:formalExpression>
    </bpmn:resourceAssignmentExpression>
  </bpmn:potentialOwner>
  <bpmn:documentation>
  {
    "executor_pattern": "queue_claim",
    "claim_logic": "first_available"
  }
  </bpmn:documentation>
</bpmn:userTask>
```

**Generation Example**:
```
NL: "The sales team will process the order. Whoever is available first will take it."
→ executor_pattern: queue_claim
→ executor_config: {claim_group: "department", group_name: "sales"}
→ Flowable creates task for all sales members
→ First to claim wins
```

---

##### Pattern 5: MCP Automation (虚拟成员/AI驱动)

**Use Case**: Task automated via MCP tool (no human involved) or by virtual member

**BPMN Configuration**:
```json
{
  "executor_pattern": "automation",
  "executor_config": {
    "automation_type": "mcp_tool|virtual_member",
    "mcp_tool_name": "financial_audit",
    "automation_logic": "Check compliance against KB policies",
    "virtual_member_name": "AI Financial Auditor",
    "input_variables": ["document", "budget_code"],
    "output_variable": "audit_result"
  }
}
```

**BPMN Implementation**:
```xml
<bpmn:serviceTask id="FinancialAudit" name="Run Financial Audit (AI)">
  <bpmn:documentation>
  {
    "executor_pattern": "automation",
    "mcp_tool": "financial_audit",
    "kb_query": "Get compliance rules for budget code ${budget_code}",
    "approval_logic": "If result.passed == true, auto-approve"
  }
  </bpmn:documentation>
</bpmn:serviceTask>
```

**Generation Example**:
```
NL: "The system should automatically check financial compliance. Only if it passes
     should the approval move to the next stage."
→ executor_pattern: automation
→ mcp_tool_name: "financial_compliance_check"
→ Flowable calls MCP → MCP queries KB for rules → Returns compliance status
→ Exclusive gateway routes based on compliance_passed
```

---

### 3. LLM Prompt Engineering

#### 3.1 System Prompt for BPMN Generation

```
You are a BPMN 2.0 process expert that translates natural language process descriptions
into valid BPMN 2.0 XML.

## CRITICAL REQUIREMENTS

1. **BPMN Structure**:
   - Must be valid BPMN 2.0 XML
   - All tasks, gateways, events must be properly connected
   - No orphaned elements or dangling connections

2. **Executor Patterns** (5 types available):
   - Static: Fixed department/role
   - Form-driven: User selects executor at process start
   - Dynamic: Route based on data analysis
   - Queue-claim: First available team member claims
   - Automation: MCP tool execution

   Include executor pattern in bpmn:documentation tag as JSON:
   {
     "executor_pattern": "static|form_driven|dynamic|queue_claim|automation",
     "executor_config": { ... }
   }

3. **Membership Integration**:
   - Reference actual departments, roles, members from organization context
   - Validate that referenced entities exist
   - Use consistent naming with Membership (lowercase, underscores)

4. **Process Variables**:
   - Define all variables used in expressions
   - Use ${variable_name} syntax consistently
   - Include data types in documentation

5. **Error Handling**:
   - Include error boundaries where appropriate
   - Define retry strategies for service tasks
   - Add fallback flows for failures

## OUTPUT FORMAT

Return ONLY valid BPMN 2.0 XML, wrapped in:
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" ...>
...
</bpmn:definitions>

Do NOT include markdown backticks or explanations.
```

#### 3.2 Input Context Template

```json
{
  "user_requirement": "string - Natural language process description",

  "organization_context": {
    "departments": [
      {"id": "dept_123", "name": "finance", "members_count": 5},
      {"id": "dept_456", "name": "medical", "members_count": 12}
    ],
    "roles": [
      {"id": "role_001", "name": "approver"},
      {"id": "role_002", "name": "reviewer"},
      {"id": "role_003", "name": "auditor"}
    ],
    "members": [
      {"id": "mem_001", "name": "Alice", "roles": ["approver"], "departments": ["finance"]},
      {"id": "mem_002", "name": "Bob", "roles": ["reviewer"], "departments": ["medical"]}
    ]
  },

  "knowledge_base_context": {
    "relevant_policies": [
      "Policy 001: Amounts > $10,000 require CFO approval",
      "Policy 002: Medical decisions require at least 2 medical experts"
    ],
    "process_templates": [
      "Standard Approval Flow: Start → Assign → Review → Approve → End"
    ]
  },

  "constraints": {
    "max_parallel_tasks": 3,
    "max_approval_levels": 5,
    "required_error_handling": true
  }
}
```

#### 3.3 Few-Shot Examples for Prompt

**Example 1: Static Pattern**
```
Input:
  requirement: "Purchase orders above $5000 need approval from the Finance Manager"
  available_roles: ["finance_manager", "approver"]
  available_depts: ["finance", "procurement"]

Output BPMN snippet:
  <bpmn:userTask id="FinanceApproval" name="Finance Manager Approval">
    <bpmn:documentation>
    {
      "executor_pattern": "static",
      "executor_config": {
        "type": "role",
        "value": "finance_manager"
      }
    }
    </bpmn:documentation>
  </bpmn:userTask>
```

**Example 2: Form-Driven Pattern**
```
Input:
  requirement: "At the start of the process, ask who will be the primary reviewer"
  form_fields_available: ["reviewer_selection", "category_selection"]

Output:
  - Include in process start form: <bpmn:startEvent formKey="process_startup">
  - Task references form field: ${reviewer_selection}
  - Pattern documentation: "form_driven" with "form_field": "reviewer_selection"
```

**Example 3: Dynamic Pattern**
```
Input:
  requirement: "Route the approval request to different teams based on the application category:
               - Medical devices → Medical Team
               - Pharmaceuticals → Pharma Team
               - Devices > $100k → CFO also needed"

Output BPMN snippet:
  <bpmn:exclusiveGateway id="RouteByCategory">
    <bpmn:outgoing>Flow_MedicalDevices</bpmn:outgoing>
    <bpmn:outgoing>Flow_Pharma</bpmn:outgoing>
    <bpmn:outgoing>Flow_HighValue</bpmn:outgoing>
  </bpmn:exclusiveGateway>

  <bpmn:sequenceFlow id="Flow_MedicalDevices" sourceRef="RouteByCategory" targetRef="MedicalTeamApproval">
    <bpmn:conditionExpression>${category == 'medical_device'}</bpmn:conditionExpression>
  </bpmn:sequenceFlow>
```

---

### 4. Validation Engine

#### 4.1 Validation Pipeline

```
Input BPMN
  │
  ├─ XML Parsing
  │  └─ Check: Valid XML syntax
  │
  ├─ BPMN Structure
  │  └─ Check: Required elements, connections, references
  │
  ├─ Flowable Compatibility
  │  └─ Check: Supported task types, gateway types, expressions
  │
  ├─ Executor Pattern Validation
  │  ├─ Static: Verify dept/role/member in Membership
  │  ├─ Form-driven: Verify form fields defined
  │  ├─ Dynamic: Verify MCP tools and KB queries
  │  ├─ Queue: Verify role supports concurrent claims
  │  └─ Automation: Verify MCP tools registered
  │
  ├─ Data Flow
  │  └─ Check: Variables defined before use
  │
  └─ Final Decision
     └─ Return: valid (true/false) + warnings + suggestions
```

#### 4.2 Validation Rules (Detailed)

**Rule 1: BPMN Structure**
- File must be valid XML with BPMN namespace
- Must have exactly 1 process
- Process must have startEvent and endEvent
- All sequence flows must have source and target
- No circular references (except loops in process logic)

**Rule 2: Flowable Task Types**
- Supported: userTask, serviceTask, scriptTask, exclusiveGateway, parallelGateway
- Not supported: sendTask, receiveTask, complexGateway
- Recommendation: convert to userTask or serviceTask

**Rule 3: Executor Pattern Validation**
```
For each userTask:
  1. Extract executor_pattern from documentation
  2. Based on pattern, validate:
     - static: referenced dept/role exist in Membership
     - form_driven: referenced form field exists in process
     - dynamic: MCP tool registered, KB query syntax valid
     - queue_claim: referenced role exists, supports multiple assignments
     - automation: MCP tool registered, virtual member name valid
```

**Rule 4: Expression Validation**
- All ${...} expressions must reference defined process variables
- Expressions must be valid Java/SpEL syntax
- No undefined variable references

**Rule 5: Process Variables**
- All variables used in expressions must be defined
- Variables defined in documentation before first use
- Variable types match their usage (no comparing string to number)

---

### 5. Knowledge Base Integration

#### 5.1 KB Query Strategy

When generating process:

1. **Policy Discovery**
   ```
   Query: "What policies apply to {process_type} for {departments}?"
   Result: ["Approval > $10k requires CFO", "Medical requires 2 experts", ...]
   Action: Incorporate into process as constraints/gateways
   ```

2. **Precedent Processes**
   ```
   Query: "What similar processes exist in knowledge base?"
   Result: [{"name": "Pharma Approval v2", "success_rate": 0.95}, ...]
   Action: Suggest to user for adaptation
   ```

3. **Routing Rules**
   ```
   Query: "What are the routing rules for department={dept}, category={cat}?"
   Result: ["Route to director if amount > threshold", ...]
   Action: Generate dynamic gateways based on rules
   ```

#### 5.2 Semantic Search for Smart Routing

For dynamic routing patterns, query KB:

```
MCP Service Task (in BPMN):
  Query: "Find optimal approver for:
          - item_type: pharmaceutical,
          - amount: 50000,
          - region: EMEA"

  KB Search (semantic + full-text):
    - Find documents about pharma approval policies
    - Find documents about EMEA regional requirements
    - Extract approval structure from matched docs

  Result: "Route to: Pharma Director + Regional CFO"
```

---

### 6. Example: Complete Drug Approval Process

**Input Natural Language**:
```
"Pharmaceutical drug approval process:
1. Manufacturer submits application with supporting docs
2. Initial completeness check - reject if missing docs
3. If complete, send to Medical Team for review (2 experts required)
4. Medical Team provides assessment
5. If assessment is positive:
   - Amount < $100k → Finance Manager approves
   - Amount >= $100k → CFO and Board approval
6. If approved at all levels, send approval letter
7. If rejected at any stage, send rejection letter"
```

**Generated BPMN** (conceptual structure):
```
START
  ├─ [User Task] Submit Application
  │  └─ [Process Form] application_form
  │
  ├─ [Service Task] Check Completeness (auto, script)
  │  └─ ├─ Output: completeness_status
  │  └─ ├─ if NOT complete → Rejection Path
  │
  ├─ [Exclusive Gateway] Route by Completeness
  │  ├─ COMPLETE → Medical Review
  │  └─ INCOMPLETE → Rejection
  │
  ├─ [Parallel Gateway] Medical Review (2 experts, pattern: queue_claim)
  │  ├─ [User Task] Expert 1 Review (executor: queue_claim, dept: medical)
  │  ├─ [User Task] Expert 2 Review (executor: queue_claim, dept: medical)
  │  └─ [Synchronization] Wait for both
  │
  ├─ [Exclusive Gateway] Medical Assessment Result
  │  ├─ POSITIVE → Finance Approval
  │  └─ NEGATIVE → Rejection
  │
  ├─ [Exclusive Gateway] Route by Amount (pattern: dynamic, KB query)
  │  ├─ < $100k → Manager Approval
  │  ├─ >= $100k → CFO & Board
  │
  ├─ [User Task] Finance Manager Approval (executor: static, role: manager)
  ├─ [Parallel Gateway] Executive Approval
  │  ├─ [User Task] CFO Approval (executor: static, dept: finance)
  │  ├─ [User Task] Board Approval (executor: static, dept: board)
  │
  ├─ [Exclusive Gateway] All Approvals
  │  ├─ APPROVED → Send Approval Letter
  │  └─ REJECTED → Send Rejection Letter
  │
  ├─ [Service Task] Send Letter (automation pattern)
  └─ END

Process Variables:
  - application_id, application_form, completeness_status, amount
  - medical_assessment, medical_score
  - manager_approval, cfo_approval, board_approval
  - final_decision, letter_content
```

**Executor Patterns Used**:
- ✅ Static: Manager, CFO, Board (fixed roles)
- ✅ Queue-claim: Medical experts (competing for tasks)
- ✅ Dynamic: Routing based on amount
- ✅ Automation: Completeness check, letter generation

---

## Implementation Checklist

### Week 1: Design & Setup
- [ ] Finalize LLM prompt templates
- [ ] Set up MCP tool schemas and interfaces
- [ ] Design Membership client integration
- [ ] Set up KB query client
- [ ] Create test fixtures (sample org data)

### Week 2: Core Implementation
- [ ] Implement `generate_process` tool
- [ ] Implement LLM integration with prompt engineering
- [ ] Implement `validate_process` tool
- [ ] Implement `suggest_executors` tool
- [ ] Implement `analyze_process_semantics` tool
- [ ] Write unit tests for all tools
- [ ] Integration tests with Membership client

### Week 3: Refinement
- [ ] End-to-end testing with real examples
- [ ] Error handling and fallback strategies
- [ ] Performance optimization
- [ ] Documentation

### Testing Strategy
- **Unit Tests**: Each tool independently
- **Integration Tests**: With Membership client
- **E2E Tests**: Full workflow generation → validation
- **Error Cases**: Missing data, invalid patterns, KB unavailable
- **Performance**: Generation time, validation time

---

## Success Criteria

- [x] Architecture aligned with Membership integration
- [x] 5 executor patterns fully documented
- [ ] BPMN-MCP generates valid BPMN for 80%+ of inputs
- [ ] Validation catches 95%+ of issues before Flowable
- [ ] Generation time < 5 seconds (including LLM call)
- [ ] All test cases passing
- [ ] Confidence scores calibrated (0.5 = 50% chance of success)

---

## Appendix: BPMN 2.0 Quickstart

### Basic Elements

```xml
<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                   id="Definitions_01">
  <bpmn:process id="Process_1" isExecutable="true">

    <!-- Start Event -->
    <bpmn:startEvent id="StartEvent_1" name="Start">
      <bpmn:outgoing>Flow_1</bpmn:outgoing>
    </bpmn:startEvent>

    <!-- User Task -->
    <bpmn:userTask id="Task_1" name="Approve">
      <bpmn:incoming>Flow_1</bpmn:incoming>
      <bpmn:outgoing>Flow_2</bpmn:outgoing>
      <bpmn:documentation>{"executor_pattern": "static", ...}</bpmn:documentation>
    </bpmn:userTask>

    <!-- Exclusive Gateway (decision) -->
    <bpmn:exclusiveGateway id="Gateway_1">
      <bpmn:incoming>Flow_2</bpmn:incoming>
      <bpmn:outgoing>Flow_Approved</bpmn:outgoing>
      <bpmn:outgoing>Flow_Rejected</bpmn:outgoing>
    </bpmn:exclusiveGateway>

    <!-- Sequence Flows (connections) -->
    <bpmn:sequenceFlow id="Flow_1" sourceRef="StartEvent_1" targetRef="Task_1"/>
    <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="Gateway_1"/>
    <bpmn:sequenceFlow id="Flow_Approved" sourceRef="Gateway_1" targetRef="EndEvent_Approved">
      <bpmn:conditionExpression>${approved == true}</bpmn:conditionExpression>
    </bpmn:sequenceFlow>

    <!-- End Event -->
    <bpmn:endEvent id="EndEvent_Approved" name="End - Approved">
      <bpmn:incoming>Flow_Approved</bpmn:incoming>
    </bpmn:endEvent>

  </bpmn:process>
</bpmn:definitions>
```

### Variable Declaration (in process documentation)

```json
{
  "process_variables": [
    {
      "name": "approved",
      "type": "boolean",
      "default": false,
      "description": "Whether application was approved"
    },
    {
      "name": "approver_id",
      "type": "string",
      "required": true,
      "description": "ID of person approving"
    }
  ]
}
```

---

## Critical Dependencies & Blocker Resolution

### Blocker 1: Membership Client Integration ✅ RESOLVED

**Original Concern**: How do we authenticate with Membership?

**Resolution**:
- AICMDEngine already delegates authentication to Membership
- All requests include `X-Tenant-ID` header (from JWT token)
- Use existing REST APIs from Membership OpenAPI v2.2:
  - `GET /v2/members` - Fetch members by role/dept
  - `GET /v2/roles` - List available roles
  - `GET /v2/orgs` - Get organization structure
  - `POST /v2/authz/check` - Verify permissions before generating

**Implementation**:
```python
# Use Membership REST API directly via requests library
class MembershipClient:
  def __init__(self, base_url, tenant_id):
    self.base_url = base_url
    self.tenant_id = tenant_id
    # token comes from current request context (Flask/FastAPI)

  async def get_org_context(self):
    # Fetch departments, roles, members
    # Returns: {"departments": [...], "roles": [...], "members": [...]}

  async def validate_executor(self, executor_pattern, executor_config):
    # Verify dept/role/member exist before generating BPMN
```

**Dependencies**: None (Membership APIs already exist)

---

### Blocker 2: Knowledge Base Query APIs ⏳ PROPOSED (Membership v2.4已设计基础)

**Original Concern**: KB queries for policy discovery and dynamic routing

**Current Status**:
- ✅ **Membership v2.4文档引擎已设计** (见membership_v2.4_enterprise_platform_expansion_plan.md)
  - MongoDB存储: documents + document_permissions collections
  - Elasticsearch全文索引: documents_text index (IK中文分词)
  - Elasticsearch语义向量: doc_embeddings (768维dense_vector, cosine相似度)
  - HybridSearchService混合搜索: RRF融合算法 (keyword_weight: 0.3, semantic_weight: 0.7)
  - 权限管理: document_permissions collection (role/user/org_unit级别)
- ❌ **REST API层未实现** - membership-docs服务设计完成，但查询endpoint需补充

**Solution**: 提议为Membership v2.4补充4个REST Query API：
1. **Keyword Search** - 全文搜索 (Elasticsearch documents_text index)
2. **Semantic Search** - 语义相似性搜索 (Elasticsearch doc_embeddings 768维向量)
3. **Hybrid Search** - 混合搜索 (HybridSearchService RRF融合)
4. **RAG Query** - 问答+检索 (LLM + 向量相似度)

**Timeline**:
- **Minimal MVP (Phase 2.1)**: 仅需keyword search
  - BPMN生成可用简单文档查询完成
  - Membership已有Elasticsearch索引结构，直接调用即可
  - **Timeline**: 1-2周补充REST API endpoint
- **Full KB support (Phase 2.2)**: Semantic search + routing extraction
  - 更智能的动态路由决策
  - 充分利用768维向量索引
  - **Timeline**: 2-3周完整实现

**Fallback Strategy** (如KB API延迟):
```python
# Phase 2.1可以不依赖KB API，使用hardcoded策略
# 示例:
APPROVAL_POLICIES = {
  ("pharmaceutical", "amount > 50000"): ["role:pharma_director", "role:cfo"],
  ("device", "amount > 100000"): ["role:device_review", "role:board"],
  # ... 更多规则
}

# Phase 2.2再迁移到动态KB查询
```

**Proposed KB API Spec**: See `/docs/plans/2026-01-11-KB-Query-API-Proposal.md`
- 基于Membership v2.4文档引擎设计
- API设计建议 + 实现指南 (与expansion_plan v2.4对齐)
- 已准备好发给Membership团队审阅确认

---

### Concern 3: LLM Prompt Stability ⚠️ HANDLED

**Original Concern**: LLM output consistency for BPMN XML generation

**Mitigation Strategy**:

1. **Structured Output with Few-Shot Examples**
   - Provide 3-5 worked examples in system prompt (Section 3.3)
   - Use consistent formatting and terminology
   - Target: 80%+ first-pass valid BPMN

2. **Validation Catches Errors**
   - Every generated BPMN goes through validation pipeline (Section 4)
   - Validation returns detailed error messages
   - Confidence score indicates likelihood of success (0.5 = 50% chance)

3. **Graceful Fallback**
   - If LLM generation fails: Return basic template
   - Template: Start → Review Task → Approval Task → End (basic flow)
   - User manually edits template in ProcessEditor

4. **Retry with Refinement**
   - If first generation has issues, send back error details to LLM
   - LLM regenerates with constraints learned from failures
   - Implement as Option in UI: "Regenerate with fixes"

5. **Rate Limiting and Caching**
   - Cache generated processes by [tenant_id, process_name, description]
   - If exact match found, return cached BPMN instead of re-calling LLM
   - Rate limit: Max 10 generations per tenant per minute

**Expected Output Quality**:
- **Valid BPMN**: 85-90% first pass (higher with few-shot examples)
- **Flowable compatible**: 80% (some edge cases need manual fix)
- **Executor patterns correct**: 75% (user reviews in ProcessEditor)
- **Process variables defined**: 80% (validation catches undefined vars)

---

### Concern 4: Week 1 Task Granularity ⏳ WILL REFINE

**Original Concern**: Week 1 tasks are still design-level, not concrete TDD

**Current Plan** (needs refinement):
```
Week 1: Design & Setup
- [ ] Finalize LLM prompt templates
- [ ] Set up MCP tool schemas and interfaces
- [ ] Design Membership client integration
- [ ] Set up KB query client
- [ ] Create test fixtures (sample org data)
```

**Problem**: These are still DESIGN tasks, not bite-sized TDD steps

**Solution**: Will break down further during **Week 1 Day 1-2** into concrete tasks like:
```
Task 1.1: Write failing test for MembershipClient.get_org_context()
  - Input: tenant_id="1"
  - Expected: {"departments": [...], "roles": [...]}

Task 1.2: Implement MembershipClient with REST calls
  - Use requests library
  - Cache results with 5-minute TTL
  - Test with mock Membership API

Task 1.3: Write failing test for BPMN validator
  - Input: invalid_bpmn_xml
  - Expected: ValidationError with specific messages

Task 1.4: Implement BPMN validation pipeline
  - XML parsing
  - Structure validation
  - Executor pattern validation

... and so on
```

**This refinement** happens during Week 1 kickoff, following TDD approach per superpowers:test-driven-development skill.

---

## Summary: Ready for Implementation

| Item | Status | Notes |
|------|--------|-------|
| Blocker 1: Membership auth | ✅ RESOLVED | Use existing REST APIs, no new work needed |
| Blocker 2: KB APIs | ⏳ PROPOSED | Fallback: hardcode policies for Phase 2.1; KB APIs in Phase 2.2 |
| Concern 3: LLM stability | ⚠️ HANDLED | Validation catches errors; confidence score guides user |
| Concern 4: Task granularity | ⏳ WILL REFINE | TDD tasks will be created during Week 1 kickoff |

**Recommendation**: ✅ **Proceed with implementation**
- No critical blockers
- Membership integration straightforward (use existing APIs)
- KB APIs can be deferred to Phase 2.2 with fallback strategy
- Week 1 tasks will be refined to TDD standards

---

**PRD Status**: ✅ Complete and ready for implementation
**Next Step**: Begin BPMN-MCP implementation with TDD approach
**Coordination**: Send KB API proposal to Membership team for review
