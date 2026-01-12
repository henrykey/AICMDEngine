# Phase 2：完整的工作流生成和执行架构

> 版本：2025-01-11
> 状态：架构设计阶段
> 核心认知：AICMDEngine 的 BPMN-MCP + FORM-MCP 不是孤立的，而是与 Membership 企业级知识库和权限系统的完美融合

---

## 一、战略地位

### 1.1 Membership 的真实角色

**Membership 不仅仅是身份管理系统，它是企业级的基础设施层，包括**：

```
Membership 架构层次:
├─ 身份层 (Authentication)
│  ├─ LDAP / OAuth / JWT
│  ├─ 多因子认证 (OTP)
│  └─ Token 生命周期管理
│
├─ 权限层 (Authorization)
│  ├─ RBAC + 位图掩码
│  ├─ 资源和动作绑定
│  └─ 租户隔离 (RLS)
│
├─ 组织结构层 (Hierarchy)
│  ├─ 闭包表 (Closure Table) 存储
│  ├─ 组织树 + 岗位体系
│  └─ 存储过程优化查询
│
├─ 知识库层 (Knowledge Base) ⭐ 关键
│  ├─ MongoDB 存储文档 (政策/指南/规范)
│  ├─ ElasticSearch 全文检索
│  ├─ Milvus 向量存储 (语义搜索)
│  └─ 支持 RAG (检索增强生成)
│
├─ 数据流层 (Data Streaming)
│  ├─ Kafka 事件总线
│  ├─ Debezium CDC (变更数据捕获)
│  ├─ 实时审计链路
│  └─ 异步事件处理
│
├─ 缓存层 (Performance)
│  ├─ Redis 权限位图缓存
│  ├─ JWT 令牌缓存
│  └─ 组织树缓存
│
└─ 审计层 (Compliance)
   ├─ audit_outbox 表
   ├─ Kafka → MongoDB
   ├─ 完整操作链路
   └─ 合规追踪
```

### 1.2 AICMDEngine 的角色

**AICMDEngine 是 AI 驱动的流程生成和执行引擎**：

```
AICMDEngine 层次:
├─ 前端 (Design Time)
│  ├─ ProcessDesigner: 流程可视化编辑
│  ├─ FormDesigner: 表单定义和配置
│  └─ WebApp: 用户任务执行界面
│
├─ MCP 层 (Generation)
│  ├─ BPMN-MCP: 自然语言 → BPMN XML
│  ├─ FORM-MCP: 自然语言 → 表单定义
│  ├─ 业务规则 MCP: 动态分配逻辑
│  └─ 其他专业 MCP: 合规/财务/质量等检查
│
├─ 执行引擎 (Runtime)
│  ├─ WorkflowEngine: 流程协调
│  ├─ TaskHandler: 任务处理器
│  ├─ MCPExecutor: MCP 调用器
│  └─ VariableMapper: 数据映射
│
└─ 集成层 (Integration)
   ├─ 与 Membership 的 5 层集成
   ├─ 与知识库的查询和检索
   ├─ 与 Flowable 的深度融合
   └─ 与 WebApp 的 UI 同步
```

---

## 二、核心创新：5层执行者模式

### 2.1 五种执行者配置方式

| # | 模式 | 执行者 | 触发方式 | 用例 | 配置位置 |
|---|------|------|--------|------|--------|
| 1 | **静态配置** | 部门/角色/个人 | 流程启动 | "初审由风险部门处理" | BPMN设计时 |
| 2 | **表单驱动** | 用户指定 | 表单提交 | "谁审核架构由提交人选" | 表单字段 |
| 3 | **动态多路** | 基于数据分析 | MCP 分析 | "架构和UI各分配给专家" | 后端逻辑 |
| 4 | **角色队列认领** | 竞争认领 | 用户主动 | "5个出纳先到先得" | BPMN角色组 |
| 5 | **MCP自动化** | 虚拟成员 | 系统自动 | "AI审核数据合规性" | ServiceTask |

### 2.2 多模式组合示例：新药申报流程

```yaml
新药申报流程:

第一阶段:
  提交申请资料
    └─ 执行者: 申请人 (static)

  文件完整性检查
    └─ 执行者: MCP自动化 (方式5)
       MCP: document_validation
       时间: 2小时
       失败处理: 自动补充通知

第二阶段:
  技术部初审 (15人可选)
    └─ 执行者: 角色队列认领 (方式4)
       Candidates: all "senior_reviewer" role members
       时间: 10-15天

  如有重大缺陷
    └─ 执行者: 专家研讨会 (方式3)
       路由1: 内部专家 (architect + clinical director + statistician)
       路由2: 外部专家 (3-5 invited)
       并行处理，所有人意见汇总

第三阶段:
  4个合规检查 (并行)
    ├─ 伦理合规审查
    │   └─ 执行者: MCP自动化 (方式5)
    │      工具: validate_ethics_report
    │      查询知识库: 伦理审查标准
    │      时间: 1小时
    │
    ├─ 统计学合规审查
    │   └─ 执行者: MCP自动化 (方式5)
    │      查询知识库: 统计学方法指南
    │      时间: 2小时
    │
    ├─ 法律文件合规审查
    │   └─ 执行者: MCP自动化 (方式5)
    │      查询知识库: 法律合规清单
    │      时间: 1小时
    │
    └─ 安全性数据库审查
        ├─ 第一步: MCP自动化 (方式5)
        │  工具: validate_safety_database
        │  查询知识库: 安全性评估标准
        │
        └─ 第二步: 如有风险信号
           执行者: 角色队列 (方式4)
           Candidates: all "Drug Safety Officer" role
           决策: 是否继续推进

第四阶段:
  NMPA预审会议申请
    └─ 执行者: 静态 (方式1)
       指定: 监管部部长

  NMPA会议
    └─ 执行者: 表单驱动 (方式2)
       由部长在表单中选择外部专家参与

  根据反馈修改
    └─ 执行者: 表单驱动 (方式2)
       由NMPA反馈自动生成修改任务
       可能循环多次

... (更多阶段)
```

---

## 三、MCP 与 Membership 知识库的集成

### 3.1 MCP 查询知识库的机制

**每个 MCP 可以调用 Membership 的知识库接口来获取政策、指南、规范等信息**：

```python
# MCP 内部：医学伦理合规检查
class EthicsComplianceMCP:

    def validate_ethics_report(self, requirement, ethics_doc):
        """
        MCP Tool: validate_ethics_report

        1. 从 Membership 知识库查询"伦理审查标准"
        2. 检查文档是否符合标准
        3. 返回验证结果
        """

        # 第一步：查询知识库
        ethics_standards = self.membership.query_knowledge_base(
            query="伦理审查标准 ICH GCP指南",
            filters={
                "doc_type": "guideline",
                "category": "ethics",
                "version": "latest"
            },
            search_type="semantic"  # 使用向量搜索
        )

        # 返回:
        # [
        #   {
        #     "id": "doc_123",
        #     "title": "ICH GCP指南 2024版",
        #     "content": "知情同意书应包括...",
        #     "relevance": 0.95
        #   },
        #   {
        #     "id": "doc_124",
        #     "title": "公司伦理审查流程 v3.2",
        #     "content": "伦理委员会应在30天内完成审查...",
        #     "relevance": 0.87
        #   }
        # ]

        # 第二步：从知识库提取检查清单
        checklist = self.extract_checklist_from_docs(ethics_standards)
        # 结果:
        # {
        #   "informed_consent": "ICH GCP §1.28 - 必须包含...",
        #   "subject_protection": "指南 §2.3 - 应说明...",
        #   "adverse_events": "公司流程 §4.1 - 报告机制...",
        #   ...
        # }

        # 第三步：逐项检查文档
        validation_results = {}
        for check_item, standard in checklist.items():
            result = self.check_item(ethics_doc, check_item, standard)
            validation_results[check_item] = result

        # 第四步：生成报告
        return {
            "status": "passed" if all_passed else "rejected",
            "findings": validation_results,
            "referenced_standards": [doc["id"] for doc in ethics_standards],
            "audit_trail": {
                "checked_at": now(),
                "checked_by": "ethics_compliance_mcp_v1.0",
                "knowledge_base_version": "2025-01-11"
            }
        }
```

### 3.2 知识库的内容类型

```
Membership 知识库中存储的企业知识:

1. 政策文件 (Policy Documents)
   ├─ 新药申报政策
   ├─ 财务报销政策
   ├─ 采购流程政策
   ├─ 合同管理政策
   └─ HR 招聘政策

2. 监管指南 (Regulatory Guidelines)
   ├─ NMPA 指南
   ├─ ICH GCP 指南
   ├─ FDA 指南
   └─ 国际标准 (ISO, etc)

3. 内部流程标准 (Process Standards)
   ├─ 审批权限表
   ├─ SOP (Standard Operating Procedure)
   ├─ 检查清单
   └─ 决策矩阵

4. 案例库 (Case Library)
   ├─ 历史申报案例
   ├─ 常见问题 (FAQ)
   ├─ 最佳实践
   └─ 失败案例分析

5. 组织信息 (Organization Data)
   ├─ 部门权限映射
   ├─ 人员能力认证
   ├─ 外部专家库
   └─ 供应商评分

6. 实时数据 (Real-time Data)
   ├─ 项目进度跟踪
   ├─ 成本统计
   ├─ 工作量分布
   └─ 风险指标
```

### 3.3 查询知识库的三种方式

```python
# 方式1: 关键词搜索 (ElasticSearch)
results = membership.search_knowledge_base(
    query="财务报销 出差 补贴 标准",
    fields=["title", "content", "tags"],
    limit=10
)

# 方式2: 语义搜索 (Milvus 向量)
results = membership.semantic_search(
    query="新药审批的财务风险评估",
    threshold=0.8,
    top_k=5
)

# 方式3: 结构化查询 (MongoDB)
results = membership.query_structured(
    filters={
        "doc_type": "policy",
        "applies_to_org": ["org_123", "org_456"],
        "effective_date": {"$lte": "2025-01-11"},
        "status": "active"
    },
    sort={"updated_at": -1}
)
```

---

## 四、完整的工作流执行链路

### 4.1 从自然语言到执行的全过程

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. 用户输入: "创建新药申报流程，遵守NMPA规范"                   │
└────────────────┬──────────────────────────────────────────────────┘
                 ↓
┌──────────────────────────────────────────────────────────────────┐
│ 2. BPMN-MCP 处理                                                 │
│ ├─ 理解需求: 新药申报 + NMPA 合规                              │
│ ├─ 查询知识库: Membership 中"NMPA流程标准"文档                 │
│ │  (通过语义搜索找到相关的监管指南)                             │
│ ├─ 生成BPMN XML:                                                 │
│ │  ├─ 任务节点 (50+个)                                          │
│ │  ├─ 决策分支 (25+个)                                          │
│ │  ├─ 执行者标记:                                               │
│ │  │  ├─ 某些任务标记为 "static:role_监管部"                  │
│ │  │  ├─ 某些任务标记为 "mcp:ethics_compliance"                │
│ │  │  ├─ 某些任务标记为 "queue:role_senior_reviewer"           │
│ │  │  └─ 某些任务标记为 "form_driven:field_external_expert"   │
│ │  └─ 调用 Membership API 以验证角色是否存在                   │
│ └─ 输出: BPMN XML (带所有元数据)                                │
└────────────────┬──────────────────────────────────────────────────┘
                 ↓
┌──────────────────────────────────────────────────────────────────┐
│ 3. FORM-MCP 处理                                                 │
│ ├─ 基于BPMN理解表单需求                                         │
│ ├─ 为每个表单任务生成表单定义                                   │
│ ├─ 查询知识库:                                                   │
│ │  ├─ "新药申报 所需文档清单" → 生成字段                       │
│ │  ├─ "财务报销表单 必填字段" → 生成财务模块                   │
│ │  └─ "伦理审查 信息需求" → 生成伦理审查表单                   │
│ └─ 输出: 表单定义 (包含权限、可见性规则)                        │
└────────────────┬──────────────────────────────────────────────────┘
                 ↓
┌──────────────────────────────────────────────────────────────────┐
│ 4. 前端编辑 (ProcessDesigner + FormDesigner)                     │
│ ├─ 用户查看生成的 BPMN XML                                       │
│ ├─ 可选: 微调流程结构                                           │
│ ├─ 用户查看生成的表单定义                                       │
│ ├─ 可选: 调整字段、权限、验证规则                               │
│ └─ 用户确认: "保存"                                              │
└────────────────┬──────────────────────────────────────────────────┘
                 ↓
┌──────────────────────────────────────────────────────────────────┐
│ 5. 保存到 Membership                                            │
│ ├─ 保存 BPMN XML 到 Membership 文档库                            │
│ ├─ 保存 表单定义 到 Membership                                   │
│ ├─ 保存 执行者配置 (角色、权限映射)                             │
│ ├─ Membership 审计: 记录"流程定义创建"                          │
│ └─ 返回: Process ID, Version, Signature                          │
└────────────────┬──────────────────────────────────────────────────┘
                 ↓
                 ↓ [运行时开始]
                 ↓
┌──────────────────────────────────────────────────────────────────┐
│ 6. 用户启动流程: "提交新药申报"                                  │
│ └─ AICMDEngine WorkflowController 接收请求                       │
│    POST /v1/workflows/start                                      │
│    {                                                             │
│      "process_id": "drug_approval_v1",                          │
│      "form_data": {...}                                         │
│    }                                                             │
└────────────────┬──────────────────────────────────────────────────┘
                 ↓
┌──────────────────────────────────────────────────────────────────┐
│ 7. WorkflowEngine 初始化                                         │
│ ├─ 从 Membership 加载 BPMN XML                                   │
│ ├─ 从 Membership 加载 表单定义                                   │
│ ├─ 创建 Flowable ProcessInstance                                 │
│ ├─ 设置流程变量: formData, initiator, timestamp, etc             │
│ ├─ 记录操作到 Membership 审计: "流程启动"                        │
│ └─ 推进流程到第一个任务                                         │
└────────────────┬──────────────────────────────────────────────────┘
                 ↓
┌──────────────────────────────────────────────────────────────────┐
│ 8. 第一个任务: "文件完整性检查" (MCP自动化 - 方式5)             │
│ ├─ 触发 Flowable TaskListener                                    │
│ ├─ MCPExecutor 调用 MCP:                                         │
│ │  POST /v1/mcp/document_validation/check_completeness         │
│ │  {                                                            │
│ │    "files": [...],                                           │
│ │    "knowledge_base_query": "NMPA 申报文件清单"                │
│ │  }                                                            │
│ ├─ MCP 内部:                                                     │
│ │  1. 查询 Membership 知识库 (语义搜索 Milvus)                  │
│ │  2. 获得"NMPA官方文件清单" + "公司内部补充要求"               │
│ │  3. 逐文件检查                                                 │
│ │  4. 生成完整性报告                                            │
│ ├─ MCP 返回结果: {status: "incomplete", missing_items: [...]}   │
│ ├─ WorkflowEngine 处理结果:                                      │
│ │  ├─ 如果 status=="complete" → 推进到下一任务                 │
│ │  └─ 如果 status=="incomplete" → 通知申请人补充                │
│ └─ 记录到 Membership 审计: "检查结果: 缺少XXX文件"               │
└────────────────┬──────────────────────────────────────────────────┘
                 ↓
┌──────────────────────────────────────────────────────────────────┐
│ 9. 申请人补充文件 (表单驱动 - 方式2)                            │
│ ├─ 系统自动生成补充表单                                         │
│ │  (MCP 告诉我们缺少什么，表单库自动生成补充表单)               │
│ ├─ 申请人在 WebApp 中填写并提交                                  │
│ └─ 回到步骤 8 重新检查                                            │
└────────────────┬──────────────────────────────────────────────────┘
                 ↓
┌──────────────────────────────────────────────────────────────────┐
│ 10. 文件检查通过后: "技术部初审" (角色队列认领 - 方式4)         │
│ ├─ WorkflowEngine 创建 Flowable Task (unassigned)               │
│ ├─ 设置 candidateUsers = 所有 "senior_reviewer" 角色的人         │
│ │  (通过 Membership API: GET /v2/members?role=senior_reviewer)  │
│ ├─ 通知所有15个评审专家: "有新任务需要认领"                     │
│ │  (推送消息、邮件、Webhook)                                    │
│ ├─ WebApp 显示: [认领] 按钮 + "还有15人可认领"                 │
│ ├─ 张三点击 [认领]:                                              │
│ │  POST /v1/workflows/{taskId}/claim                            │
│ │  WorkflowEngine 设置: task.assignee = "张三"                   │
│ ├─ 李四刷新 WebApp: 该任务消失 (不再是候选人)                   │
│ └─ 张三获得任务: 需要在10-15天内完成审查                        │
└────────────────┬──────────────────────────────────────────────────┘
                 ↓
┌──────────────────────────────────────────────────────────────────┐
│ 11. 张三完成初审并提交意见                                       │
│ ├─ POST /v1/workflows/{taskId}/complete                          │
│ │  {                                                            │
│ │    "result": "major_issues_found",                           │
│ │    "issues": [{...}, {...}],                                 │
│ │    "recommendation": "召开技术研讨会"                         │
│ │  }                                                            │
│ ├─ WorkflowEngine 处理决策:                                      │
│ │  ├─ 读取表单数据: recommendation == "召开技术研讨会"           │
│ │  ├─ 触发条件分支: → "动态多路分配" (方式3)                   │
│ │  └─ 创建多个子任务:                                           │
│ │     ├─ 子任务1: 分配给"架构经验好的人" (指定 member_id)      │
│ │     ├─ 子任务2: 分配给"临床主任" (Membership 职位)           │
│ │     ├─ 子任务3: 分配给"统计学家" (Membership 职位)           │
│ │     └─ 主任务: 等待所有子任务完成                            │
│ ├─ Membership 审计: "条件分支: 创建研讨会任务"                   │
│ └─ 所有与会者收到通知 + WebApp 显示各自任务                     │
└────────────────┬──────────────────────────────────────────────────┘
                 ↓
┌──────────────────────────────────────────────────────────────────┐
│ 12. 4个并行合规检查 (MCP自动化 - 方式5)                         │
│ ├─ 伦理合规检查:                                                │
│ │  MCP 调用: ethics_compliance.validate_ethics_report()         │
│ │  ├─ 查询知识库: "ICH GCP 指南" + "公司伦理政策"              │
│ │  ├─ 提取检查清单 (知识库驱动)                                 │
│ │  ├─ 逐项检查                                                 │
│ │  └─ 返回: pass/fail + findings                               │
│ │                                                              │
│ ├─ 统计学合规检查:                                             │
│ │  MCP 调用: statistics_validation.validate_analysis()         │
│ │  ├─ 查询知识库: "统计方法指南" + "样本量计算标准"             │
│ │  ├─ 验证 p-value, CI, ITT analysis                          │
│ │  └─ 返回: pass/fail + report                                │
│ │                                                              │
│ ├─ 法律合规检查:                                              │
│ │  MCP 调用: legal_compliance.validate_documents()             │
│ │  ├─ 查询知识库: "合同模板" + "法律风险清单"                  │
│ │  └─ 返回: pass/fail + issues                                │
│ │                                                              │
│ └─ 安全性审查:                                                │
│    MCP 调用: pharmacovigilance.validate_safety_data()          │
│    ├─ 查询知识库: "安全信号定义" + "风险评估矩阵"               │
│    ├─ 分析不良事件数据                                         │
│    └─ 返回: pass/fail + risk_signals                           │
│                                                               │
│ ⏱️  所有4个 MCP 并行执行 (总耗时 = max(2h, 1h, 1h, 30m) = 2h) │
└────────────────┬──────────────────────────────────────────────────┘
                 ↓
┌──────────────────────────────────────────────────────────────────┐
│ 13. 合规检查汇总                                                 │
│ ├─ WorkflowEngine 同步点:等待所有4个MCP完成                      │
│ ├─ 汇总结果:                                                    │
│ │  ├─ 伦理: PASS                                               │
│ │  ├─ 统计: PASS                                               │
│ │  ├─ 法律: PASS                                               │
│ │  └─ 安全: FAIL (发现2个风险信号)                             │
│ ├─ 决策:                                                       │
│ │  ├─ 因为有风险信号 → 触发 "药安委评估" (角色队列 - 方式4)  │
│ │  ├─ 创建任务: 分配给所有 "Drug Safety Officer"               │
│ │  └─ 等待评估结果                                             │
│ ├─ Membership 审计: "创建风险评估任务"                           │
│ └─ WebApp: 药安委成员看到新的认领任务                            │
└────────────────┬──────────────────────────────────────────────────┘
                 ↓
┌──────────────────────────────────────────────────────────────────┐
│ 14. 后续流程 (省略细节，模式相同)                               │
│ ├─ NMPA 预审会议 (表单驱动 - 方式2)                            │
│ ├─ NMPA 反馈处理 (条件分支)                                     │
│ ├─ 工厂现场检查 (静态 + 外部)                                   │
│ ├─ 上市前准备 (MCP自动化生成文件)                               │
│ └─ 最终提交 (MCP自动验证 + 人工确认)                            │
└────────────────┬──────────────────────────────────────────────────┘
                 ↓
         ✅ 流程完成或获批
```

---

## 五、MCP 集群设计

### 5.1 所需的 MCP 列表

```
通用基础 MCP:
├─ document_validation (文档检查)
│  ├─ check_completeness: 检查文件完整性
│  ├─ check_format: 检查格式合规性
│  └─ extract_metadata: 提取文件元数据
│
└─ knowledge_base_search (知识库查询)
   ├─ semantic_search: 向量搜索
   ├─ keyword_search: 关键词搜索
   └─ retrieve_policy: 获取政策文件

专业领域 MCP:
├─ ethics_compliance (伦理审查)
│  ├─ validate_ethics_report
│  ├─ check_informed_consent
│  └─ verify_subject_protection
│
├─ statistics_validation (统计学)
│  ├─ validate_statistical_analysis
│  ├─ check_sample_size
│  └─ verify_itt_analysis
│
├─ legal_compliance (法律合规)
│  ├─ validate_legal_documents
│  ├─ check_contract_terms
│  └─ verify_intellectual_property
│
├─ pharmacovigilance (药物安全)
│  ├─ validate_safety_database
│  ├─ detect_risk_signals
│  └─ generate_safety_report
│
├─ quality_assurance (质量管理)
│  ├─ validate_quality_documentation
│  ├─ check_analytical_methods
│  └─ verify_stability_data
│
├─ financial_analysis (财务分析)
│  ├─ validate_pricing_documentation
│  ├─ check_cost_effectiveness
│  └─ verify_market_access
│
├─ regulatory_affairs (监管事务)
│  ├─ prepare_nmpa_submission
│  ├─ check_regulatory_status
│  └─ generate_summary_documents
│
└─ document_generation (文档生成)
   ├─ generate_submission_package
   ├─ create_summary_report
   └─ generate_audit_trail

业务特定 MCP:
├─ business_rules_engine (业务规则)
│  ├─ determine_next_assignee: 基于规则分配下一个处理人
│  ├─ evaluate_decision_gate: 评估决策点
│  └─ check_approval_authority: 验证批准权限
│
├─ finance_expense_validation (财务报销)
│  ├─ validate_expense_amount
│  ├─ check_approval_limits
│  └─ verify_policy_compliance
│
├─ procurement_validation (采购管理)
│  ├─ validate_vendor_qualifications
│  ├─ check_competitive_bidding
│  └─ verify_contract_terms
│
└─ hr_recruitment (HR招聘)
   ├─ validate_position_requirements
   ├─ check_candidate_qualifications
   └─ verify_compliance_requirements
```

### 5.2 MCP 与 Membership 的交互

```python
# 示例：Business Rules Engine MCP

class BusinessRulesEngineMCP:
    """
    这个 MCP 在运行时根据流程状态和 Membership 数据
    动态决定下一个任务应该分配给谁
    """

    def determine_next_assignee(self, process_data, current_step):
        """
        输入:
          process_data: {
            "amount": 50000,
            "category": "equipment",
            "requester_org": "org_123",
            "approved_by": ["manager", "director"]
          }
          current_step: "final_approval"

        流程:
          1. 查询 Membership 组织信息
             GET /v2/orgs/org_123/hierarchy
             → 获得上级组织链: org_123 → org_456 → org_789

          2. 查询知识库：授权矩阵
             Membership KB: "采购授权矩阵 2025"
             金额 50000 元 + 设备类 → 需要 VP 审批

          3. 查询 Membership 职位信息
             GET /v2/members?org_id=org_789&position=VP
             → 返回: [member_1(VP), member_2(VP)]

          4. 检查成员的可用性和资格
             GET /v2/members/{member_id}/workload
             → member_1: 当前负载 85%
             → member_2: 当前负载 40%

          5. 智能分配
             assigned_to = member_2 (负载较轻)
        """

        # 查询组织链
        org_chain = self.membership.get_org_chain(process_data["requester_org"])

        # 查询授权矩阵 (从知识库)
        approval_policy = self.membership.query_knowledge_base(
            query="采购授权矩阵",
            filters={"doc_type": "policy", "category": "approval_limits"}
        )

        # 从 policy 中解析规则
        rule = self.parse_approval_rule(
            approval_policy,
            amount=process_data["amount"],
            category=process_data["category"]
        )
        # 返回: {required_role: "VP", org_id: org_789}

        # 查询符合条件的人员
        candidates = self.membership.get_members_by_role(
            role=rule["required_role"],
            org_id=rule["org_id"]
        )

        # 优选负载较轻的人
        best_candidate = self.select_least_loaded(candidates)

        return {
            "assigned_to": best_candidate["id"],
            "assigned_to_name": best_candidate["name"],
            "reason": f"Authority: {rule['required_role']}, Load: {best_candidate['workload']}%",
            "policy_ref": approval_policy["id"],
            "assigned_at": now()
        }
```

---

## 六、架构的关键创新

### 6.1 知识库驱动的决策

**所有重要决策都可以基于 Membership 知识库中存储的政策、指南、规范**：

```
传统方式:
  规则写死在代码中
  → 更新政策需要修改代码 + 重新部署
  → 易出错，维护困难

新方式 (知识库驱动):
  规则存在 Membership 知识库中
  → MCP 在运行时查询规则
  → 政策变化只需更新知识库 + 无需重部署
  → 完全可审计 (谁改了什么时间改的)
```

### 6.2 审计链路的完整性

**整个流程从设计到执行的每一步都有审计记录**：

```
审计链路:
1. 流程定义创建
   → Membership 审计: "process_123 created by user_001"

2. 流程启动
   → Membership 审计: "process_instance_456 started"

3. MCP 决策
   → Membership 审计: "knowledge_base queried for approval_policy"
   → Membership 审计: "task assigned to user_002 based on policy_v2.1"

4. 任务认领
   → Membership 审计: "task_789 claimed by user_003"

5. 任务完成
   → Membership 审计: "task_789 completed with result: PASS"

6. 决策分支
   → Membership 审计: "conditional branch triggered: route_A"

完整的可追溯性: 所有决策都能回溯到具体的政策版本和时间点
```

### 6.3 与 WebApp 的完美集成

```
WebApp 的简洁性:
├─ 不需要实现复杂的业务逻辑
├─ 不需要查询 Membership API (后端代劳)
├─ 只需要:
│  ├─ 显示表单
│  ├─ 显示任务列表
│  ├─ 显示认领/完成按钮
│  └─ 提交表单数据给后端
│
└─ 后端处理:
   ├─ 权限验证 (Membership)
   ├─ 业务逻辑 (MCP)
   ├─ 流程推进 (Flowable)
   ├─ 审计记录 (Membership)
   └─ 通知用户 (WebSocket/Push)
```

---

## 七、实现优先级

### Phase 2 分三个子阶段

```
Phase 2.1 (第1个月):
├─ 完成 BPMN-MCP 基础版本
│  └─ 支持方式1 (静态) + 方式2 (表单驱动)
├─ 完成 FORM-MCP 基础版本
└─ 与 Membership 完成基础集成 (组织查询)

Phase 2.2 (第2个月):
├─ 添加 MCP 自动化任务支持 (方式5)
├─ 实现 WorkflowEngine 核心逻辑
├─ 完成与知识库的集成
│  ├─ 关键词搜索
│  ├─ 向量搜索
│  └─ 政策查询
└─ 实现角色队列认领 (方式4)

Phase 2.3 (第3个月):
├─ 添加动态多路分配 (方式3)
├─ 实现条件分支和循环
├─ 完成 WebApp 集成
├─ 性能优化和扩展测试
└─ 以新药申报流程为实际案例演示
```

---

## 八、总结：为什么这个架构能支持天级别的复杂流程

```
1. 混合执行者模式 (5种)
   ✅ 覆盖人工 + 自动化的所有场景

2. 知识库驱动决策
   ✅ 政策变化无需改代码
   ✅ 完全审计可追踪

3. MCP 集群
   ✅ 领域专家系统
   ✅ 可持续扩展 (新业务新MCP)

4. Membership 作为基础设施
   ✅ 组织、权限、审计统一管理
   ✅ 知识库作为企业大脑

5. 前后端分工清晰
   ✅ 前端仅显示 + 提交
   ✅ 后端处理逻辑 + 权限 + 审计

6. 完整的审计链路
   ✅ 每个决策都能追溯
   ✅ 符合监管要求
```

这不是一个简单的流程引擎，而是一个**AI驱动的、知识库支撑的、完全审计的、企业级的智能工作流平台**。
