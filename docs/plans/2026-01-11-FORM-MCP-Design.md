# FORM-MCP Detailed Design PRD

**Version**: 1.0
**Date**: 2026-01-11
**Status**: Design Phase - Ready for Implementation
**Phase**: 2.1 (Weeks 1-2)
**Team**: Backend (2), Form Designer (1), LLM/AI (1)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this PRD task-by-task.

---

## Executive Summary

The FORM-MCP (Model Context Protocol) server generates dynamic forms that are tightly integrated with BPMN processes and Membership's organizational structure. It's responsible for:

1. **Understanding** form requirements from natural language descriptions
2. **Generating** form definitions with field-level permissions
3. **Binding** forms to BPMN processes (process startup forms + task-specific forms)
4. **Validating** form fields against Membership organization (roles, departments, members)
5. **Enforcing** Membership RBAC permissions at the field level (field-level RLS)

**Goal**: Enable automatic generation of forms that align with organizational structure and process requirements, ensuring data is collected correctly and permissions are enforced from design-time to execution-time.

---

## Architecture Overview

### FORM-MCP Position in System

```
User Natural Language Input
        │
        ▼
┌──────────────────────────────────┐
│  FORM-MCP Server                 │
├──────────────────────────────────┤
│  - LLM for form generation       │
│  - Form validator               │
│  - Permission mapper            │
│  - BPMN binding handler         │
│  - Membership integration       │
└────────────┬─────────────────────┘
             │
    ┌────────┴────────────────┐
    │                         │
┌───▼────────────┐     ┌─────▼──────────────┐
│ Form Definition│     │ Membership RBAC    │
│ (JSON Schema)  │     │ (Org/Role/Member)  │
└────────────────┘     └────────────────────┘
    │
    ▼
FormEditor UI
(for human refinement)
```

### Key Responsibilities

| Responsibility | Owner | Details |
|---|---|---|
| **Generation** | LLM-driven | Prompt engineering for form structure |
| **Field Validation** | Validator | Field types, required fields, constraints |
| **Permission Mapping** | Permission Handler | Field-level RLS from Membership |
| **BPMN Binding** | Binding Handler | Process variables, task-specific forms |
| **Organization Verification** | Membership Client | Dropdown sources, member selectors |

---

## Key Concept: Form-Level vs Field-Level Permissions

### Form-Level Permissions (Access Control)
```
Who can SEE this form?
├─ Static: "Only finance team"
├─ Dynamic: "Only members in approver role"
└─ Formula: "Members of department X with role Y"
```

### Field-Level Permissions (Data Control)
```
For each field in the form:
├─ View: Who can see this field
├─ Edit: Who can modify this field
└─ Require: For whom is this field required

Example:
├─ budget_amount: View=[manager+], Edit=[manager+], Required=[true]
├─ approval_notes: View=[approver], Edit=[approver], Required=[true]
└─ internal_comments: View=[finance], Edit=[finance], Required=[false]
```

---

## Detailed Design

### 1. MCP Tool Interface

#### Tool 1: `generate_form`

**Purpose**: Generate form definition from natural language requirement

**Input Schema**:
```json
{
  "tenant_id": "integer (required)",
  "form_name": "string (required) - e.g., 'Drug Approval Application'",
  "form_type": "string enum: startup|task_specific|standalone",
  "description": "string (required) - Natural language form description",
  "context": {
    "process_name": "string (optional) - If binding to BPMN process",
    "task_name": "string (optional) - If task-specific form",
    "departments": ["array of dept names"],
    "roles": ["array of role names"],
    "process_variables": ["array of variables from BPMN"],
    "form_fields_hint": ["array of suggested field names"]
  }
}
```

**Output Schema**:
```json
{
  "success": "boolean",
  "form_definition": {
    "form_id": "string - Unique form ID",
    "form_name": "string",
    "form_type": "string: startup|task_specific|standalone",
    "description": "string",
    "fields": [
      {
        "field_id": "string",
        "field_name": "string",
        "field_type": "string enum: text|textarea|number|select|checkbox|date|file",
        "label": "string",
        "description": "string (optional)",
        "required": "boolean",
        "default_value": "any (optional)",
        "validation": {
          "min": "number (optional)",
          "max": "number (optional)",
          "pattern": "regex (optional)",
          "allowed_values": ["array (optional)"]
        },
        "data_binding": {
          "bpmn_variable": "string (optional) - Process variable it maps to",
          "source_type": "string enum: user_input|calculated|from_membership|from_kb",
          "source_config": {
            "if source_type == 'from_membership'": {
              "entity_type": "string enum: member|role|department",
              "entity_name": "string (optional)",
              "filter": "string (optional) - Additional filter logic"
            },
            "if source_type == 'from_kb'": {
              "kb_query": "string - Semantic search query",
              "result_field": "string - Which field from KB result to use"
            }
          }
        },
        "permissions": {
          "view": {
            "condition": "string - Formula or role/dept reference",
            "applies_to": ["array of roles/depts or '*' for all"]
          },
          "edit": {
            "condition": "string",
            "applies_to": ["array of roles/depts or '*' for all"]
          },
          "required": {
            "condition": "string",
            "applies_to": ["array of roles/depts or '*' for all"]
          }
        },
        "ui_hints": {
          "display_order": "integer",
          "column_width": "string enum: full|half|third",
          "help_text": "string (optional)",
          "placeholder": "string (optional)"
        }
      }
    ],
    "sections": [
      {
        "section_id": "string",
        "section_name": "string",
        "description": "string (optional)",
        "fields": ["array of field_ids in this section"]
      }
    ],
    "form_permissions": {
      "view_condition": "string - Formula determining visibility",
      "view_applies_to": ["array of roles/depts"]
    }
  },
  "bpmn_bindings": {
    "process_name": "string (if applicable)",
    "process_variables_mapped": ["array of BPMN variables bound"],
    "unmapped_variables": ["array of BPMN variables not in form"]
  },
  "validation_warnings": ["array of warnings"],
  "confidence_score": "0.0-1.0"
}
```

**Execution Flow**:

1. **Input Validation**
   - Tenant exists in Membership
   - Form name is unique in tenant
   - Description is meaningful

2. **Organization Context Loading**
   - Fetch departments from Membership
   - Fetch roles from Membership
   - Fetch members (for dropdowns if needed)

3. **LLM Prompt Engineering** (See Section 3)
   - Provide Membership org context
   - Include BPMN variables if process binding
   - Specify form generation requirements

4. **Knowledge Base Query** (optional)
   - Search KB for similar forms
   - Extract field templates
   - Get field naming conventions

5. **Form Generation**
   - Call LLM to generate form fields
   - Include permission rules for each field

6. **Permission Mapping** (See Section 2)
   - Map field permissions to Membership roles/depts
   - Generate view/edit/required conditions

7. **BPMN Binding** (if applicable)
   - Match form fields to process variables
   - Generate data binding configurations

8. **Validation** (See Section 4)
   - Validate form structure
   - Check field types and constraints
   - Verify permission conditions

9. **Return Result**
   - Complete form definition ready for FormEditor
   - Warnings for manual review

**Error Handling**:
```
- Invalid tenant: Return 404
- Invalid organization context: Return 400 with details
- LLM generation fails: Return fallback form structure
- Permission validation fails: Return with warnings
```

---

#### Tool 2: `validate_form`

**Purpose**: Validate form definition and permission rules

**Input Schema**:
```json
{
  "tenant_id": "integer (required)",
  "form_definition": "object (required) - Full form definition",
  "strict_mode": "boolean (optional, default: false)",
  "bpmn_context": {
    "process_variables": ["array of available BPMN variables (optional)"]
  }
}
```

**Output Schema**:
```json
{
  "valid": "boolean",
  "errors": ["array of critical errors"],
  "warnings": ["array of warnings"],
  "issues": {
    "field_issues": [
      {
        "field_id": "string",
        "issue_type": "string enum: invalid_type|missing_label|permission_error|binding_error",
        "message": "string"
      }
    ],
    "permission_issues": [
      {
        "field_id": "string",
        "issue": "string - Description of permission problem"
      }
    ],
    "binding_issues": [
      {
        "field_id": "string",
        "issue": "string - BPMN binding problem"
      }
    ],
    "org_mismatches": ["array of roles/depts that don't exist in Membership"]
  },
  "coverage": {
    "all_bpmn_variables_covered": "boolean",
    "unmapped_variables": ["array of process variables not in form"]
  },
  "confidence_score": "0.0-1.0",
  "suggestions": ["array of improvement suggestions"]
}
```

**Validation Rules**:

1. **Field Structure**
   - Each field has valid type (text, textarea, number, select, checkbox, date, file)
   - Field has label and description
   - Field constraints are valid (min/max for numbers, pattern for text)

2. **Permissions**
   - Permission conditions reference valid roles/departments
   - View permission doesn't contradict edit permission
   - Required permission makes sense (can't require field if not viewable)
   - Permission formulas are valid SpEL expressions

3. **BPMN Binding** (if applicable)
   - All referenced process variables exist
   - Variable types match field types (number field ↔ number variable)
   - Data flow direction is correct (input vs output)

4. **Organization Integration**
   - All referenced departments exist in Membership
   - All referenced roles exist in Membership
   - Dropdown sources (member selectors) resolve correctly

5. **Field Dependencies**
   - No circular dependencies
   - Conditional visibility logic is valid
   - Calculated fields have valid formulas

---

#### Tool 3: `suggest_field_permissions`

**Purpose**: Recommend field-level permissions based on form context

**Input Schema**:
```json
{
  "tenant_id": "integer (required)",
  "field_description": "string (required) - What is this field for?",
  "field_type": "string enum: text|number|select|etc",
  "context": {
    "form_name": "string",
    "process_name": "string (optional)",
    "departments": ["array"],
    "roles": ["array"]
  }
}
```

**Output Schema**:
```json
{
  "recommended_permissions": {
    "view": {
      "applies_to": ["array of roles/depts"],
      "condition": "string - Formula",
      "rationale": "string explanation",
      "confidence": "0.0-1.0"
    },
    "edit": {
      "applies_to": ["array of roles/depts"],
      "condition": "string",
      "rationale": "string",
      "confidence": "0.0-1.0"
    },
    "required": {
      "applies_to": ["array of roles/depts"],
      "condition": "string",
      "rationale": "string",
      "confidence": "0.0-1.0"
    }
  },
  "alternatives": [
    {
      "name": "Alternative A",
      "permissions": { ... },
      "pros": ["array"],
      "cons": ["array"]
    }
  ]
}
```

**Logic Examples**:

For field: "Budget Amount" in "Approval Process"

- ✅ **View**: All roles (confidence: 1.0) - "Everyone needs to see the amount"
- ✅ **Edit**: Only managers (confidence: 0.9) - "Only managers should set budget"
- ✅ **Required**: All roles (confidence: 0.95) - "Budget amount is always required"

For field: "Internal Audit Notes" in same process

- ✅ **View**: finance + audit roles only (confidence: 0.95)
- ✅ **Edit**: audit role only (confidence: 1.0)
- ✅ **Required**: audit role only (confidence: 0.9)

---

#### Tool 4: `generate_form_section_template`

**Purpose**: Generate structured sections for complex forms

**Input Schema**:
```json
{
  "tenant_id": "integer (required)",
  "form_name": "string (required)",
  "num_sections": "integer (optional, default: auto-detect)",
  "field_list": ["array of field descriptions"]
}
```

**Output Schema**:
```json
{
  "sections": [
    {
      "section_id": "string",
      "section_name": "string",
      "section_description": "string",
      "purpose": "string - Why this section exists",
      "fields": [
        {
          "field_name": "string",
          "field_type": "string",
          "required": "boolean"
        }
      ],
      "visibility": {
        "visible_to": ["array of roles/depts"],
        "collapsible": "boolean"
      }
    }
  ],
  "suggested_flow": "string - Order of sections to fill"
}
```

---

### 2. Permission Model Details

#### 2.1 Permission Expressions

Permission conditions use a simplified formula language:

```
Simple conditions:
├─ "role:approver" - Has approver role
├─ "dept:finance" - In finance department
├─ "member:123" - Specific member
└─ "*" - Everyone (public)

Complex conditions (SpEL):
├─ "role:approver OR role:manager" - Any of these roles
├─ "dept:finance AND role:manager" - Must be manager in finance
├─ "process.variable > 10000" - Based on BPMN variable
└─ "user.role == 'approver' AND process.amount > 50000" - Complex logic
```

#### 2.2 Permission Resolution Algorithm

When rendering form for user:

```
For each field:
  1. Can user VIEW this field?
     - Check: field.permissions.view applies to user's roles/depts?
     - If NO: Hide field
     - If YES: Continue

  2. Can user EDIT this field?
     - Check: field.permissions.edit applies to user?
     - If NO: Render as read-only
     - If YES: Render as editable

  3. Is field REQUIRED?
     - Check: field.permissions.required applies to user?
     - If YES: Mark as required
     - If NO: Mark as optional

Result: Personalized form for each user based on their role/dept
```

#### 2.3 Example: Drug Approval Form

```json
{
  "form_id": "pharma_approval_app",
  "fields": [
    {
      "field_id": "drug_name",
      "label": "Drug Name",
      "field_type": "text",
      "required": true,
      "permissions": {
        "view": {
          "applies_to": ["*"],
          "condition": "*"
        },
        "edit": {
          "applies_to": ["role:applicant"],
          "condition": "role:applicant"
        },
        "required": {
          "applies_to": ["*"],
          "condition": "*"
        }
      }
    },
    {
      "field_id": "approval_notes",
      "label": "Approval Decision Notes",
      "field_type": "textarea",
      "required": true,
      "permissions": {
        "view": {
          "applies_to": ["role:approver", "role:manager"],
          "condition": "role:approver OR role:manager"
        },
        "edit": {
          "applies_to": ["role:approver"],
          "condition": "role:approver"
        },
        "required": {
          "applies_to": ["role:approver"],
          "condition": "role:approver"
        }
      }
    },
    {
      "field_id": "budget_code",
      "label": "Budget Code",
      "field_type": "select",
      "data_binding": {
        "source_type": "from_membership",
        "source_config": {
          "entity_type": "role",
          "entity_name": "budget_manager"
        }
      },
      "permissions": {
        "view": {
          "applies_to": ["dept:finance"],
          "condition": "dept:finance"
        },
        "edit": {
          "applies_to": ["role:budget_manager"],
          "condition": "role:budget_manager"
        },
        "required": {
          "applies_to": ["dept:finance"],
          "condition": "dept:finance"
        }
      }
    }
  ]
}
```

---

### 3. LLM Prompt Engineering

#### 3.1 System Prompt for Form Generation

```
You are a form design expert that translates natural language form requirements
into valid form definitions following JSON schema.

## CRITICAL REQUIREMENTS

1. **Form Structure**:
   - Form must be valid JSON
   - All fields must have required properties: field_id, field_name, field_type, label, required
   - Field types: text, textarea, number, select, checkbox, date, file, email, url
   - Fields must be logically organized (can suggest sections)

2. **Permissions** (Field-Level RBAC):
   - Each field must have view/edit/required permissions
   - Permissions reference roles or departments from the organization context
   - Format: "role:approver", "dept:finance", "*" for public, or SpEL for complex logic
   - Ensure view permission includes or exceeds edit permission
   - Required permission should be subset of who can view/edit

3. **Membership Integration**:
   - Reference actual departments and roles from organization context
   - For dropdown fields, specify source as "from_membership" with entity_type and entity_name
   - Validate that all referenced roles/depts exist in provided context
   - Use consistent naming (lowercase, underscores)

4. **BPMN Binding** (if applicable):
   - All fields that correspond to process variables must be explicitly mapped
   - data_binding.bpmn_variable must match BPMN process variable name exactly
   - Field type should match BPMN variable type
   - Handle input vs output directions correctly

5. **Data Validation**:
   - Text fields: max_length constraints
   - Number fields: min/max values, decimal places
   - Select fields: allowed_values array
   - Date fields: min_date/max_date constraints
   - File fields: allowed_file_types

6. **UX Best Practices**:
   - Logical field ordering (basic info → details → validation → confirmation)
   - Grouping related fields into sections
   - Conditional visibility where appropriate
   - Help text for complex fields
   - Placeholder text for guidance

## OUTPUT FORMAT

Return ONLY valid JSON form definition. Start with:
{
  "form_id": "...",
  "form_name": "...",
  ...
}

Do NOT include markdown, explanations, or multiple JSON objects.
```

#### 3.2 Input Context Template

```json
{
  "user_requirement": "string - Natural language form description",

  "organization_context": {
    "departments": [
      {"id": "dept_001", "name": "finance"},
      {"id": "dept_002", "name": "medical"},
      {"id": "dept_003", "name": "compliance"}
    ],
    "roles": [
      {"id": "role_001", "name": "approver", "members_count": 5},
      {"id": "role_002", "name": "reviewer", "members_count": 8},
      {"id": "role_003", "name": "manager", "members_count": 3}
    ]
  },

  "bpmn_context": {
    "process_name": "string (optional)",
    "process_variables": [
      {
        "name": "applicant_name",
        "type": "string",
        "direction": "input"
      },
      {
        "name": "approval_decision",
        "type": "string",
        "direction": "output"
      }
    ]
  },

  "form_type": "string: startup|task_specific|standalone",

  "constraints": {
    "max_fields": "integer (optional)",
    "required_sections": ["array of section names"]
  }
}
```

#### 3.3 Few-Shot Examples

**Example 1: Simple Startup Form**
```
Input:
  requirement: "When starting a process, ask the user to enter their name and select a department"
  process_variables: ["applicant_name", "applicant_department"]
  available_depts: ["finance", "medical", "operations"]

Output:
{
  "form_type": "startup",
  "fields": [
    {
      "field_id": "applicant_name",
      "field_name": "applicant_name",
      "field_type": "text",
      "label": "Your Name",
      "required": true,
      "data_binding": {
        "bpmn_variable": "applicant_name",
        "source_type": "user_input"
      },
      "permissions": {
        "view": {"applies_to": ["*"], "condition": "*"},
        "edit": {"applies_to": ["*"], "condition": "*"},
        "required": {"applies_to": ["*"], "condition": "*"}
      }
    },
    {
      "field_id": "applicant_department",
      "field_name": "applicant_department",
      "field_type": "select",
      "label": "Department",
      "required": true,
      "data_binding": {
        "bpmn_variable": "applicant_department",
        "source_type": "from_membership",
        "source_config": {
          "entity_type": "department"
        }
      },
      "permissions": { ... }
    }
  ]
}
```

**Example 2: Task-Specific Form with Permissions**
```
Input:
  requirement: "Only the approver should see the approval notes field.
               It should be required for approvers but not shown to others"
  available_roles: ["approver", "reviewer", "applicant"]

Output:
{
  "form_type": "task_specific",
  "fields": [
    {
      "field_id": "approval_notes",
      "label": "Approval Decision Notes",
      "field_type": "textarea",
      "permissions": {
        "view": {
          "applies_to": ["role:approver"],
          "condition": "role:approver"
        },
        "edit": {
          "applies_to": ["role:approver"],
          "condition": "role:approver"
        },
        "required": {
          "applies_to": ["role:approver"],
          "condition": "role:approver"
        }
      }
    }
  ]
}
```

**Example 3: Data-Driven Permissions**
```
Input:
  requirement: "The budget code field should only be visible and editable
               to finance department members"
  available_depts: ["finance", "operations"]
  available_roles: ["budget_manager"]

Output:
{
  "field_id": "budget_code",
  "label": "Budget Code",
  "field_type": "select",
  "data_binding": {
    "source_type": "from_membership",
    "source_config": {
      "entity_type": "role",
      "entity_name": "budget_manager"
    }
  },
  "permissions": {
    "view": {
      "applies_to": ["dept:finance"],
      "condition": "dept:finance"
    },
    "edit": {
      "applies_to": ["dept:finance", "role:budget_manager"],
      "condition": "dept:finance AND role:budget_manager"
    },
    "required": {
      "applies_to": ["dept:finance"],
      "condition": "dept:finance"
    }
  }
}
```

---

### 4. Validation Engine

#### 4.1 Validation Pipeline

```
Input Form Definition
  │
  ├─ JSON Structure
  │  └─ Check: Valid JSON, required fields present
  │
  ├─ Field Validation
  │  ├─ Check: Valid field types
  │  ├─ Check: Each field has label
  │  ├─ Check: Constraints make sense (min < max)
  │  └─ Check: No duplicate field_ids
  │
  ├─ Permission Validation
  │  ├─ Check: Referenced roles exist in Membership
  │  ├─ Check: Referenced depts exist in Membership
  │  ├─ Check: Permission formulas are valid SpEL
  │  ├─ Check: View >= Edit >= Required (subset logic)
  │  └─ Check: No impossible conditions
  │
  ├─ BPMN Binding Validation (if applicable)
  │  ├─ Check: All referenced variables exist
  │  ├─ Check: Field type matches variable type
  │  ├─ Check: Variable direction is correct
  │  └─ Check: Required fields bind to required variables
  │
  ├─ Data Flow
  │  ├─ Check: Dependent fields have dependencies
  │  ├─ Check: No circular dependencies
  │  └─ Check: Calculated fields have formulas
  │
  └─ Final Decision
     └─ Return: valid (true/false) + warnings + suggestions
```

#### 4.2 Validation Rules (Detailed)

**Rule 1: Field Structure**
- Each field has unique field_id
- field_type is one of: text, textarea, number, select, checkbox, date, file, email, url
- label is provided and non-empty
- required is boolean

**Rule 2: Constraints**
- For number fields: min <= max
- For text fields: max_length > 0
- For select fields: allowed_values is non-empty array
- For file fields: allowed_file_types is non-empty array

**Rule 3: Permissions**
```
For each field:
  - view.applies_to references existing roles/depts
  - edit.applies_to is subset of view.applies_to
  - required.applies_to is subset of edit.applies_to
  - Permission formulas are valid SpEL expressions
  - No contradictory conditions (e.g., "role:approver AND role:reviewer")
```

**Rule 4: BPMN Binding**
- If form_type == "startup": fields should map to input variables
- If form_type == "task_specific": fields can map to input or output
- All required process variables have corresponding form fields
- Field type matches variable type

**Rule 5: Membership Integration**
```
For each field with source_type == "from_membership":
  - entity_type is valid (member, role, department)
  - entity_name references existing entity in Membership
  - Filter logic (if present) is valid
```

**Rule 6: Sections**
- All fields referenced in sections exist
- Section IDs are unique
- Sections don't create orphaned fields

---

### 5. Form Types & Use Cases

#### 5.1 Process Startup Form

**Purpose**: Collect initial data when process instance is created

**Characteristics**:
- Shown once at process start
- Data maps to input process variables
- Must cover all required input variables
- Can ask for executor selection (form-driven pattern)

**Example**:
```
Drug Approval Startup Form:
├─ Drug Name (required, text)
├─ Manufacturer (required, select from KB)
├─ Estimated Budget (required, number)
└─ Select Primary Reviewer (required, select members from medical dept)
```

#### 5.2 Task-Specific Form

**Purpose**: Collect/display data specific to one BPMN task

**Characteristics**:
- Shown when user claims task in task list
- Data can be input (for task to collect) or output (for user to fill)
- Field-level permissions enforce who can edit what
- Can show progress through process

**Example**:
```
Medical Review Task Form:
├─ Drug Name (read-only, auto-populated from process)
├─ Manufacturer (read-only, auto-populated from process)
├─ Medical Assessment (required for reviewers, hidden from others)
├─ Safety Concerns (required for reviewers)
├─ Approval Recommendation (required for reviewers)
└─ Internal Notes (visible to medical dept only)
```

#### 5.3 Standalone Form

**Purpose**: Collect data outside of process context

**Characteristics**:
- Used for surveys, feedback, one-off data collection
- No BPMN process variables
- Can still have field-level permissions
- Submits data to KB or external system

**Example**:
```
User Feedback Form:
├─ Feedback Type (required, select)
├─ Comments (required, textarea)
├─ Your Department (optional, auto-filled from user context)
└─ Allow Follow-up Contact (optional, checkbox)
```

---

### 6. BPMN Form Binding

#### 6.1 How Forms Bind to BPMN

```
BPMN Process Definition:
  └─ Process Variable: applicant_name (type: string)
  └─ Process Variable: approval_decision (type: string)

Form Definition:
  └─ Field: applicant_name → maps to process variable "applicant_name"
  └─ Field: approval_decision → maps to process variable "approval_decision"

At Runtime:
  1. When process starts, Flowable creates variables
  2. FormRenderer loads form definition
  3. Form fields auto-populate from process variables
  4. When form submitted, values saved back to process
```

#### 6.2 Form Binding Specification

```json
{
  "data_binding": {
    "bpmn_variable": "string - Name of BPMN process variable",
    "source_type": "string enum: user_input|calculated|from_membership|from_kb",
    "source_config": {
      "if source_type == 'user_input'": {
        // No additional config needed
      },
      "if source_type == 'calculated'": {
        "formula": "string - SpEL formula to calculate value"
      },
      "if source_type == 'from_membership'": {
        "entity_type": "string enum: member|role|department",
        "entity_name": "string (optional) - Specific entity",
        "filter": "string (optional) - Additional filter"
      },
      "if source_type == 'from_kb'": {
        "kb_query": "string - Semantic search query",
        "result_field": "string - Which field from result"
      }
    }
  }
}
```

#### 6.3 Data Flow Example

**Drug Approval Process BPMN**:
```
Process Variables:
  ├─ applicant_name: string
  ├─ applicant_department: string
  ├─ drug_name: string
  └─ approval_decision: string (output)

Startup Form:
  ├─ Applicant Name field → binds to applicant_name
  ├─ Department field → binds to applicant_department
  └─ Drug Name field → binds to drug_name

Task Form (Approval Task):
  ├─ Drug Name field (read-only) → reads from drug_name
  ├─ Applicant field (read-only) → reads from applicant_name
  ├─ Approval Decision field → binds to approval_decision (output)
  └─ Approval Notes field → binds to approval_notes (output)
```

---

### 7. Example: Complete Drug Approval Form

**Input Natural Language**:
```
"Drug approval form for the pharmaceutical process:
1. Applicant enters: drug name, manufacturer, estimated development cost
2. Applicant selects which medical expert should review it
3. The medical review task shows:
   - Read-only: drug name, manufacturer, cost (from process)
   - Editable by reviewers only: medical assessment, safety concerns, recommendation
   - Internal notes field visible only to finance dept
4. Finance approval task shows:
   - Read-only: all above info
   - Editable: budget code (only for finance dept members)
   - Approval decision (visible and editable by approvers)
5. Some fields are always required, some become required based on role"
```

**Generated Form Definition**:
```json
{
  "form_id": "pharma_approval_complete",
  "form_name": "Drug Approval Application",
  "form_type": "startup",
  "description": "Complete form for pharmaceutical drug approval process",
  "sections": [
    {
      "section_id": "applicant_info",
      "section_name": "Applicant Information",
      "fields": ["drug_name", "manufacturer", "estimated_cost"]
    },
    {
      "section_id": "assignment",
      "section_name": "Review Assignment",
      "fields": ["primary_reviewer"]
    }
  ],
  "fields": [
    {
      "field_id": "drug_name",
      "field_name": "drug_name",
      "field_type": "text",
      "label": "Drug Name",
      "description": "Official name of the drug being approved",
      "required": true,
      "data_binding": {
        "bpmn_variable": "drug_name",
        "source_type": "user_input"
      },
      "permissions": {
        "view": {
          "applies_to": ["*"],
          "condition": "*"
        },
        "edit": {
          "applies_to": ["role:applicant"],
          "condition": "role:applicant"
        },
        "required": {
          "applies_to": ["*"],
          "condition": "*"
        }
      }
    },
    {
      "field_id": "manufacturer",
      "field_name": "manufacturer",
      "field_type": "text",
      "label": "Manufacturer",
      "required": true,
      "data_binding": {
        "bpmn_variable": "manufacturer",
        "source_type": "user_input"
      },
      "permissions": {
        "view": {
          "applies_to": ["*"],
          "condition": "*"
        },
        "edit": {
          "applies_to": ["role:applicant"],
          "condition": "role:applicant"
        },
        "required": {
          "applies_to": ["*"],
          "condition": "*"
        }
      }
    },
    {
      "field_id": "estimated_cost",
      "field_name": "estimated_cost",
      "field_type": "number",
      "label": "Estimated Development Cost (USD)",
      "required": true,
      "data_binding": {
        "bpmn_variable": "estimated_cost",
        "source_type": "user_input"
      },
      "validation": {
        "min": 0,
        "max": 1000000000
      },
      "permissions": {
        "view": {
          "applies_to": ["*"],
          "condition": "*"
        },
        "edit": {
          "applies_to": ["role:applicant"],
          "condition": "role:applicant"
        },
        "required": {
          "applies_to": ["*"],
          "condition": "*"
        }
      }
    },
    {
      "field_id": "primary_reviewer",
      "field_name": "primary_reviewer",
      "field_type": "select",
      "label": "Select Primary Medical Reviewer",
      "required": true,
      "data_binding": {
        "bpmn_variable": "primary_reviewer_id",
        "source_type": "from_membership",
        "source_config": {
          "entity_type": "member",
          "filter": "dept:medical AND role:reviewer"
        }
      },
      "permissions": {
        "view": {
          "applies_to": ["*"],
          "condition": "*"
        },
        "edit": {
          "applies_to": ["role:applicant"],
          "condition": "role:applicant"
        },
        "required": {
          "applies_to": ["*"],
          "condition": "*"
        }
      }
    },
    {
      "field_id": "medical_assessment",
      "field_name": "medical_assessment",
      "field_type": "textarea",
      "label": "Medical Assessment",
      "required": false,
      "permissions": {
        "view": {
          "applies_to": ["dept:medical"],
          "condition": "dept:medical"
        },
        "edit": {
          "applies_to": ["role:reviewer"],
          "condition": "role:reviewer"
        },
        "required": {
          "applies_to": ["role:reviewer"],
          "condition": "role:reviewer"
        }
      }
    },
    {
      "field_id": "safety_concerns",
      "field_name": "safety_concerns",
      "field_type": "textarea",
      "label": "Safety Concerns and Risk Assessment",
      "required": false,
      "permissions": {
        "view": {
          "applies_to": ["dept:medical", "dept:finance"],
          "condition": "dept:medical OR dept:finance"
        },
        "edit": {
          "applies_to": ["role:reviewer"],
          "condition": "role:reviewer"
        },
        "required": {
          "applies_to": ["role:reviewer"],
          "condition": "role:reviewer"
        }
      }
    },
    {
      "field_id": "recommendation",
      "field_name": "recommendation",
      "field_type": "select",
      "label": "Medical Recommendation",
      "validation": {
        "allowed_values": ["approved", "approved_with_conditions", "rejected", "requires_more_data"]
      },
      "required": false,
      "permissions": {
        "view": {
          "applies_to": ["dept:medical", "dept:finance"],
          "condition": "dept:medical OR dept:finance"
        },
        "edit": {
          "applies_to": ["role:reviewer"],
          "condition": "role:reviewer"
        },
        "required": {
          "applies_to": ["role:reviewer"],
          "condition": "role:reviewer"
        }
      }
    },
    {
      "field_id": "internal_notes",
      "field_name": "internal_notes",
      "field_type": "textarea",
      "label": "Internal Finance Notes",
      "required": false,
      "permissions": {
        "view": {
          "applies_to": ["dept:finance"],
          "condition": "dept:finance"
        },
        "edit": {
          "applies_to": ["dept:finance"],
          "condition": "dept:finance"
        },
        "required": {
          "applies_to": [],
          "condition": "false"
        }
      }
    },
    {
      "field_id": "budget_code",
      "field_name": "budget_code",
      "field_type": "select",
      "label": "Budget Code",
      "required": false,
      "data_binding": {
        "bpmn_variable": "budget_code",
        "source_type": "from_membership",
        "source_config": {
          "entity_type": "role",
          "entity_name": "budget_manager"
        }
      },
      "permissions": {
        "view": {
          "applies_to": ["dept:finance"],
          "condition": "dept:finance"
        },
        "edit": {
          "applies_to": ["role:budget_manager"],
          "condition": "role:budget_manager"
        },
        "required": {
          "applies_to": ["dept:finance"],
          "condition": "dept:finance"
        }
      }
    },
    {
      "field_id": "approval_decision",
      "field_name": "approval_decision",
      "field_type": "select",
      "label": "Approval Decision",
      "validation": {
        "allowed_values": ["approved", "approved_with_conditions", "rejected"]
      },
      "required": false,
      "data_binding": {
        "bpmn_variable": "approval_decision",
        "source_type": "user_input"
      },
      "permissions": {
        "view": {
          "applies_to": ["role:approver"],
          "condition": "role:approver"
        },
        "edit": {
          "applies_to": ["role:approver"],
          "condition": "role:approver"
        },
        "required": {
          "applies_to": ["role:approver"],
          "condition": "role:approver"
        }
      }
    }
  ]
}
```

---

## Implementation Checklist

### Week 1: Design & Setup
- [ ] Finalize LLM prompt templates for forms
- [ ] Design form JSON schema and validation rules
- [ ] Design permission model and SpEL expression parser
- [ ] Create Membership client for org context queries
- [ ] Create KB client for form template queries
- [ ] Set up test fixtures (sample org data, forms)

### Week 2: Core Implementation
- [ ] Implement `generate_form` tool
- [ ] Implement LLM integration with prompt engineering
- [ ] Implement `validate_form` tool
- [ ] Implement `suggest_field_permissions` tool
- [ ] Implement `generate_form_section_template` tool
- [ ] Implement permission expression parser (SpEL support)
- [ ] Implement BPMN binding validation
- [ ] Write unit tests for all tools
- [ ] Integration tests with Membership client

### Week 3: Refinement
- [ ] End-to-end testing with real examples
- [ ] Permission model testing (complex scenarios)
- [ ] BPMN binding correctness verification
- [ ] Error handling and fallback strategies
- [ ] Performance optimization
- [ ] Documentation

### Testing Strategy
- **Unit Tests**: Each tool independently
- **Integration Tests**: With Membership client
- **Permission Tests**: View/Edit/Required logic with various roles
- **BPMN Tests**: Form binding to process variables
- **E2E Tests**: Full form generation → validation → rendering
- **Error Cases**: Missing org data, invalid permissions, broken BPMN binding

---

## Success Criteria

- [x] Architecture aligned with Membership RBAC integration
- [x] Field-level permission model fully documented
- [x] BPMN binding specifications defined
- [ ] FORM-MCP generates valid forms for 85%+ of inputs
- [ ] Validation catches 95%+ of permission issues before runtime
- [ ] Permission resolution algorithm tested against 50+ role combinations
- [ ] Generation time < 5 seconds (including LLM call)
- [ ] All field-level permissions correctly enforced at runtime
- [ ] Confidence scores calibrated (0.5 = 50% chance of success)
- [ ] Forms work correctly with ProcessEditor BPMN bindings

---

## Appendix: Form JSON Schema

### Core Form Structure

```json
{
  "form_id": "string - Unique identifier",
  "form_name": "string - Display name",
  "form_type": "string enum: startup|task_specific|standalone",
  "description": "string - Description of form purpose",
  "sections": [
    {
      "section_id": "string",
      "section_name": "string",
      "description": "string",
      "fields": ["array of field_ids"],
      "visibility": {
        "visible_to": ["array of roles/depts"],
        "collapsible": "boolean"
      }
    }
  ],
  "fields": [
    {
      "field_id": "string",
      "field_name": "string",
      "field_type": "string enum: text|textarea|number|select|checkbox|date|file|email|url",
      "label": "string",
      "description": "string",
      "required": "boolean",
      "default_value": "any",
      "validation": {
        "min": "number",
        "max": "number",
        "pattern": "string - regex",
        "allowed_values": ["array"],
        "min_length": "number",
        "max_length": "number"
      },
      "data_binding": {
        "bpmn_variable": "string",
        "source_type": "string enum: user_input|calculated|from_membership|from_kb",
        "source_config": { "...": "depends on source_type" }
      },
      "permissions": {
        "view": { "applies_to": ["array"], "condition": "string" },
        "edit": { "applies_to": ["array"], "condition": "string" },
        "required": { "applies_to": ["array"], "condition": "string" }
      },
      "ui_hints": {
        "display_order": "integer",
        "column_width": "string enum: full|half|third",
        "help_text": "string",
        "placeholder": "string"
      }
    }
  ],
  "form_permissions": {
    "view_condition": "string",
    "view_applies_to": ["array"]
  }
}
```

---

**PRD Status**: ✅ Complete and ready for implementation
**Next Step**: Begin ProcessEditor & FormEditor component architecture design, or start BPMN-MCP + FORM-MCP implementation
