# Phase 2 MCP集成架构图

## 整体架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        AICMDEngine (主系统)                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌──────────────────────┐                                                    │
│  │   ChatPanel (前端)   │                                                    │
│  │  用户输入工作流需求   │                                                    │
│  └──────────┬───────────┘                                                    │
│             │ "我需要一个贷款审批流程..."                                     │
│             ↓                                                                 │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │              Planning Engine (规划引擎)                              │   │
│  │  生成执行计划: [step1, step2, step3]                               │   │
│  └────────────────┬─────────────────────────────────────────────────────┘   │
│                   │                                                           │
│    ┌──────────────┼──────────────┐                                           │
│    ↓              ↓              ↓                                           │
│  ┌──────────────────────┐   ┌──────────────────────┐                        │
│  │   BPMN-MCP (Step 1)  │   │   FORM-MCP (Step 2)  │                        │
│  │                      │   │                      │                        │
│  │ generate_bpmn_from   │   │ generate_form_from   │                        │
│  │ requirement          │   │ requirement          │                        │
│  │                      │   │                      │                        │
│  │ 输入: 流程需求       │   │ 输入: 表单需求       │                        │
│  │ 输出: BPMN XML ✓     │   │ 输出: 表单JSON ✓     │                        │
│  └──────────┬───────────┘   └──────────┬───────────┘                        │
│             │                          │                                    │
│             └──────────┬───────────────┘                                    │
│                        │                                                    │
│                        ↓                                                    │
│             ┌──────────────────────┐                                        │
│             │  FORM-MCP (Step 3)   │                                        │
│             │                      │                                        │
│             │ bind_form_to_process │                                        │
│             │                      │                                        │
│             │ 输入: BPMN + 表单    │                                        │
│             │ 输出: 集成配置 ✓     │                                        │
│             └──────────┬───────────┘                                        │
│                        │                                                    │
│                        ↓                                                    │
│             ┌──────────────────────────────┐                                │
│             │   ExecutionPanel (前端)      │                                │
│             │  预览 BPMN + 表单             │                                │
│             │  用户确认/修改                │                                │
│             └──────────┬───────────────────┘                                │
│                        │                                                    │
│                        ↓                                                    │
│             "保存到 Membership"                                             │
│                        │                                                    │
└────────────────────────┼────────────────────────────────────────────────────┘
                         │
                         ↓
         ┌───────────────────────────────┐
         │  Membership (后端/第三方)      │
         ├───────────────────────────────┤
         │  • BPMN 定义存储              │
         │  • 表单定义存储              │
         │  • Flowable 流程引擎         │
         │  • 机构/角色/人员管理        │
         │  • 流程执行和监控            │
         └───────────────────────────────┘
```

---

## 详细工作流程

### 1. 需求理解阶段

```
用户: "我需要一个贷款申请审批流程。客户提交申请后，需要经过风险部门初审、财务部复审、总经理批准三个阶段。"

    ↓

Planning Engine 生成执行计划:
[
  {
    step: 1,
    command: "bpmn.generate_bpmn_from_requirement",
    params: {
      query: {
        requirement: "完整需求文本",
        executor_hints: {
          departments: ["风险部门", "财务部"],
          roles: ["初审员", "复审员", "总经理"]
        }
      }
    }
  },
  {
    step: 2,
    command: "form.generate_form_from_requirement",
    params: {
      query: {
        requirement: "表单需求",
        form_context: {
          process_name: "贷款申请审批流程",
          form_type: "initiate"
        }
      }
    }
  },
  {
    step: 3,
    command: "form.bind_form_to_process",
    params: {
      body: {
        form_schema: "{来自step 2}",
        bpmn_xml: "{来自step 1}",
        bindings: "[自动生成]"
      }
    }
  }
]
```

### 2. BPMN生成阶段 (Step 1)

```
输入数据:
{
  "requirement": "...",
  "executor_hints": {
    "departments": ["风险部门", "财务部"],
    "roles": ["初审员", "复审员", "总经理"]
  }
}

    ↓

BPMN-MCP 内部处理:
1. LLM 理解需求
   ├─ 识别开始/结束事件
   ├─ 识别用户任务: [初审, 复审, 批准]
   ├─ 识别决策点: [初审通过?, 复审通过?]
   └─ 识别执行者: 风险部门 → 初审, 财务部 → 复审, 总经理 → 批准

2. 生成结构化流程定义
   └─ Process
      ├─ StartEvent
      ├─ Task: 初审 (executor: 风险部门)
      ├─ Gateway: 初审通过?
      │  ├─ Yes → Task: 复审
      │  └─ No → EndEvent: 拒绝
      ├─ Task: 复审 (executor: 财务部)
      ├─ Gateway: 复审通过?
      │  ├─ Yes → Task: 批准
      │  └─ No → EndEvent: 拒绝
      ├─ Task: 批准 (executor: 总经理)
      └─ EndEvent: 完成

3. 生成 BPMN 2.0 XML
   └─ 标准 XML 格式，包含位置信息

4. 生成元数据
   └─ tasks, gateways, executor_config 等

输出:
{
  "success": true,
  "content": {
    "bpmn_xml": "<?xml...>",
    "process_id": "loan_approval",
    "metadata": {
      "tasks": [
        {"id": "task_initial", "name": "初审", "executor": "风险部门"},
        ...
      ]
    }
  }
}
```

### 3. 表单生成阶段 (Step 2)

```
输入数据:
{
  "requirement": "贷款申请表，包含申请人信息、贷款信息",
  "form_context": {
    "process_name": "贷款申请审批流程",
    "form_type": "initiate",
    "related_bpmn_xml": "{来自Step 1}"
  }
}

    ↓

FORM-MCP 内部处理:
1. LLM 理解表单需求（结合BPMN上下文）
   ├─ 识别表单字段
   │  ├─ 申请人信息: 姓名, 身份证, 联系方式
   │  └─ 贷款信息: 金额, 用途, 期限
   ├─ 识别字段类型和验证规则
   └─ 生成字段与BPMN变量的映射

2. 生成表单Schema JSON (符合你的规范)
   {
     "metadata": {
       "id": "form_loan_app",
       "name": "贷款申请表单",
       "version": "1.0.0"
     },
     "controls": [
       {
         "id": "applicant_name",
         "type": "text",
         "label": "申请人姓名",
         "props": { "required": true, ... }
       },
       ...
     ]
   }

3. 生成字段映射
   └─ applicant_name → BPMN变量 applicantName (type: string)
   └─ loan_amount → BPMN变量 loanAmount (type: number)
   └─ ...

输出:
{
  "success": true,
  "content": {
    "form_schema": {...},
    "field_mappings": [...]
  }
}
```

### 4. 表单-流程绑定阶段 (Step 3)

```
输入数据:
{
  "form_schema": "{来自Step 2}",
  "bpmn_xml": "{来自Step 1}",
  "bindings": [
    {
      "task_id": "task_initial",
      "form_id": "form_loan_app",
      "form_mode": "review"
    },
    ...
  ]
}

    ↓

FORM-MCP 内部处理:
1. 解析 BPMN 中所有 UserTask 节点
   └─ task_initial, task_review, task_approval

2. 为每个任务确定表单模式和字段可见性
   └─ task_initial (初审):
      ├─ form_mode: "review"
      ├─ visible_fields: [申请人信息, 贷款信息]
      ├─ readonly_fields: [申请人信息] (初审员不能修改)
      ├─ editable_fields: [初审备注]
      └─ actions: [approve, reject, reassign]

   └─ task_approval (批准):
      ├─ form_mode: "approval"
      ├─ visible_fields: [申请人姓名, 金额, 初审结果, 复审结果]
      ├─ readonly_fields: [所有字段]
      ├─ editable_fields: [批准备注]
      └─ actions: [approve, reject]

3. 生成集成配置
   └─ 包含所有task_id → form_id的映射和字段配置

输出:
{
  "success": true,
  "content": {
    "integration_config": {
      "process_id": "loan_approval",
      "forms": [
        {
          "form_id": "form_loan_app",
          "bindings": [
            { "task_id": "task_initial", ... },
            ...
          ]
        }
      ]
    }
  }
}
```

### 5. 前端预览和确认阶段

```
ExecutionPanel 收到三步的结果:
├─ BPMN XML (Step 1)
├─ 表单Schema (Step 2)
└─ 集成配置 (Step 3)

    ↓

前端操作:
1. 在 BPMN-JS 编辑器中加载并显示流程图
2. 在 FormDesigner 中加载并显示表单
3. 显示流程-表单的关联关系

用户确认/修改:
- 可以在编辑器中微调流程
- 可以在编辑器中修改表单字段
- 预览结果

    ↓

用户点击 "保存到 Membership"

    ↓

前端调用后端 API:
POST /v1/workflows/save
{
  "process_definition": {
    "bpmn_xml": "...",
    "process_name": "贷款申请审批流程",
    "process_id": "loan_approval"
  },
  "forms": [
    {
      "form_schema": {...},
      "bindings": [...]
    }
  ]
}
```

### 6. Membership保存和执行阶段

```
后端 API (/v1/workflows/save):
1. 验证 BPMN XML 有效性
2. 验证表单 Schema 符合规范
3. 保存 BPMN 定义到 Membership
4. 保存表单定义到 Membership
5. 返回 process_definition_id 和 form_ids

    ↓

Membership 中的存储:
├─ ProcessDefinition 表:
│  ├─ id: "proc_def_123"
│  ├─ process_id: "loan_approval"
│  ├─ bpmn_xml: "<?xml...>"
│  ├─ status: "active"
│  └─ created_at: "2025-01-11"
│
└─ FormDefinition 表:
   ├─ id: "form_def_456"
   ├─ form_id: "form_loan_app"
   ├─ form_schema: {...}
   ├─ process_definition_id: "proc_def_123"
   └─ task_bindings: [...]

    ↓

Flowable 引擎执行:
用户启动流程 → Flowable 创建 ProcessInstance
    → 加载对应的表单 (根据task_bindings)
    → 显示表单给初审员
    → 初审员填写并提交
    → Flowable 根据审批结果流转
    → ...继续流程
```

---

## 数据流向图

```
需求文本
   │
   ├─→ BPMN-MCP.generate_bpmn
   │   └─→ LLM 理解流程需求
   │   └─→ 生成 BPMN XML
   │   └─→ 返回 BPMN XML + 元数据
   │
   ├─→ FORM-MCP.generate_form
   │   ├─ 输入: 表单需求 + BPMN XML (上下文)
   │   └─→ LLM 理解表单需求
   │   └─→ 生成 表单 Schema JSON
   │   └─→ 返回 表单 + 字段映射
   │
   └─→ FORM-MCP.bind_form_to_process
       ├─ 输入: 表单 Schema + BPMN XML + 绑定配置
       └─→ 分析任务节点和字段关联
       └─→ 生成集成配置
       └─→ 返回 完整的流程-表单集成定义

           ↓ (集成完成)

前端展示 (ExecutionPanel)
   ├─ 显示 BPMN 流程图 (BPMN-JS)
   ├─ 显示 表单设计 (FormDesigner)
   └─ 显示 任务-表单映射关系

           ↓ (用户确认)

后端保存 (POST /v1/workflows/save)
   └─→ 持久化到 Membership
   └─→ Flowable 准备执行
   └─→ 返回 process_id 和 form_ids

           ↓ (流程就绪)

实际执行
   └─→ 用户启动流程
   └─→ Flowable 执行并加载表单
   └─→ 人员填写表单并审批
   └─→ 流程根据结果流转
   └─→ 直到流程结束
```

---

## 错误处理和验证流程

```
┌─ 步骤 1: BPMN 生成
│  ├─ LLM 生成 BPMN XML
│  └─ validate_bpmn 验证
│     ├─ 检查 BPMN 2.0 规范合规性
│     ├─ 检查 Flowable 兼容性
│     ├─ 检查执行者配置完整性
│     └─ 如果失败 → 重试或返回错误
│
├─ 步骤 2: 表单生成
│  ├─ LLM 生成表单 Schema
│  └─ validate_form 验证
│     ├─ 检查 Schema 格式
│     ├─ 检查字段类型合法性
│     ├─ 检查验证规则正确性
│     └─ 如果失败 → 重试或返回错误
│
└─ 步骤 3: 绑定验证
   ├─ 检查所有 task_id 在 BPMN 中存在
   ├─ 检查所有 form_id 在表单中存在
   ├─ 检查字段映射的一致性
   ├─ 检查权限和可见性配置合理性
   └─ 如果失败 → 返回错误和建议修复方案
```

---

## 与 BPM 项目的关系

```
您的独立 BPM 项目:
┌─────────────────────────────────────┐
│  /bpm (独立编辑器)                   │
├─────────────────────────────────────┤
│  ├─ ProcessDesigner (BPMN-JS)       │
│  ├─ FormDesigner (你自建)           │
│  └─ AIAssistantPanel (辅助编辑)     │
└─────────────────────────────────────┘

       可选集成点:
       - 参考其BPMN-JS集成方式
       - 参考其表单规范 (复用到AICMDEngine的form-mcp)
       - 参考其AI助手架构

       ↓

AICMDEngine Phase 2:
┌─────────────────────────────────────┐
│  BPMN-MCP + FORM-MCP                │
├─────────────────────────────────────┤
│  ├─ 一次性自动生成 (vs 手工编辑)    │
│  ├─ 集成 Planning Engine            │
│  └─ 直接保存到 Membership           │
└─────────────────────────────────────┘

优势:
- BPMN 项目保持独立，可继续手工编辑
- AICMDEngine 新增自动生成能力
- 两者可共享 Flowable 执行引擎
```

