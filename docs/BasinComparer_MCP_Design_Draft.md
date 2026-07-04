# BasinComparer MCP 服务设计草案

## 1. 背景与目标

BasinComparer MCP 服务面向石油勘探决策场景，基于已经进入 `membership-docs` 并完成 DocIntel 处理的盆地、凹陷、区带、层系等综合地质资料，形成可审计、可解释、可排序的勘探优先级结论。

服务的核心目标不是单纯回答“某个凹陷有什么资料”，而是回答：

- 哪些盆地或凹陷应优先开展下一步勘探工作？
- 为什么某个目标排在另一个目标之前？
- 当前资料是否足以支撑排序结论？
- 应该优先部署预探井、评价井、补充地震解释、开展专项研究，还是暂缓投入？

因此，BasinComparer 的业务定位是：

```text
基于 DocIntel 已处理文档资料，完成盆地/凹陷资料完备性评估、地质条件量化评价、勘探优先级排序和下一步部署建议生成。
```

## 2. 前提条件

本服务不负责原始文档采集和基础抽取，默认以下条件已经满足：

- 盆地、凹陷、区带、层系相关综合地质报告、资源评价报告、钻井资料、测试资料、地震解释资料等已进入 `membership-docs`。
- DocIntel Stage 1 已完成 normalized content 持久化。
- DocIntel Stage 2 已完成全文索引、语义 chunk、embedding、RAG/GraphRAG 检索索引。
- 结构化表格指标已尽量进入 `doc_tables` / `doc_table_rows`。
- 文档、页面、chunk、表格、公式等对象保留可追溯的 source metadata。
- `SY/T 5519-2011 盆地评价技术规范` 已作为标准依据文档进入 `membership-docs`，并可通过 DocIntel RAG 检索到相关章节和条款摘要。

BasinComparer 是 DocIntel 之上的领域评价服务，不应改写 DocIntel Stage 1 / Stage 2 的基础职责。

## 3. 设计原则

### 3.1 先判断能不能评，再判断值不值得投

盆地/凹陷排序必须以资料完备性为前置条件。资料不足和地质条件差不能混为一个低分。

系统应分别输出：

- `data_readiness_score`：资料完备性分。
- `geological_score`：地质评价分。
- `decision_confidence`：决策置信度。

### 3.2 排序结论必须可追溯

每个评分项、排序结论和部署建议都应能追溯到 DocIntel 证据：

- 文档 ID / 文档名称。
- 版本。
- 页码。
- chunk 引用。
- 表格 `table_pk` 或结构化行列引用。
- 指标来源类型：原文数值、表格数值、模型抽取、规则推断、人工修正。

### 3.3 表格和公式不能当普通文本处理

涉及 TOC、Ro、孔隙度、渗透率、资源量、突破压力等精确指标时，应优先使用结构化表格路径。

语义检索可以用于定位相关资料，但精确数值查询应优先走：

```text
doc_tables / doc_table_rows
```

### 3.4 评分规则必须版本化

不同评价标准、权重配置、缺失值处理方式会影响排序结果。服务必须记录评分模型版本，保证结果可复现。

建议记录：

- `score_rule_version`
- `dimension_weights`
- `indicator_scoring_rules`
- `missing_data_policy`
- `confidence_penalty_policy`
- `evidence_selection_policy`

### 3.5 标准依据必须动态检索

BasinComparer 不应只依赖代码或方案文档中固化的标准摘要。执行评价任务时，应优先检索 `SY/T 5519-2011 盆地评价技术规范` 原文，提取与本次任务相关的标准要求，并形成标准对标清单。

标准检索结果用于约束：

- 资料完备性检查。
- 评价内容覆盖检查。
- 关键图件和表格成果引用检查。
- 排序解释。
- 勘探部署建议。
- 报告中的标准符合性说明。

标准检索用于约束和对标，不直接替代固定评价框架、评分规则和专家校核。

## 4. 总体流程

```text
membership-docs 已入库资料
        |
        v
DocIntel normalized content + RAG/GraphRAG + table lookup
        |
        v
标准要求读取 load_evaluation_standard_requirements
        |
        v
资料完备性评估 assess_target_data_readiness
        |
        v
盆地/凹陷评价画像 build_basin_evaluation_profile
        |
        v
地质评分与风险诊断 score_exploration_target
        |
        v
多目标排序 rank_exploration_targets
        |
        v
部署建议 recommend_exploration_deployment
        |
        v
已有图表引用与缺失检查 check_required_evaluation_artifacts
        |
        v
可追溯报告 generate_basin_comparison_report
```

## 5. 资料完备性评估

资料完备性评估是排序前置任务。它不只是检查“有没有文档”，还要判断资料是否覆盖关键评价维度，证据是否足够可靠。

### 5.1 检查维度

| 检查项 | 说明 |
|---|---|
| 文档覆盖 | 是否存在综合地质报告、资源评价、烃源岩、储层、盖层、圈闭、钻井、测试、地震解释等资料 |
| 指标覆盖 | 五大评价维度下关键指标是否齐全 |
| 证据类型 | 指标来自原文、表格、模型抽取、推断补全还是人工修正 |
| 时效性 | 资料年份是否过旧，是否缺少新钻井、新地震、新测试成果 |
| 一致性 | 多来源资料之间是否存在指标冲突 |
| 可追溯性 | 是否能追到文档、页码、chunk、表格或行列 |
| 缺口影响 | 缺失项是否影响排序、井位部署或风险判断 |

### 5.2 输出等级

| 等级 | 含义 | 后续动作 |
|---|---|---|
| `READY` | 关键资料完整，可进入强排序 | 正常评分、排序、生成部署建议 |
| `PARTIAL` | 资料基本可用，但存在重要缺口 | 允许排序，但必须降低置信度并列出缺口 |
| `INSUFFICIENT` | 关键资料不足，不足以支撑排序 | 不做强排序，只输出资料缺口和补充建议 |

### 5.3 缺失资料处理

缺失资料不能简单按 0 分处理。系统应区分：

- 地质条件明确较差。
- 资料不足导致不能判断。
- 多来源证据冲突导致置信度降低。
- 指标存在但仅为推断值或弱证据。

## 6. 评价维度与初始权重

初始评分模型采用五个一级维度，满分 100 分。

| 维度 | 初始权重 | 核心指标 |
|---|---:|---|
| 烃源岩条件 | 25% | TOC、Ro、有机质类型、生烃强度、有效烃源岩厚度 |
| 储层条件 | 25% | 孔隙度、渗透率、含油饱和度、储层厚度、储层连续性 |
| 盖层条件 | 15% | 盖层厚度、突破压力、连续性、封盖能力 |
| 圈闭条件 | 15% | 圈闭类型、规模、落实程度、形成时间与成藏期匹配度 |
| 资源潜力 | 20% | 资源量、资源丰度、可采系数、资源评价置信度 |

权重应可配置，但配置必须随评分结果一起记录。

## 7. 评分与置信度

### 7.1 指标评分

每个子指标可采用分段函数、阶梯函数或行业标准阈值评分。

示例：

```text
indicator_score = scoring_rule(indicator_value, rule_version)
dimension_score = sum(indicator_score * indicator_weight)
geological_score = sum(dimension_score * dimension_weight)
```

### 7.2 置信度计算

决策置信度不应只来自模型置信度，而应综合：

- 资料完备性。
- 指标来源可靠性。
- 多来源一致性。
- 资料时效性。
- 是否存在人工确认或专家修正。
- 是否有结构化表格证据支持。

### 7.3 排序约束

排序结果应避免把高潜力但资料不足的目标直接排到低位。建议排序输出同时包含：

```text
rank
target_name
geological_score
data_readiness_score
decision_confidence
recommended_action
key_strengths
key_risks
data_gaps
```

## 8. 部署建议逻辑

勘探行动建议应由地质评分、资料完备性和置信度共同决定。

| 地质评价 | 资料完备性 | 建议动作 |
|---|---|---|
| 高 | 高 | 优先部署预探井或评价井 |
| 高 | 中/低 | 先补充关键资料，再进入井位论证 |
| 中 | 高 | 选择性部署，优先做优势层系或构造带专项评价 |
| 中 | 中/低 | 补充储层、圈闭、资源量等关键证据后再排序 |
| 低 | 高 | 暂缓钻探或降低投入优先级 |
| 低 | 低 | 不输出强结论，仅列资料缺口和风险 |

建议动作类型包括：

- 优先部署预探井。
- 优先部署评价井。
- 开展井位论证。
- 补充二维/三维地震解释。
- 补充烃源岩或储层实验分析。
- 开展区带专项评价。
- 暂缓钻探。
- 退出或降低投入优先级。

## 9. MCP 工具设计

### 9.1 `load_evaluation_standard_requirements`

读取并确认本次评价任务适用的标准要求。

默认标准为：

```text
SY/T 5519-2011 盆地评价技术规范
```

输入：

```json
{
  "standard_name": "SY/T 5519-2011 盆地评价技术规范",
  "task_type": "basin_evaluation | sag_ranking | deployment_recommendation",
  "evaluation_stage": "regional_geological_evaluation | basin_evaluation | rolling_evaluation",
  "target_scope": {
    "basin": "string",
    "target_names": ["string"]
  }
}
```

输出：

```json
{
  "standard_name": "string",
  "standard_version": "string",
  "retrieved_sections": [],
  "geological_tasks": [],
  "evaluation_principles": [],
  "evaluation_content_requirements": [],
  "evaluation_steps": [],
  "method_constraints": [],
  "deliverable_requirements": [],
  "artifact_checklist": [],
  "expert_review_points": [],
  "evidence_refs": []
}
```

该工具输出的标准对标清单应作为后续资料完备性检查、评价画像构建、图表成果检查、排序解释和报告输出的共同约束。

### 9.2 `assess_target_data_readiness`

评估单个盆地/凹陷是否具备进入排序评价的资料基础。

输入：

```json
{
  "target_name": "string",
  "target_type": "basin | sag | belt | layer",
  "tenant_id": "number",
  "scope": {
    "basin": "string",
    "formation": "string",
    "period": "string"
  }
}
```

输出：

```json
{
  "target_name": "string",
  "readiness_level": "READY | PARTIAL | INSUFFICIENT",
  "data_readiness_score": 0,
  "covered_dimensions": [],
  "missing_dimensions": [],
  "critical_data_gaps": [],
  "evidence_summary": [],
  "blocking_issues": []
}
```

### 9.3 `build_basin_evaluation_profile`

构建单个目标的结构化评价画像。

输出应包含五大评价维度、关键指标、指标值、单位、来源、证据链和置信度。

### 9.4 `compare_exploration_targets`

对两个或多个目标进行横向对比。

输出应包含：

- 分维度对比表。
- 优势/劣势解释。
- 数据缺口对比。
- 冲突证据说明。
- 初步排序结论。

### 9.5 `rank_exploration_targets`

对多个盆地/凹陷进行勘探优先级排序。

排序结果必须同时展示地质得分、资料完备性分、决策置信度和推荐动作。

### 9.6 `explain_target_ranking`

解释某个目标为什么排在当前名次。

重点回答：

- 拉高排名的关键因素。
- 拉低排名的关键因素。
- 哪些缺失资料影响了置信度。
- 与前后名次目标的核心差异。

### 9.7 `recommend_exploration_deployment`

生成下一步勘探部署建议。

输出建议应区分：

- 可以直接进入井位论证。
- 需要补充资料后再部署。
- 适合专项研究。
- 建议暂缓或降低优先级。

### 9.8 `trace_evaluation_evidence`

追溯某个评分项、排序结论或部署建议的证据来源。

输出应包括文档、页码、chunk、表格、行列、引用内容摘要和证据质量。

### 9.9 `check_required_evaluation_artifacts`

按盆地评价规范和专家评审要求，检查当前资料中是否已有支撑评价所需的关键图件、表格和参数成果。

本工具只做引用、核查和缺失识别，不生成专业图件，不重新解释地震资料，不重算资源量成果表。

输出应包括：

- 已有图件：图名、图号、文档、页码、对应评价模块、支撑的结论。
- 已有表格：表名、表号、文档、页码、是否有结构化 rows、可引用的关键指标。
- 可引用结构化表格：可用于摘录或对比的字段、来源和适用范围。
- 缺失图件：缺失项、影响的评价模块、对结论可信度的影响。
- 缺失表格或指标：缺失项、影响的评分项或部署建议。
- 支撑关系：哪些结论有图表支撑，哪些结论缺少图表支撑。
- 专家补充建议：需要由专业解释、制图或资源评价工作补充的成果。

对于已有结构化行列数据的表格，可以生成引用式摘录表或对比汇总表。该类表格必须标注来源，不应表述为重新计算或重新解释形成的专业成果。

### 9.10 `generate_basin_comparison_report`

生成标准化报告。

报告类型：

| 类型 | 场景 | 内容 |
|---|---|---|
| 简要报告 | 快速决策 | 排名、核心结论、关键参数、建议动作 |
| 标准报告 | 常规分析 | 完整评分、对比解释、证据摘要、风险与缺口、已有图表引用清单 |
| 详细报告 | 深度评估 | 增加敏感性分析、冲突证据、资料补充计划、需专家补充的图表成果 |

## 10. 输出报告结构

建议报告采用以下结构：

```text
1. 结论摘要
2. 资料完备性评估
3. 排序结果
4. 分维度评分对比
5. 关键优势与主要风险
6. 数据缺口与置信度说明
7. 下一步勘探部署建议
8. 证据追溯清单
9. 已有图件和表格引用清单
10. 缺失图件、缺失表格和缺失关键指标清单
11. 评分规则版本与参数
```

## 11. 与 DocIntel 的边界

BasinComparer 只消费 DocIntel 已产出的内容和索引，不改变基础文档处理链路。

| 层级 | 职责 |
|---|---|
| DocIntel Stage 1 | 文档 normalized content、表格、公式、页面级结构化内容持久化 |
| DocIntel Stage 2 | chunk、embedding、全文索引、RAG/GraphRAG、table lookup |
| BasinComparer | 领域指标抽取、资料完备性评估、评分、排序、部署建议、已有图表引用与缺失检查、报告生成 |

如果 BasinComparer 发现资料缺失或结构化质量不足，应输出缺口或质量问题，不应绕过 Stage 1/Stage 2 直接调用 OCR、PDF2MD、VLM 或 Office 转换工具修复源文档。

## 12. MVP 范围

第一阶段建议只实现以下能力：

- 标准要求读取与标准对标清单生成。
- 单目标资料完备性评估。
- 单目标评价画像构建。
- 两目标对比。
- 多目标排序。
- 基于规则的部署建议。
- 证据追溯。
- 已有图件和表格引用检查。
- 缺失图件、缺失表格和缺失关键指标识别。
- 标准 Markdown 报告输出。

暂缓能力：

- PDF / Excel / PPT 导出。
- 专业图件生成。
- 地震资料重新解释。
- 资源量重算或专业成果表重建。
- 井位部署图生成。
- 神经网络评价模型。
- 复杂 AHP 交互式权重推导。
- 蒙特卡洛模拟。
- 自动井位坐标推荐。

## 13. 后续扩展

后续可扩展：

- 运移条件、保存条件、工程条件、经济条件等新评价维度。
- AHP、模糊综合评价等多模型评分。
- 基于历史勘探成败样本的模型校准。
- 与井位部署系统、GIS、地震解释成果库集成。
- 输出 PDF、Excel、PPT 等多格式成果。
- 独立建设专业图件或成果表生成能力。
- 对资料更新后的排序变化进行版本对比。

## 14. 关键风险

| 风险 | 说明 | 控制方式 |
|---|---|---|
| 资料不足被误判为地质条件差 | 缺失数据直接拉低评分会误导排序 | 分离地质分和资料完备性分 |
| 标准依据漂移 | 只依赖手写摘要会遗漏标准要求或产生理解偏差 | 执行时检索标准原文并生成对标清单 |
| 精确指标来自文本猜测 | RAG chunk 不适合直接回答精确表格值 | 精确值优先走 `doc_tables` / `doc_table_rows` |
| 排序看似精确但不可审计 | 只有综合分，没有证据链 | 每个评分项保留证据引用 |
| 规则变化导致结果不可复现 | 权重和阈值未版本化 | 保存 `score_rule_version` 和完整参数 |
| 部署建议越权 | 高分不等于可以直接钻井 | 建议动作必须受资料完备性和置信度约束 |
| 图表生成责任越界 | 自动生成构造图、资源潜力图或部署图会替代专业解释工作 | 本阶段只做已有图表引用与缺失检查 |

## 15. 当前结论

BasinComparer MCP 适合基于 DocIntel 构建，但它应被设计为“证据驱动的勘探排序与部署建议服务”，而不是普通资料问答或单纯打分器。

最小闭环应是：

```text
资料是否足够 -> 地质条件如何 -> 排名为什么如此 -> 下一步该做什么 -> 证据在哪里
```
