# Policy Workflow MCP 设计文档

**日期**: 2026-01-09
**状态**: 架构设计阶段
**优先级**: 高（建议Phase 2启动）
**预期价值**: 自动化合规流程，减少配置工作 80%+

---

## 📋 Executive Summary

### 核心能力
将**非结构化的政策文档**（规章制度、审批规范、Audit规定等）自动转换为**可执行的工作流**：

```
输入: "员工请假规定" / "资金审批规范" / "项目启动流程" / "审计规范"
  ↓ (自然语言理解 + 业务逻辑)
输出: BPMN流程 + Form表单 + 合规规则
  ↓ (立即可执行)
自动化审批工作流系统
```

### 关键特点
- ✅ **自动化**：政策文档直接转流程，无需手工配置
- ✅ **合规**：所有规则来自政策文档，可追溯
- ✅ **灵活**：政策更新时自动生成新版本流程
- ✅ **智能**：支持多轮对话澄清需求
- ✅ **完整**：BPMN + Form + 规则引擎完整输出

---

## 🎯 核心功能设计

### 1. 需求澄清对话（Multi-turn Requirement Elicitation）

**问题**：政策文档往往存在歧义，需要多轮对话确认

**解决方案**：MCP支持多轮对话模式

```python
async def clarify_policy_requirements(
    self,
    policy_document: str,
    policy_type: str,
    clarification_history: List[Dict] = None
) -> ToolResult:
    """
    多轮对话澄清政策需求

    支持Planning Engine和MCP之间的多轮对话：
    Turn 1: User/LLM 输入政策文档 → MCP生成初步理解
    Turn 2: MCP提出澄清问题 → User确认/修正
    Turn 3: MCP根据反馈重新分析 → 输出最终规则
    """

    # Step 1: 初步分析
    initial_analysis = await self._analyze_policy(
        policy_document,
        policy_type
    )

    # Step 2: 识别歧义并提出问题
    clarification_questions = await self._identify_ambiguities(
        initial_analysis,
        policy_document
    )

    # 如果有歧义，返回问题让用户确认
    if clarification_questions:
        return ToolResult(
            is_error=False,
            content="需要澄清以下问题",
            data={
                "status": "CLARIFICATION_NEEDED",
                "initial_analysis": initial_analysis,
                "questions": clarification_questions,
                "session_id": str(uuid.uuid4())
            }
        )

    # Step 3: 如果之前有澄清反馈，融合反馈
    if clarification_history:
        initial_analysis = await self._merge_clarifications(
            initial_analysis,
            clarification_history
        )

    return ToolResult(
        is_error=False,
        content="政策需求已确认",
        data={"status": "READY_FOR_GENERATION", "analysis": initial_analysis}
    )
```

**使用示例**：

```
Planning Engine: "我有一份请假规定，需要转成工作流"
     ↓ (发送政策文档)

MCP Turn 1: 初步分析，发现以下疑点：
  Q1: "经理审批超过1天自动升级到总监" - 这里的"总监"是指直属总监还是任何总监？
  Q2: "同一时间最多5人同时请假" - 这个限制是公司级还是部门级？
  Q3: "年假必须在当年年底前用完" - 那病假和事假呢？

Planning Engine: 提供澄清
  A1: 直属总监
  A2: 公司级限制
  A3: 病假和事假可以累积

MCP Turn 2: 根据澄清重新分析
  → 输出最终的BPMN + Form + 规则
```

### 2. 政策文档解析（Policy Analysis Engine）

```python
async def _analyze_policy(
    self,
    policy_document: str,
    policy_type: str,
    context: Dict = None
) -> dict:
    """
    用LLM深度理解政策文档

    输入可以是：
    - 规章制度文档 (请假规定、项目申请)
    - 审批规范 (资金审批、采购规范)
    - Audit规定 (审计流程、合规检查)
    - 公司政策 (数据安全、保密协议)
    """

    # 根据政策类型选择合适的分析模板
    analysis_template = self._get_template_for_type(policy_type)

    # 构建分析提示词
    prompt = self._build_detailed_analysis_prompt(
        policy_document,
        policy_type,
        analysis_template,
        context
    )

    # 调用LLM (需要强大的推理能力)
    response = await self.llm_manager.call_llm(
        prompt=prompt,
        provider="gpt-5",  # 必须用最强的模型
        temperature=0.1,   # 极低温度，需要精确性
        max_tokens=6000
    )

    analysis = json.loads(response)

    return {
        "workflow_name": analysis["workflow_name"],
        "workflow_description": analysis["workflow_description"],
        "policy_type": policy_type,

        # 关键要求提取
        "key_requirements": analysis["key_requirements"],

        # 审批流程层级
        "approval_hierarchy": analysis["approval_hierarchy"],
        # 示例:
        # [
        #   {"level": 1, "role": "部门经理", "condition": "金额 < 10K"},
        #   {"level": 2, "role": "总监", "condition": "10K <= 金额 < 100K"},
        #   {"level": 3, "role": "CFO", "condition": "金额 >= 100K"}
        # ]

        # 条件规则 (可执行的)
        "rules": analysis["rules"],
        # 示例:
        # [
        #   {"type": "time_limit", "parameter": "manager_approval_days", "value": 1},
        #   {"type": "amount_limit", "parameter": "single_approval_max", "value": 10000},
        #   {"type": "concurrent_limit", "parameter": "max_concurrent", "value": 5},
        #   {"type": "quota_limit", "parameter": "annual_quota", "value": 10}
        # ]

        # 表单需求
        "form_definitions": analysis["form_definitions"],

        # 时间限制和升级规则
        "time_limits": analysis["time_limits"],
        "escalation_rules": analysis["escalation_rules"],

        # 特殊规定和例外
        "special_cases": analysis["special_cases"],

        # 潜在的歧义或问题
        "ambiguities": analysis.get("ambiguities", []),
        "risks": analysis.get("risks", [])
    }
```

### 3. 提示词工程（Prompt Engineering for Policies）

```python
def _build_detailed_analysis_prompt(
    self,
    policy_document: str,
    policy_type: str,
    template: dict,
    context: dict = None
) -> str:
    """
    根据政策类型构建精准的分析提示词
    这是核心！决定理解准确性
    """

    # 获取政策类型的特定指导
    policy_guides = {
        "leave": """
你是人力资源和流程专家。分析这份请假规定：
- 识别所有假期类型和规则
- 提取审批层级和条件
- 找出时间限制和升级规则
- 识别特殊情况（如法定假期、特殊假期）
        """,

        "budget": """
你是财务和合规专家。分析这份资金审批规范：
- 按金额识别审批层级
- 提取预算限制和权限
- 识别所需文档和证明
- 找出财务合规要求
        """,

        "project": """
你是项目管理和治理专家。分析这份项目申请规定：
- 按项目大小分类
- 提取每个阶段的审批流程
- 识别所需的文档和评估
- 找出资源分配规则
        """,

        "audit": """
你是审计和合规专家。分析这份审计规定：
- 识别审计周期和范围
- 提取审计步骤和检查点
- 找出证据要求和文档
- 识别整改跟踪流程
        """
    }

    guide = policy_guides.get(policy_type, "")

    prompt = f"""
{guide}

政策文档：
{policy_document}

请返回以下JSON格式的详细分析：

{{
  "workflow_name": "流程名称",
  "workflow_description": "详细描述（2-3句话）",
  "policy_type": "{policy_type}",

  "key_requirements": [
    "关键要求1",
    "关键要求2",
    "..."
  ],

  "approval_hierarchy": [
    {{
      "level": 1,
      "role": "审批人角色",
      "condition": "触发此级别的条件",
      "approval_days": "审批期限（天数）",
      "required_documents": ["文档1", "文档2"],
      "approval_authority": "审批权限说明"
    }}
  ],

  "rules": [
    {{
      "rule_id": "rule_001",
      "name": "规则名称",
      "type": "time_limit|amount_limit|quota_limit|concurrent_limit|role_based|other",
      "parameter": "参数名",
      "value": "参数值",
      "description": "规则描述",
      "enforcement": "hard|soft",  // hard=必须遵守，soft=建议
      "triggered_by": "由什么事件触发"
    }}
  ],

  "form_definitions": [
    {{
      "form_name": "表单名",
      "trigger_node": "在哪个节点显示",
      "trigger_condition": "触发条件",
      "fields": [
        {{
          "name": "字段名",
          "label": "显示标签",
          "type": "text|number|date|select|textarea|file|checkbox",
          "required": true|false,
          "required_when": "条件（可选）",
          "options": ["选项1", "选项2"],  // select类型需要
          "validation": "验证规则",
          "placeholder": "提示文本",
          "help": "帮助文本"
        }}
      ]
    }}
  ],

  "time_limits": {{
    "manager_approval": "1 day",
    "director_approval": "2 days",
    "ceo_approval": "3 days",
    "overall_process": "10 days"
  }},

  "escalation_rules": [
    {{
      "trigger": "事件触发条件",
      "action": "执行的操作",
      "escalate_to": "升级到的角色",
      "notification": "发送通知方式"
    }}
  ],

  "special_cases": [
    {{
      "case_name": "特殊情况名",
      "condition": "触发条件",
      "handling": "如何处理",
      "approver": "谁来审批"
    }}
  ],

  "ambiguities": [
    "可能的歧义1",
    "可能的歧义2"
  ],

  "risks": [
    {{
      "risk": "风险描述",
      "impact": "影响",
      "mitigation": "缓解方案"
    }}
  ]
}}

重点注意：
1. 必须提取每一个审批层级的精确条件
2. 规则必须是可执行的（有具体参数值）
3. 时间限制必须明确（具体天数或时间）
4. 列出所有歧义，不要猜测
5. 特殊情况是重点，不要遗漏
"""

    return prompt
```

### 4. 歧义识别和澄清

```python
async def _identify_ambiguities(
    self,
    analysis: dict,
    policy_document: str
) -> List[Dict]:
    """
    识别政策中的歧义并生成澄清问题
    """

    questions = []

    # 检查所有歧义
    for ambiguity in analysis.get("ambiguities", []):
        question = {
            "id": f"q_{len(questions) + 1}",
            "ambiguity": ambiguity,
            "question": await self._generate_clarification_question(
                ambiguity,
                policy_document,
                analysis
            ),
            "context": "上下文信息用来帮助用户理解"
        }
        questions.append(question)

    # 检查可能的逻辑矛盾
    contradictions = await self._check_logical_consistency(analysis)
    for contradiction in contradictions:
        questions.append({
            "id": f"q_{len(questions) + 1}",
            "type": "contradiction",
            "issue": contradiction["issue"],
            "question": contradiction["question"]
        })

    return questions

async def _generate_clarification_question(
    self,
    ambiguity: str,
    policy_document: str,
    analysis: dict
) -> str:
    """
    用LLM生成清晰的澄清问题
    """

    prompt = f"""
政策文档中存在以下歧义："{ambiguity}"

基于政策上下文，生成一个清晰、简洁的澄清问题，
用户可以直接回答。

示例：
- 歧义："经理审批" → 问题："这里的经理是指直属经理还是部门经理？"
- 歧义："超期自动升级" → 问题："升级到谁？是否发送通知？"

请生成问题（单句，不超过20个字）：
"""

    response = await self.llm_manager.call_llm(
        prompt=prompt,
        provider="deepseek-v3.2",  # 节省成本
        temperature=0.3
    )

    return response.strip()

async def _merge_clarifications(
    self,
    initial_analysis: dict,
    clarification_responses: List[Dict]
) -> dict:
    """
    将用户的澄清反馈融合到分析中
    """

    # 根据澄清响应修正分析
    refined_analysis = deepcopy(initial_analysis)

    for response in clarification_responses:
        question_id = response["question_id"]
        answer = response["answer"]

        # 根据答案更新相关规则
        await self._update_analysis_with_answer(
            refined_analysis,
            question_id,
            answer
        )

    return refined_analysis
```

### 5. BPMN生成（Policy-aware BPMN Generation）

```python
async def _generate_workflow_bpmn(
    self,
    analysis: dict,
    rules: dict
) -> str:
    """
    根据政策分析生成BPMN流程
    特点：自动生成条件分支、并行网关等
    """

    bpmn = BPMNBuilder(workflow_name=analysis["workflow_name"])

    # 开始节点
    bpmn.add_start_event("Start", "流程开始")

    # 提交申请节点（通用）
    bpmn.add_user_task(
        "SubmitRequest",
        "提交申请",
        assignee="requester"
    )

    # 根据规则生成条件判断点
    # 例如：按金额判断审批层级
    conditions = self._extract_conditional_logic(analysis)

    if conditions:
        # 添加条件判断网关
        gateway_id = "ConditionGateway"
        bpmn.add_exclusive_gateway(
            gateway_id,
            "判断审批条件"
        )
        bpmn.add_sequence_flow("SubmitRequest", gateway_id)

        # 为每个条件创建分支
        for condition in conditions:
            branch_start = f"Branch_{condition['name']}"
            bpmn.add_user_task(
                branch_start,
                f"审批：{condition['name']}",
                assignee=condition["approver"]
            )

            bpmn.add_sequence_flow(
                gateway_id,
                branch_start,
                condition=condition.get("condition_expression")
            )

            # 在分支中添加审批层级
            for level in condition.get("approval_levels", []):
                task_id = f"{condition['name']}_L{level['level']}"
                bpmn.add_user_task(
                    task_id,
                    f"{level['role']} 审批",
                    assignee=self._get_role_expression(level['role'])
                )

                # 添加时间限制事件监听器
                if level.get("approval_days"):
                    bpmn.add_timer_event(
                        f"Timer_{task_id}",
                        duration=f"P{level['approval_days']}D",  // BPMN ISO 8601
                        task_id=task_id
                    )

                    # 超时后升级规则
                    escalation = self._find_escalation_rule(level)
                    if escalation:
                        bpmn.add_boundary_event(
                            f"Escalation_{task_id}",
                            type="escalation",
                            action=escalation["action"]
                        )
    else:
        # 简单流程：直接添加审批
        for level in analysis.get("approval_hierarchy", []):
            task_id = f"Approval_L{level['level']}"
            bpmn.add_user_task(
                task_id,
                f"{level['role']} 审批",
                assignee=self._get_role_expression(level['role'])
            )

    # 结束节点
    bpmn.add_end_event("Approved", "已批准")
    bpmn.add_end_event("Rejected", "已驳回")

    return bpmn.to_xml()
```

### 6. 规则引擎配置

```python
async def _generate_compliance_config(
    self,
    analysis: dict,
    rules: dict
) -> dict:
    """
    生成可执行的合规规则配置
    """

    config = {
        "policy_type": analysis["policy_type"],
        "workflow_name": analysis["workflow_name"],

        # 审批规则
        "approval_rules": self._compile_approval_rules(analysis),

        # 验证规则
        "validation_rules": self._compile_validation_rules(analysis),

        # 业务规则（配额、限制等）
        "business_rules": self._compile_business_rules(analysis),

        # 时间规则
        "time_rules": self._compile_time_rules(analysis),

        # 升级规则
        "escalation_rules": self._compile_escalation_rules(analysis),

        # 审计和合规
        "audit_trail": {
            "enabled": True,
            "log_all_actions": True,
            "retention_days": 2555,  # 7年
            "required_fields": [
                "requester_id",
                "request_time",
                "approval_action",
                "approver_id",
                "approval_time",
                "reason_if_rejected"
            ]
        },

        # 通知规则
        "notification_rules": self._compile_notification_rules(analysis),

        # 版本信息
        "version": "1.0",
        "created_at": datetime.utcnow().isoformat(),
        "policy_source": "policy_document"
    }

    return config

def _compile_approval_rules(self, analysis: dict) -> List[Dict]:
    """
    将政策中的审批层级编译为可执行规则
    """
    rules = []

    for level in analysis.get("approval_hierarchy", []):
        rule = {
            "level": level["level"],
            "role": level["role"],
            "condition": level.get("condition"),
            "approval_deadline": f"{level.get('approval_days', 1)} days",
            "required_documents": level.get("required_documents", []),
            "can_delegate": level.get("can_delegate", True),
            "can_parallel_approve": level.get("can_parallel_approve", False),
            "escalation_target": self._find_escalation_target(level)
        }
        rules.append(rule)

    return rules

def _compile_validation_rules(self, analysis: dict) -> List[Dict]:
    """
    编译验证规则（检查字段有效性）
    """
    rules = []

    for form in analysis.get("form_definitions", []):
        for field in form.get("fields", []):
            if field.get("validation"):
                rules.append({
                    "field": field["name"],
                    "type": field["type"],
                    "rule": field["validation"],
                    "error_message": f"{field['label']} 不符合要求"
                })

    return rules

def _compile_business_rules(self, analysis: dict) -> List[Dict]:
    """
    编译业务规则（配额、并发限制等）
    """
    rules = []

    for rule in analysis.get("rules", []):
        if rule["type"] in ["quota_limit", "concurrent_limit", "amount_limit"]:
            rules.append({
                "name": rule["parameter"],
                "type": rule["type"],
                "value": rule["value"],
                "unit": rule.get("unit", ""),
                "enforcement": rule.get("enforcement", "hard")
            })

    return rules
```

---

## 📊 政策类型支持矩阵

### 支持的政策类型

| 类型 | 示例 | 关键要素 | 复杂度 |
|------|------|--------|-------|
| **Leave** | 请假规定 | 假期类型、审批级别、时间限制 | 中 |
| **Budget** | 资金审批规范 | 金额分级、权限、文档要求 | 高 |
| **Project** | 项目申请规定 | 项目大小分类、审批流程 | 高 |
| **Procurement** | 采购规范 | 采购金额、招标要求 | 高 |
| **Audit** | 审计规定 | 审计周期、检查清单 | 中 |
| **Compliance** | 合规规范 | 合规检查、举证要求 | 高 |
| **Data Security** | 数据安全规定 | 数据分类、访问控制 | 中 |
| **HR Policy** | 人力资源规范 | 招聘流程、晋升规范 | 高 |

### 每个类型的分析模板

```python
POLICY_TEMPLATES = {
    "leave": {
        "key_fields": ["leave_types", "approval_levels", "time_limits", "quotas"],
        "required_extractions": ["假期类型", "审批人", "期限", "配额"],
        "validation_rules": ["date_validation", "quota_check", "concurrent_limit"],
        "analysis_prompts": "..."
    },
    "budget": {
        "key_fields": ["amount_tiers", "approval_matrix", "required_docs", "authorities"],
        "required_extractions": ["金额范围", "审批人", "文档", "权限"],
        "validation_rules": ["amount_validation", "budget_check", "authority_check"],
        "analysis_prompts": "..."
    },
    # ... 其他类型
}
```

---

## 🔄 工作流程示例：完整案例

### 案例：资金审批规范

#### Input: 政策文档

```markdown
# 公司资金使用审批规范 v2026

## 第一章 总则

### 1.1 适用范围
本规范适用于公司内所有资金支出审批，包括但不限于：
- 日常运营费用
- 项目投资
- 员工报销
- 设备采购

### 1.2 审批权限矩阵

#### 金额 < 10,000元
- 提交人：部门员工
- 初审人：部门经理
- 审批人：部门总监（如> 5000元）
- 审批期限：3个工作日
- 所需文档：
  - 支出申请单
  - 相关发票/报价单

#### 金额 10,000 - 100,000元
- 第一级：部门总监（3个工作日）
- 第二级：财务总监（2个工作日）
- 所需文档：
  - 支出申请单
  - 发票/报价单
  - 商业理由说明
  - 预算批准文件

#### 金额 100,000 - 1,000,000元
- 第一级：财务总监（2个工作日）
- 第二级：CFO（3个工作日）
- 所需文档：
  - 完整的商业分析报告
  - 供应商比价分析
  - 预算审批文件
  - 合同（如有）

#### 金额 > 1,000,000元
- 第一级：CFO（3个工作日）
- 第二级：CEO（5个工作日）
- 第三级：董事会（7个工作日）
- 所需文档：
  - 详细的投资分析报告
  - 风险评估
  - 多家供应商报价
  - 法律审查（如涉及合同）
  - 董事会提案

### 1.3 特殊规定

#### 1.3.1 紧急支出
如需在24小时内完成审批，可申请紧急程序：
- 需要上级领导（CFO以上）书面授权
- 审批期限：4小时
- 需要事后补充文档

#### 1.3.2 重复审批规则
- 相同供应商、相同项目：如上次批准距今< 30天，可简化为一级审批
- 同一项目多笔支出：第一笔需完整审批，后续可简化

#### 1.3.3 超期处理
- 经理超过期限未审批：自动升级到总监
- 总监超过期限未审批：自动升级到CFO
- CFO超过期限未审批：自动升级到CEO

### 1.4 财务合规检查
- 所有支出必须在当年预算内
- 采购金额 > 50,000需要询价招标
- 涉及外汇需要法律审查

### 1.5 审计要求
- 所有审批记录保留7年
- 必须记录：提交人、提交时间、审批人、审批时间、审批意见
```

#### Process: MCP处理

```
Step 1: 初步分析 (gpt-5, temperature=0.1)
  ↓ 提取关键信息：
    - 4个金额分级
    - 多个审批层级
    - 特殊规定和例外
    - 合规要求

Step 2: 识别歧义 (gpt-5)
  Q1: "部门总监（如> 5000元）" - 这是否意味着≤5000元时只需经理审批？
  Q2: "相同供应商、相同项目：距今< 30天" - 这个规则只适用于<10000金额吗？
  Q3: "采购金额 > 50,000需要询价招标" - 这是招标程序的替代，还是额外要求？

Step 3: Planning Engine回答问题
  A1: 是的，≤5000元只需部门经理审批
  A2: 这个规则对所有金额适用
  A3: 这是额外要求，与审批并行进行

Step 4: 融合澄清，生成最终规则
  ↓ 构建审批矩阵：

    Amount Range    | Level 1        | Level 2         | Level 3  | Level 4
    <= 5K          | Manager        | (end)           | -        | -
    5K - 10K       | Manager        | Director        | (end)    | -
    10K - 100K     | Director       | Finance Dir     | (end)    | -
    100K - 1M      | Finance Dir    | CFO             | (end)    | -
    > 1M           | CFO            | CEO             | Board    | (end)

Step 5: 生成BPMN
  ↓ 自动生成包含：
    - 开始：提交申请
    - 条件网关：根据金额判断
    - 并行网关：采购审批与资金审批并行
    - 多个审批节点
    - 超时升级处理
    - 结束：批准/驳回

Step 6: 生成表单
  ↓ 提交表单：
    {
      "fields": [
        {"name": "amount", "type": "number", "label": "支出金额"},
        {"name": "vendor", "type": "text", "label": "供应商"},
        {"name": "category", "type": "select", "label": "支出类别"},
        {"name": "purpose", "type": "textarea", "label": "业务用途"},
        {"name": "budget_code", "type": "text", "label": "预算代码"}
      ]
    }

  ↓ 不同审批人的审批表单（动态生成）

Step 7: 生成合规规则
  ↓ 可执行的规则配置：
    {
      "approval_rules": [
        {
          "level": 1,
          "amount_range": [0, 5000],
          "role": "department_manager",
          "approval_deadline": "3 days",
          "escalation_to": "director"
        },
        ...
      ],
      "business_rules": [
        {
          "name": "budget_check",
          "type": "budget_limit",
          "logic": "total_amount <= annual_budget[category]"
        },
        {
          "name": "same_vendor_rule",
          "type": "history_check",
          "logic": "days_since_last_approval(vendor) < 30 ? skip_level_2 : normal"
        },
        {
          "name": "procurement_check",
          "type": "procurement_required",
          "logic": "amount > 50000 ? require_bidding : skip"
        }
      ],
      "escalation_rules": [
        {
          "trigger": "approval_timeout",
          "escalate_from": "manager",
          "escalate_to": "director"
        }
      ]
    }
```

#### Output: 完整的工作流系统

```json
{
  "workflow_id": "wf_budget_2026_v1",
  "bpmn_xml": "<?xml version='1.0'...>",
  "form_definitions": {
    "budget_request_form": {...},
    "level1_approval_form": {...},
    "level2_approval_form": {...},
    "level3_approval_form": {...}
  },
  "compliance_config": {
    "approval_rules": [...],
    "business_rules": [...],
    "validation_rules": [...],
    "escalation_rules": [...],
    "audit_trail": {...}
  },
  "policy_analysis": {
    "workflow_name": "资金支出审批流程",
    "key_requirements": [...],
    "special_cases": [...],
    "risks": [...]
  },
  "metadata": {
    "policy_document_url": "minio://policies/budget/2026/policy.md",
    "created_at": "2026-01-09T...",
    "version": "1.0",
    "source": "company_policy_2026"
  }
}
```

---

## 🔑 关键成功因素

### 1. **提示词工程** - 最关键
- 不同政策类型需要不同的分析指导
- 必须明确提取"可执行"的规则（有具体数值）
- 必须识别所有歧义而不是猜测

### 2. **多轮对话支持**
- 澄清歧义是必需的，不能跳过
- 用户的回答必须融合到规则中

### 3. **规则可执行性检查**
- 生成的规则必须能在运行时判断
- 不能有模糊的条件（如"合理范围"）

### 4. **政策版本管理**
- 政策更新时自动生成新版本工作流
- 历史版本可追溯（7年审计期）

### 5. **特殊情况处理**
- 企业政策总有例外和特例
- 必须全面识别和处理

---

## 🏗️ 架构集成

### 与MCP框架集成

```
┌────────────────────────────────┐
│  Planning Engine               │
│  (需要自动化工作流)             │
└──────────────┬─────────────────┘
               │
       ┌───────▼────────┐
       │ Policy Workflow│
       │ MCP Server     │
       └───────┬────────┘
               │
      ┌────────┼──────────┬──────────┐
      ▼        ▼          ▼          ▼
   MongoDB   MinIO      LLM      Flowable
   (规则)   (文档)    (理解)    (执行)
```

### 数据存储

```
MongoDB:
├── policy_workflows (工作流配置)
│   ├── workflow_id
│   ├── policy_type
│   ├── bpmn_xml
│   ├── form_definitions
│   ├── compliance_rules
│   └── audit_trail_config
│
├── policy_documents (政策文档版本)
│   ├── policy_id
│   ├── version
│   ├── original_content
│   ├── analysis
│   └── approval_status
│
└── workflow_executions (执行实例)
    ├── execution_id
    ├── workflow_id
    ├── requester
    ├── status
    ├── audit_log
    └── completion_time

MinIO:
├── policies/ (原始政策文档)
│   ├── leave/2026/policy.md
│   ├── budget/2026/policy.md
│   └── ...
│
├── workflows/ (生成的BPMN)
│   ├── leave_approval.bpmn.xml
│   └── ...
│
└── templates/ (政策模板库)
    ├── leave_template.md
    ├── budget_template.md
    └── ...
```

---

## 📈 实施路线图

### Phase 2 (Week 2-3)

```
Week 2:
  Day 1-2:
    - 完成PolicyWorkflowMCP核心框架
    - 实现policy analysis引擎
    - 建立提示词模板

  Day 3-4:
    - 实现多轮对话澄清
    - 歧义检测

  Day 5:
    - BPMN生成
    - Form生成

Week 3:
  Day 1-2:
    - 规则引擎配置
    - 测试

  Day 3-4:
    - 集成Flowable执行
    - 审计追踪

  Day 5:
    - 完整集成测试
    - 性能优化
```

### Phase 3+ 增强

```
增强功能：
- 政策模板库（减少LLM调用）
- 跨政策规则合并（多个政策同时生效时）
- 自适应优化（基于execution历史）
- 更多政策类型支持
```

---

## ⚠️ 注意事项

### 风险和缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| LLM误解政策 | 规则错误 | 强制多轮澄清，必须确认 |
| 政策过于模糊 | 无法转换 | 返回错误提示，要求用户澄清 |
| 特殊情况遗漏 | 流程不完整 | 主动询问"是否有例外情况" |
| 合规问题 | 违规风险 | 内建审计追踪，7年保留 |

---

**下一步**：你希望我详细设计：
1. ✅ 完整的提示词库（针对各类政策）？
2. ✅ 规则引擎实现（如何在运行时执行规则）？
3. ✅ 多轮对话流程（如何管理对话状态）？
4. ✅ 政策模板库（如何建立可重用的模板）？