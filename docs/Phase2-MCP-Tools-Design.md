# Phase 2 MCP工具设计规范

## 概述
本文档详细描述Phase 2工作流生成MCP的两个核心MCP的工具设计、输入输出规范和集成方式。

---

## 第一部分：BPMN-MCP (流程生成)

### MCP基本信息
- **MCP名称**: `bpmn`
- **版本**: `2.0`
- **用途**: 将自然语言需求转换为BPMN 2.0标准XML流程定义
- **实现位置**: `src/mcp_servers/bpmn_mcp.py`

### 核心工具

#### 工具1: `generate_bpmn_from_requirement`

**目的**: 根据自然语言需求生成完整的BPMN 2.0 XML流程定义

**输入Schema**:
```json
{
  "type": "object",
  "properties": {
    "requirement": {
      "type": "string",
      "description": "流程需求描述。例：'客户申请贷款，需要经过初审、复审、批准三个阶段，初审由风险部门负责，复审和批准由不同的经理负责'",
      "minLength": 10,
      "maxLength": 2000
    },
    "existing_bpmn": {
      "type": "string",
      "description": "现有BPMN 2.0 XML (用于修改/优化现有流程)。留空则从零创建。",
      "default": null
    },
    "executor_hints": {
      "type": "object",
      "description": "执行者角色/机构配置提示，帮助AI更准确地标记任务执行者",
      "properties": {
        "departments": {
          "type": "array",
          "description": "涉及的部门列表，如 ['风险部门', '财务部', '市场部']",
          "items": {"type": "string"}
        },
        "roles": {
          "type": "array",
          "description": "涉及的角色列表，如 ['初审员', '复审员', '批准人', '客户']",
          "items": {"type": "string"}
        },
        "task_executor_mapping": {
          "type": "object",
          "description": "任务与执行者的映射提示，如 {'初审': '风险部门', '批准': '总经理'}",
          "additionalProperties": {"type": "string"}
        }
      }
    },
    "constraints": {
      "type": "object",
      "description": "流程约束条件",
      "properties": {
        "max_parallel_tasks": {
          "type": "integer",
          "description": "最多并行任务数 (默认: 3)",
          "default": 3
        },
        "require_sequential": {
          "type": "boolean",
          "description": "是否要求严格顺序执行",
          "default": false
        },
        "include_error_handling": {
          "type": "boolean",
          "description": "是否包含错误处理分支",
          "default": true
        },
        "include_escalation": {
          "type": "boolean",
          "description": "是否包含升级处理路径",
          "default": false
        }
      }
    }
  },
  "required": ["requirement"]
}
```

**输出Schema** (ToolResult):
```json
{
  "success": true,
  "content": {
    "bpmn_xml": "<?xml version='1.0' encoding='UTF-8'?><bpmn:definitions xmlns:bpmn='...' ... </bpmn:definitions>",
    "process_id": "loan_approval_20250111",
    "process_name": "贷款申请审批流程",
    "metadata": {
      "elements_count": 8,
      "tasks": [
        {
          "id": "task_initial_review",
          "name": "初审",
          "type": "UserTask",
          "executor_type": "department",
          "executor_value": "风险部门"
        },
        {
          "id": "task_review",
          "name": "复审",
          "type": "UserTask",
          "executor_type": "role",
          "executor_value": "复审员"
        },
        {
          "id": "task_approval",
          "name": "批准",
          "type": "UserTask",
          "executor_type": "role",
          "executor_value": "批准人"
        }
      ],
      "gateways": [
        {
          "id": "gateway_review_decision",
          "name": "初审决策",
          "type": "ExclusiveGateway",
          "outgoing_paths": ["approved", "rejected"]
        }
      ],
      "executor_config": {
        "description": "执行者配置建议",
        "recommendations": [
          "初审任务建议分配给风险部门全体成员",
          "复审任务建议分配给具有复审权限的员工",
          "批准任务建议分配给总经理或授权人员"
        ]
      }
    }
  },
  "error_code": null
}
```

**关键点**:
1. **输出必须是标准BPMN 2.0 XML** - 可直接导入BPMN-JS编辑器
2. **metadata中包含执行者配置建议** - 帮助后续与Membership集成
3. **XML中每个任务节点包含文档注释** - 记录执行者类型和值
4. **支持修改现有流程** - 通过传入existing_bpmn参数

---

#### 工具2: `validate_bpmn_xml`

**目的**: 验证生成的BPMN XML是否符合规范且可执行

**输入Schema**:
```json
{
  "type": "object",
  "properties": {
    "bpmn_xml": {
      "type": "string",
      "description": "要验证的BPMN 2.0 XML"
    },
    "validate_executable": {
      "type": "boolean",
      "description": "是否验证可执行性(检查是否有完整的执行者配置)",
      "default": true
    },
    "validate_flowable_compatible": {
      "type": "boolean",
      "description": "是否验证Flowable兼容性",
      "default": true
    }
  },
  "required": ["bpmn_xml"]
}
```

**输出Schema**:
```json
{
  "success": true,
  "content": {
    "is_valid": true,
    "issues": [],
    "warnings": [
      {
        "type": "missing_executor",
        "element_id": "task_review",
        "element_name": "复审",
        "message": "任务节点缺少执行者配置，建议在文档中添加"
      }
    ],
    "statistics": {
      "total_elements": 8,
      "tasks_count": 3,
      "gateways_count": 1,
      "start_events": 1,
      "end_events": 1,
      "sequence_flows": 5
    },
    "executor_summary": {
      "configured_tasks": 2,
      "unconfigured_tasks": 1,
      "executor_types": ["department", "role"]
    }
  }
}
```

---

### BPMN-MCP实现要点

#### 内部架构
```python
class BpmnMCPServer(BaseMCPServer):
    def __init__(self):
        super().__init__("bpmn", "2.0")
        self.llm_client = ...  # LLM客户端
        self.bpmn_validator = BpmnValidator()
        self._register_tools()

    async def generate_bpmn(self, requirement: str, ...) -> ToolResult:
        # 步骤1: 使用LLM理解需求
        # - 提示词引导LLM识别：任务、角色、决策点、并行分支等
        # - 提示词要求输出结构化的流程定义

        # 步骤2: 使用结构化流程定义生成BPMN XML
        # - 可选方案A: 直接构建XML (使用lxml)
        # - 可选方案B: 使用bpmn-moddle库 (需Node.js)
        # - 可选方案C: 使用LLM生成并验证XML

        # 步骤3: 验证生成的XML
        # - 检查BPMN 2.0规范
        # - 检查Flowable兼容性

        # 步骤4: 返回结果
        pass

    async def validate_bpmn(self, bpmn_xml: str, ...) -> ToolResult:
        # 使用self.bpmn_validator验证XML
        pass
```

#### BPMN XML模板示例
```xml
<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                   xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
                   xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
                   xmlns:flowable="http://flowable.org/bpmn"
                   targetNamespace="http://flowable.org/bpmn"
                   exporter="Flowable"
                   exporterVersion="6.7.0">

  <!-- 流程定义 -->
  <bpmn:process id="loan_approval" name="贷款申请审批" isExecutable="true">

    <!-- 开始事件 -->
    <bpmn:startEvent id="start" name="申请开始"/>

    <!-- 用户任务 -->
    <bpmn:userTask id="task_initial_review" name="初审">
      <bpmn:documentation>
        {"executor_type": "department", "executor_value": "风险部门"}
      </bpmn:documentation>
    </bpmn:userTask>

    <!-- 排他网关 -->
    <bpmn:exclusiveGateway id="gateway_review" name="初审决策"/>

    <!-- 结束事件 -->
    <bpmn:endEvent id="end_approved" name="批准完成"/>

    <!-- 流转规则 -->
    <bpmn:sequenceFlow id="flow_1" sourceRef="start" targetRef="task_initial_review"/>
    <bpmn:sequenceFlow id="flow_2" sourceRef="task_initial_review" targetRef="gateway_review"/>
    <bpmn:sequenceFlow id="flow_3" sourceRef="gateway_review" targetRef="end_approved">
      <bpmn:conditionExpression xsi:type="bpmn:tFormalExpression">
        ${initialReviewPass == true}
      </bpmn:conditionExpression>
    </bpmn:sequenceFlow>
  </bpmn:process>

  <!-- 图形信息 -->
  <bpmndi:BPMNDiagram id="diagram">
    <bpmndi:BPMNPlane bpmnElement="loan_approval">
      <!-- 元素位置信息 -->
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>

</bpmn:definitions>
```

---

## 第二部分：FORM-MCP (表单生成)

### MCP基本信息
- **MCP名称**: `form`
- **版本**: `1.0`
- **用途**: 将自然语言需求转换为表单定义，并与BPMN流程节点关联
- **实现位置**: `src/mcp_servers/form_mcp.py`

### 核心工具

#### 工具1: `generate_form_from_requirement`

**目的**: 根据自然语言需求生成表单定义JSON

**输入Schema**:
```json
{
  "type": "object",
  "properties": {
    "requirement": {
      "type": "string",
      "description": "表单需求描述。例：'贷款申请表单，包含申请人信息(姓名、身份证、联系方式)、贷款信息(金额、用途、期限)'",
      "minLength": 10,
      "maxLength": 2000
    },
    "form_context": {
      "type": "object",
      "description": "表单上下文信息",
      "properties": {
        "process_name": {
          "type": "string",
          "description": "所属流程名称，如'贷款审批流程'"
        },
        "form_type": {
          "type": "string",
          "enum": ["initiate", "review", "approval", "execution"],
          "description": "表单类型: initiate(发起表单) review(审批表单) approval(批准表单) execution(执行表单)"
        },
        "related_bpmn_xml": {
          "type": "string",
          "description": "相关的BPMN流程XML，用于理解流程上下文"
        },
        "target_task_id": {
          "type": "string",
          "description": "表单关联的BPMN任务ID，如'task_initial_review'"
        }
      }
    },
    "field_requirements": {
      "type": "array",
      "description": "字段级需求(可选，用于精细化控制)",
      "items": {
        "type": "object",
        "properties": {
          "name": {
            "type": "string",
            "description": "字段名称"
          },
          "label": {
            "type": "string",
            "description": "字段标签"
          },
          "type": {
            "type": "string",
            "enum": ["text", "number", "date", "select", "checkbox", "radio", "textarea", "email", "phone", "file"],
            "description": "字段类型"
          },
          "required": {
            "type": "boolean"
          },
          "description": {
            "type": "string"
          }
        }
      }
    },
    "constraints": {
      "type": "object",
      "description": "表单约束条件",
      "properties": {
        "max_fields": {
          "type": "integer",
          "description": "最多字段数 (默认: 20)",
          "default": 20
        },
        "enable_conditional_display": {
          "type": "boolean",
          "description": "是否启用条件显示逻辑",
          "default": true
        },
        "enable_validation": {
          "type": "boolean",
          "description": "是否启用字段验证",
          "default": true
        }
      }
    }
  },
  "required": ["requirement"]
}
```

**输出Schema**:
```json
{
  "success": true,
  "content": {
    "form_schema": {
      "metadata": {
        "id": "form_loan_application_20250111",
        "name": "贷款申请表单",
        "description": "用户申请贷款时填写的初始表单",
        "version": "1.0.0",
        "createdAt": 1705000000,
        "updatedAt": 1705000000
      },
      "controls": [
        {
          "id": "applicant_name",
          "type": "text",
          "label": "申请人姓名",
          "width": "100%",
          "hideLabel": false,
          "props": {
            "required": true,
            "disabled": false,
            "readonly": false,
            "placeholder": "请输入您的真实姓名",
            "maxLength": 50,
            "validation": [
              {
                "type": "minLength",
                "value": 2,
                "message": "姓名至少2个字符"
              }
            ]
          },
          "children": []
        },
        {
          "id": "applicant_id_card",
          "type": "text",
          "label": "身份证号",
          "width": "100%",
          "hideLabel": false,
          "props": {
            "required": true,
            "placeholder": "请输入您的身份证号",
            "validation": [
              {
                "type": "pattern",
                "value": "^\\d{17}[\\dXx]$",
                "message": "请输入有效的身份证号"
              }
            ]
          },
          "children": []
        },
        {
          "id": "loan_amount",
          "type": "number",
          "label": "贷款金额（万元）",
          "width": "100%",
          "hideLabel": false,
          "props": {
            "required": true,
            "min": 1,
            "max": 1000,
            "placeholder": "请输入贷款金额",
            "validation": [
              {
                "type": "min",
                "value": 1,
                "message": "贷款金额不能低于1万元"
              }
            ]
          },
          "children": []
        },
        {
          "id": "loan_purpose",
          "type": "select",
          "label": "贷款用途",
          "width": "100%",
          "hideLabel": false,
          "props": {
            "required": true,
            "options": [
              {"label": "个人消费", "value": "consumption"},
              {"label": "创业", "value": "business"},
              {"label": "教育", "value": "education"},
              {"label": "其他", "value": "other"}
            ]
          },
          "children": []
        }
      ],
      "version": "1.0.0"
    },
    "field_mappings": {
      "description": "字段映射信息，用于与BPMN流程变量关联",
      "mappings": [
        {
          "form_field_id": "applicant_name",
          "bpmn_variable_name": "applicantName",
          "data_type": "string"
        },
        {
          "form_field_id": "loan_amount",
          "bpmn_variable_name": "loanAmount",
          "data_type": "number"
        }
      ]
    },
    "validation_rules": {
      "description": "整体表单级的验证规则",
      "rules": [
        {
          "type": "custom",
          "condition": "loan_amount > 100",
          "action": "show_field",
          "target_field": "loan_purpose",
          "message": "贷款金额超过100万需要选择用途"
        }
      ]
    }
  }
}
```

---

#### 工具2: `bind_form_to_process`

**目的**: 将表单与BPMN流程中的任务节点关联

**输入Schema**:
```json
{
  "type": "object",
  "properties": {
    "form_schema": {
      "type": "object",
      "description": "表单Schema (从generate_form_from_requirement工具获得)"
    },
    "bpmn_xml": {
      "type": "string",
      "description": "BPMN流程定义XML"
    },
    "bindings": {
      "type": "array",
      "description": "表单与BPMN任务的关联配置",
      "items": {
        "type": "object",
        "properties": {
          "task_id": {
            "type": "string",
            "description": "BPMN任务ID，如'task_initial_review'"
          },
          "form_id": {
            "type": "string",
            "description": "表单ID"
          },
          "form_mode": {
            "type": "string",
            "enum": ["initiate", "review", "approval"],
            "description": "表单在该任务中的模式"
          },
          "field_visibility": {
            "type": "object",
            "description": "在该任务中哪些字段可见/可编辑/只读",
            "properties": {
              "visible_fields": {
                "type": "array",
                "items": {"type": "string"}
              },
              "editable_fields": {
                "type": "array",
                "items": {"type": "string"}
              },
              "readonly_fields": {
                "type": "array",
                "items": {"type": "string"}
              }
            }
          },
          "actions": {
            "type": "array",
            "description": "在该任务中可执行的操作，如'approve', 'reject', 'reassign'",
            "items": {"type": "string"}
          }
        },
        "required": ["task_id", "form_id", "form_mode"]
      }
    }
  },
  "required": ["form_schema", "bpmn_xml", "bindings"]
}
```

**输出Schema**:
```json
{
  "success": true,
  "content": {
    "integration_config": {
      "process_id": "loan_approval",
      "forms": [
        {
          "form_id": "form_loan_application_20250111",
          "form_name": "贷款申请表单",
          "bindings": [
            {
              "task_id": "task_initial_review",
              "task_name": "初审",
              "form_mode": "review",
              "visible_fields": [
                "applicant_name",
                "applicant_id_card",
                "loan_amount",
                "loan_purpose"
              ],
              "editable_fields": ["review_notes"],
              "readonly_fields": [
                "applicant_name",
                "applicant_id_card",
                "loan_amount"
              ],
              "actions": ["approve", "reject", "reassign"]
            },
            {
              "task_id": "task_approval",
              "task_name": "批准",
              "form_mode": "approval",
              "visible_fields": [
                "applicant_name",
                "loan_amount",
                "initial_review_result"
              ],
              "editable_fields": ["approval_notes"],
              "readonly_fields": [
                "applicant_name",
                "loan_amount",
                "initial_review_result"
              ],
              "actions": ["approve", "reject"]
            }
          ]
        }
      ]
    },
    "flowable_integration_hints": {
      "description": "集成到Flowable的建议",
      "hints": [
        "将表单ID存储在任务的'formKey'属性中",
        "在Flowable表单引擎中注册这些表单定义",
        "配置字段与流程变量的映射关系"
      ]
    }
  }
}
```

---

### FORM-MCP实现要点

#### 内部架构
```python
class FormMCPServer(BaseMCPServer):
    def __init__(self):
        super().__init__("form", "1.0")
        self.llm_client = ...
        self.form_validator = FormValidator()
        self._register_tools()

    async def generate_form(self, requirement: str, ...) -> ToolResult:
        # 步骤1: 使用LLM理解表单需求
        # - 识别表单字段和属性
        # - 根据form_type生成不同的表单变体

        # 步骤2: 生成符合你的表单规范的Schema JSON
        # - metadata: 表单元数据
        # - controls: 字段定义数组
        # - validation: 验证规则

        # 步骤3: 生成字段映射
        # - 表单字段 → BPMN流程变量的映射

        # 步骤4: 返回结果
        pass

    async def bind_form_to_process(self, ...) -> ToolResult:
        # 关键：分析BPMN流程结构
        # - 识别所有UserTask节点
        # - 为每个任务确定表单模式 (initiate/review/approval)
        # - 根据任务类型配置字段可见性

        pass
```

#### 表单规范参考（你的现有实现）
需要从你的BPM项目中提取FormDesigner的规范。关键字段应包括：
- metadata (id, name, description, version)
- controls (id, type, label, width, props, children)
- validation rules
- event handlers (如果需要)

---

## 第三部分：集成规范

### 前端集成流程

```
用户在ChatPanel输入需求
    ↓
传给Planning Engine
    ↓
Planning Engine调用执行计划：
  [
    {
      "step": 1,
      "command": "bpmn.generate_bpmn_from_requirement",
      "description": "生成贷款申请流程",
      "params": {
        "query": {
          "requirement": "用户输入的完整需求"
        }
      }
    },
    {
      "step": 2,
      "command": "form.generate_form_from_requirement",
      "description": "生成贷款申请表单",
      "params": {
        "query": {
          "requirement": "表单需求",
          "related_bpmn_xml": "{从step 1获得的BPMN XML}"
        }
      }
    },
    {
      "step": 3,
      "command": "form.bind_form_to_process",
      "description": "将表单绑定到流程",
      "params": {
        "body": {
          "form_schema": "{从step 2获得的表单}",
          "bpmn_xml": "{从step 1获得的BPMN XML}",
          "bindings": "[根据流程自动生成的绑定配置]"
        }
      }
    }
  ]
    ↓
返回给前端：
  {
    "bpmn_xml": "...",
    "form_schema": "...",
    "integration_config": "..."
  }
    ↓
前端在BPMN编辑器中预览BPMN
前端提示用户进行修改/确认
    ↓
用户点击"保存到Membership"
    ↓
前端调用后端API保存到Membership
```

### 后端保存到Membership

新增API端点:
```python
POST /v1/workflows/save
{
  "process_definition": {
    "bpmn_xml": "...",
    "process_name": "...",
    "process_id": "..."
  },
  "forms": [
    {
      "form_schema": {...},
      "bindings": [...]
    }
  ]
}

Response:
{
  "success": true,
  "data": {
    "process_id": "loan_approval_20250111",
    "process_definition_id": "proc_def_123",
    "forms": [
      {
        "form_id": "form_123",
        "process_id": "proc_def_123"
      }
    ],
    "message": "流程和表单已保存到Membership"
  }
}
```

---

## 第四部分：LLM提示词设计

### BPMN生成提示词模板

```
你是一个BPM流程专家。根据用户的需求，生成一个有效的BPMN 2.0流程定义。

流程需求：
{requirement}

执行者信息：
- 部门：{departments}
- 角色：{roles}

输出格式：
生成标准的BPMN 2.0 XML，包括：
1. startEvent: 流程开始
2. userTask: 用户任务（需标注执行者）
3. exclusiveGateway: 决策点
4. endEvent: 流程结束
5. sequenceFlow: 流转规则

要求：
- XML必须是有效的、可执行的
- 每个userTask必须在文档中标注执行者信息
- 支持Flowable 6.7.0
- 包括异常处理分支（如果需要）

输出仅XML，无其他文本。
```

### 表单生成提示词模板

```
你是一个表单设计专家。根据用户的需求，生成一个详细的表单定义JSON。

表单需求：
{requirement}

表单类型：{form_type}

所属流程：{process_name}

输出格式（JSON Schema）：
{
  "metadata": {
    "id": "form_...",
    "name": "...",
    "description": "...",
    "version": "1.0.0"
  },
  "controls": [
    {
      "id": "field_id",
      "type": "text|number|date|select|...",
      "label": "字段标签",
      "width": "100%",
      "hideLabel": false,
      "props": {
        "required": true/false,
        "placeholder": "...",
        "validation": [...]
      },
      "children": []
    }
  ]
}

要求：
- 字段类型合理，匹配实际需求
- 包含必要的验证规则
- 生成JSON Schema，无其他文本
```

---

## 总结表格

| 方面 | BPMN-MCP | FORM-MCP |
|-----|----------|----------|
| **核心工具** | generate_bpmn, validate_bpmn | generate_form, bind_form_to_process |
| **输入** | 自然语言 + 可选的现有BPMN | 自然语言 + 可选的BPMN上下文 |
| **输出** | 标准BPMN 2.0 XML + 元数据 | JSON表单Schema + 字段映射 |
| **内部依赖** | LLM + BPMN验证器 | LLM + 表单验证器 |
| **Flowable集成** | 直接存储BPMN XML | 表单引擎集成 + 字段映射 |
| **前端展示** | BPMN-JS编辑器 | FormDesigner组件 |

