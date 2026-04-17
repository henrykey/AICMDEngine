# DocIntel MCP 规范驱动编排设计方案

日期：2026-04-17  
状态：Proposed  
范围：DocIntel / MCP Router / Planner / Executor / External MCPs

## 1. 背景

当前系统已经具备较强的文档处理能力基础，但这些能力分散在多个层次：

- DocIntel 自身文档上传、处理、检索、索引接口
- `PDF2MD Enhanced`、`PaddleOCR`、`office-word` 等处理能力
- `doc_processing_tasks`、`doc_page_states`、`doc_rag_pages` 等任务与产物模型
- `fulltext / vector / pageindex` 三通道索引设计

当前缺失的不是底层能力，而是一个面向自然语言任务的统一文档知识库建设入口。

用户的真实诉求通常不是：

- “调用某个 OCR 服务”
- “调用某个 Markdown 转换器”
- “执行某个 embedding 接口”

而是：

- “把这个目录下的 PDF、Word、MD 都上传，分类叫建筑规范”
- “按现有规范处理这批文档并入库”
- “把这份 PDF 做布局识别，表格结构化入库，图片转语义描述，公式转 LaTeX，再生成 Markdown 和向量”
- “重建全文/语义索引”
- “删掉旧版文档，用新版替换并按原规范重跑”

因此需要一个新的 `docintel_mcp`，用于把用户自然语言目标稳定映射为符合 DocIntel 规范的处理任务。

## 2. 问题定义

### 2.1 当前缺口

1. 缺少一个统一的“文档知识库建设助手”型 MCP。
2. 用户不会记住内部处理规范，只会按自己的语言表达目标。
3. 处理结果不能偏离现有 DocIntel 规范，但目前没有专门的“规范解析与约束执行”层。
4. 底层 extractor / OCR / VLM / 索引能力存在，但没有统一任务抽象对外暴露。
5. 管理类动作（删除、重建索引、重跑处理）需要受控暴露，不能和普通任务工具混在一起。

### 2.2 设计要求

新的 `docintel_mcp` 必须同时满足：

1. 用户可自由表达目标结果。
2. 执行结果必须收敛到 DocIntel 已有规范。
3. 任务控制语义必须统一，不依赖某个 extractor 私有逻辑。
4. 处理链路必须对齐现有产物模型：
   - `render markdown`
   - `doc_rag_pages`
   - `fulltext`
   - `vector`
   - `pageindex`
5. 表格、图片、公式等结构化内容必须可纳入受控处理范围。

## 3. 设计目标

### 3.1 总体目标

构建一个新的 `docintel_mcp`，作为面向自然语言的“规范驱动文档编排 MCP”，让用户能够通过自然语言完成知识库建设工作，同时保证执行结果不偏离 DocIntel 既有规范。

### 3.2 关键原则

1. **规范优先，不是 provider 优先**
   - 用户不需要记住 `glm-ocr`、`qwen-vl`、`PDF2MD Enhanced` 等内部组件。
   - 用户描述目标结果，系统再根据规范选择组件。

2. **自然语言自由表达，结果必须受控**
   - 用户输入是意图。
   - 规范是约束源。
   - pipeline 是编译结果。

3. **任务控制属于处理框架，不属于 extractor**
   - `pause / resume / retry / cancel` 统一建模。
   - 不允许由单个 extractor 自己定义任务语义。

4. **工具面向任务，不面向底层 API**
   - MCP 工具应表达“导入、按规范处理、重建索引、重试处理”等业务任务。
   - 不直接暴露零散底层调用。

5. **管理工具与普通任务工具分离**
   - 破坏性或运维型能力单独标记，避免 planner 误召回。

## 4. 规范依据

本设计主要依赖以下现有设计基线：

1. [membership_v2.4_doc_design.md](/Users/kehongwei/workspace/AICMDEngine/docs/membership_docs/membership_v2.4_doc_design.md)
   - 明确了 `/v2/documents/**` API 契约
   - 明确了 Mongo / S3 / ES 存储分离
   - 明确了分块、向量化、索引的标准链路

2. [INTELLIGENT_TEXT_EXTRACTION_DESIGN.md](/Users/kehongwei/workspace/AICMDEngine/docs/membership_docs/INTELLIGENT_TEXT_EXTRACTION_DESIGN.md)
   - 明确了智能提取策略
   - 明确了结构化内容模型
   - 明确了图片、公式、表格、Markdown 化目标

3. [2026-03-14-docintel-unified-document-processing-control-plan.md](/Users/kehongwei/workspace/AICMDEngine/docs/membership_docs/plans/2026-03-14-docintel-unified-document-processing-control-plan.md)
   - 明确了统一任务控制语义
   - 明确了任务、处理单元、checkpoint 约束

4. [2026-03-07-docintel-pdf2md-improvement-design.md](/Users/kehongwei/workspace/AICMDEngine/docs/membership_docs/plans/2026-03-07-docintel-pdf2md-improvement-design.md)
   - 明确了 `render markdown`、`doc_rag_pages`、`fulltext/vector/pageindex` 三通道
   - 明确了 `table_lookup` 与表格结构化入库方向
   - 明确了 `change_flags.*`、`retry_from`、`rebuild_version` 等流水线语义

## 5. 目标架构

`docintel_mcp` 采用三层结构：

### 5.1 用户任务层

承接用户自然语言目标，例如：

- “把 `/docs/specs` 下所有 PDF 和 Word 按建筑规范入库”
- “这份扫描 PDF 按增强识别规范处理”
- “表格结构化入库并补语义说明，图片转语义描述，公式转 LaTeX”
- “重建建筑规范分类的全文和语义索引”

### 5.2 规范解析层

负责：

1. 将用户输入映射到最匹配的 policy
2. 识别用户附加约束
3. 判断哪些覆盖项允许生效
4. 拒绝或降级处理超出规范边界的要求

该层输出：

- `matched_policy`
- `resolved_policy`
- `policy_conflicts`

### 5.3 执行编排层

负责将 `resolved_policy` 编译为可执行 pipeline，并落到现有处理框架：

- 任务模型：`doc_processing_tasks`
- 页状态：`doc_page_states`
- RAG 数据：`doc_rag_pages`
- 产物：`render markdown`
- 索引通道：`fulltext / vector / pageindex`

## 6. 核心模型

### 6.1 Policy

表示 DocIntel 内部已定义的处理规范。

建议字段：

- `policy_id`
- `name`
- `description`
- `document_types`
- `applicable_scenarios`
- `required_stages`
- `default_extractors`
- `output_contract`
- `index_contract`
- `allowed_overrides`
- `forbidden_overrides`
- `risk_level`

### 6.2 ResolvedPolicy

表示用户请求与标准 policy 合并后的结果。

建议字段：

- `policy_id`
- `matched_by`
- `confidence`
- `resolved_options`
- `rejected_options`
- `deviations`
- `final_contract`

### 6.3 ExecutionPipeline

表示最终编译得到的执行计划。

建议字段：

- `pipeline_id`
- `task_type`
- `unit_granularity`
- `stages`
- `retry_from`
- `artifacts`
- `index_channels`
- `resume_supported`

### 6.4 PolicyConflict

用于表达用户要求与规范约束冲突。

建议字段：

- `field`
- `requested_value`
- `allowed_range`
- `resolution`
- `severity`

## 7. 规范驱动执行机制

### 7.1 用户输入不是 pipeline

用户自然语言是目标描述，不是最终执行计划。

例如用户说：

“这个 PDF 先做布局识别，文字正常处理，公式及表格交给 xxx，图交给 qwen-vl 获得描述，然后合并成 md，再切片和向量生成”

系统不应直接按字面逐项执行，而应：

1. 识别适用 policy
2. 判断哪些要求是该 policy 的默认行为
3. 判断哪些要求属于允许覆盖项
4. 生成 `resolved_pipeline`

### 7.2 用户自由表达的约束边界

系统允许用户自由表达，但必须保证：

1. 不违反既定处理规范
2. 不绕开标准产物与索引链路
3. 不让危险管理动作在无明确意图时被默认执行

### 7.3 支持的覆盖维度

建议仅允许以下维度作为规范内 override：

- `layout_mode`
- `text_mode`
- `table_mode`
- `image_mode`
- `formula_mode`
- `markdown_mode`
- `chunking_mode`
- `index_channels`

示例：

- `table_mode`: `skip | text_only | structured | structured_with_summary`
- `image_mode`: `keep | caption | semantic_replace`
- `formula_mode`: `text | latex | latex_with_summary`

这些值是否允许，由 `Policy.allowed_overrides` 决定。

## 8. MCP 工具分组

### 8.1 规范发现与解释类

1. `list_processing_policies`
2. `get_processing_policy`
3. `explain_policy_resolution`

职责：

- 列出现有处理规范
- 查看规范内容
- 解释“用户输入将如何映射到哪条规范”

### 8.2 文档资产管理类

1. `ingest_documents`
2. `update_document`
3. `delete_documents`
4. `list_documents`
5. `get_document`

职责：

- 批量导入目录/文件
- 替换文档
- 删除文档
- 查询文档清单与详情

### 8.3 规范驱动处理类

1. `process_documents_by_policy`
2. `reprocess_documents_by_policy`

职责：

- 根据 policy 对文档执行处理
- 对已有文档按新 policy 或新规则重跑

### 8.4 索引与修复类

1. `build_knowledge_index`
2. `repair_document_pipeline`
3. `get_index_status`

职责：

- 触发 `fulltext / vector / pageindex` 三通道重建
- 基于 `change_flags.*` 修复索引与中间状态
- 查询索引健康状态

### 8.5 任务控制类

1. `list_processing_tasks`
2. `get_pipeline_status`
3. `retry_processing_task`
4. `pause_processing_task`
5. `resume_processing_task`
6. `cancel_processing_task`

职责：

- 提供统一任务控制接口
- 对齐现有统一任务控制设计

## 9. 核心工具定义

### 9.1 `process_documents_by_policy`

这是第一核心工具。

#### 输入建议

- `target_query`
- `policy_query`
- `instructions`
- `category_name`
- `tags`
- `recursive`
- `file_types`
- `override_options`

#### 行为

1. 解析目标文档或目录
2. 匹配最合适的 policy
3. 解析用户意图中的附加约束
4. 生成 `resolved_policy`
5. 编译为 `resolved_pipeline`
6. 创建处理任务

#### 输出建议

- `task_id`
- `document_ids`
- `matched_policy`
- `resolved_policy`
- `resolved_pipeline`
- `policy_conflicts`
- `status`

### 9.2 `build_knowledge_index`

用于统一触发知识库索引任务。

#### 输入建议

- `scope`
- `category_name`
- `document_ids`
- `index_channels`
- `force`

#### 支持通道

- `fulltext`
- `vector`
- `pageindex`

#### 对齐要求

该工具必须对齐现有重建语义：

- `REINDEX_FULLTEXT`
- `REINDEX_VECTOR`
- `REINDEX_PAGEINDEX`

### 9.3 `explain_policy_resolution`

用于提高可解释性，避免“系统做了什么用户看不懂”。

#### 输入建议

- `policy_query`
- `instructions`
- `document_type`

#### 输出建议

- `matched_policy`
- `confidence`
- `accepted_overrides`
- `rejected_overrides`
- `final_behavior_summary`

## 10. 管理动作分级

为避免 planner 误召回危险工具，工具需区分：

### 10.1 `task_tool`

适合自然语言主链路优先召回的工具：

- `list_processing_policies`
- `get_processing_policy`
- `ingest_documents`
- `process_documents_by_policy`
- `list_documents`
- `get_pipeline_status`

### 10.2 `admin_tool`

破坏性或运维型工具：

- `delete_documents`
- `build_knowledge_index`
- `repair_document_pipeline`
- `retry_processing_task`
- `pause_processing_task`
- `resume_processing_task`
- `cancel_processing_task`

## 11. category 与 tags 规范

### 11.1 category

建议使用以下分类：

- `cmdengine.command.mcp.docintel.policy`
- `cmdengine.command.mcp.docintel.document`
- `cmdengine.command.mcp.docintel.processing`
- `cmdengine.command.mcp.docintel.index`
- `cmdengine.command.mcp.docintel.task`

### 11.2 tags

建议按“领域 + 对象 + 动作 + 用途”组织：

示例：

- `list_processing_policies`
  - `["docintel", "policy", "list", "task_tool"]`
- `process_documents_by_policy`
  - `["docintel", "policy", "document", "process", "task_tool"]`
- `build_knowledge_index`
  - `["docintel", "index", "rebuild", "admin_tool"]`
- `retry_processing_task`
  - `["docintel", "task", "retry", "admin_tool"]`

## 12. 与现有能力的衔接

`docintel_mcp` 不直接实现底层处理算法，而是编排现有能力：

- 文档上传与状态查询：DocIntel `/v2/documents/**`
- 任务控制：`/v2/processing/**`
- PDF 复杂处理：`PDF2MD Enhanced`
- OCR：`PaddleOCR` 或兼容 OCR MCP
- Word 结构化处理：`office-word`
- PageIndex 构建：`pageindex` 相关链路
- 表格结构化落库：`doc_tables / doc_table_rows`

该 MCP 是 orchestration 层，不是 extractor 层。

## 13. 第一版范围

建议 MVP 只先做 6 个工具：

1. `list_processing_policies`
2. `get_processing_policy`
3. `ingest_documents`
4. `process_documents_by_policy`
5. `build_knowledge_index`
6. `get_pipeline_status`

原因：

1. 已可覆盖“发现规范 -> 导入 -> 按规范处理 -> 建索引 -> 查状态”的主链路
2. 能最早验证“自然语言自由表达 + 规范约束执行”的设计
3. 破坏性管理动作可放到第二阶段

## 14. 实施计划

### Phase 1: 元数据与同步适配

目标：

- 扩展 MCP `Tool` 元数据以支持更细粒度 category
- 为 `docintel_mcp` 设计统一 tags/category
- 使 DocIntel 同步不再将所有 MCP 工具硬编码到单一 category

交付：

- `Tool.category`
- `Tool.risk_level`
- DocIntel 文档构建支持 tool-level category

### Phase 2: Policy 发现与解释

目标：

- 构建 policy 查询层
- 支持 `list_processing_policies / get_processing_policy / explain_policy_resolution`

交付：

- Policy 模型
- ResolvedPolicy 模型
- 基础 policy matching 逻辑

### Phase 3: 主处理工具

目标：

- 实现 `ingest_documents`
- 实现 `process_documents_by_policy`

交付：

- 目录批量导入
- 自然语言 -> policy -> pipeline 编译
- 任务创建与状态返回

### Phase 4: 索引与任务控制

目标：

- 实现 `build_knowledge_index`
- 对齐 `retry/pause/resume/cancel` 任务控制

交付：

- 三通道索引重建入口
- 统一任务控制 MCP 工具

### Phase 5: 高级管理与修复

目标：

- 实现 `reprocess_documents_by_policy`
- 实现 `repair_document_pipeline`
- 实现 `delete_documents`

交付：

- 重跑与一致性修复
- 受控管理动作

## 15. 风险与约束

### 15.1 主要风险

1. **规范来源不统一**
   - 若当前 DocIntel 规范散落在文档和代码中，policy 抽象需要先做收敛。

2. **用户描述过于自由**
   - 需要解释型工具和冲突输出，避免黑盒行为。

3. **底层 extractor 能力差异**
   - 不同文档类型的处理粒度不同，需统一成 task/unit 模型。

4. **危险动作误召回**
   - 必须通过 `admin_tool` 和风险等级控制。

### 15.2 非目标

本方案不在第一阶段解决：

1. 新建全套 extractor
2. 重写 DocIntel 底层处理引擎
3. 让用户直接拼底层 provider/workflow DSL

## 16. 验收标准

以下条件满足时，认为 `docintel_mcp` 第一阶段设计达标：

1. 用户可以用自然语言描述目标结果，而无需记住内部规范名称。
2. 系统能够返回“命中哪条规范、哪些覆盖被接受、哪些被拒绝”。
3. 文档处理任务能稳定映射到现有 DocIntel 任务与产物模型。
4. 索引重建能够明确作用于 `fulltext / vector / pageindex`。
5. 管理动作与普通任务动作在工具层清晰分级。

## 17. 一句话定义

`docintel_mcp` 不是文档 CRUD 工具集合，而是一个“把用户自然语言目标约束到 DocIntel 规范结果上，并自动编排处理与索引流水线”的知识库建设助手。
