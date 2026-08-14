# PDF2MD Large Table Recovery Goals Loop

日期：2026-08-02
状态：Executing（Goals 1、2、4、5 的首轮最小实现与本地验证已完成；Goal 3 等待三档真实页证据）
责任边界：本计划仅覆盖 `AICMDEngine/mcp/servers/PDF2MDEnhanced` 的大表路由、结构化输出预算、回退与安全诊断；不修改 Membership / DocIntel 的业务语义。
现场样本：`EJMA Expansion Joints_10th.pdf-p187`，单页、双层表头、约 10 列、约 60 行、约 600 个单元格，并包含纵向合并单元格。

执行记录（2026-08-02）：

- 已贯通 Provider `context_window` 与 `dual_output_max_tokens` 到 PDF2MD VLM 配置，并在 Provider 表单中提供显式配置。
- 已将 dual-output 实际预算限制为 Provider max、dual configured max 和 Context Window 可用预算三者最小值；4096、8192、16384 三档本地 mock 测试通过。
- 已修复 `full_glm_ocr` 的结果保留：GLM Markdown 可用但结构不足、随后 VLM dual 失败时，页面保留 GLM Markdown，不再直接抛出 `dual output json parse failed`。
- 已在页面决策结果中增加不含正文的 `vlm_budget` 摘要；日志记录预算数值和 cap 原因。
- 本地聚焦回归 78 项通过；Plan2 TypeScript/Vite 构建通过。未调用外部模型、未重建或重启容器、未部署、未提交。
- 待执行：经单独授权使用目标页做 4096/8192/16384 三档真实模型测试；根据证据决定是否进入 Goal 3 的分块提取。

## 1. 问题陈述

当前失败不是 MCP HTTP、图片清晰度或网络错误，而是两级提取策略连续失效：

```text
full_glm_ocr
  -> 已取得 OCR/Markdown，但 tables 结构为空
  -> glm_ocr_insufficient_structured_output
  -> full_vlm_ocr
  -> 一次请求 render + RAG + 全表行列 + 每单元格几何
  -> full_page_dual_output 固定最多 4096 output tokens
  -> JSON 截断或格式不完整
  -> dual output json parse failed
  -> 页面 FAILED
```

这类页面的关键矛盾是输出规模，而不是输入上下文不足。LLM Provider 中的 `context_window` 当前属于能力元数据，不会注入 PDF2MD 请求；实际注入的是 `max_tokens`。同时，`full_page_dual_output` 使用 `min(provider.max_tokens, 4096)`，所以即使 Provider 配置为 `max_tokens=20480`，该调用仍最多请求 4096 tokens。

## 2. 最终目标

对清晰、超出单次结构化输出预算的大型表格页：

1. 不丢弃 GLM-OCR 已取得的可信 Markdown。
2. 不要求单次 VLM 响应同时承载整页文本和数百个单元格几何。
3. JSON 结构化提取失败时，页面仍能以可审计的降级结果成功完成。
4. 只有经证据支持的结构化表格和几何信息才标记为完整。
5. 日志足以区分模型截断、非 JSON、空响应和结构缺失，但不记录文档正文、提示词、响应内容或凭证。

成功标准不是“提高 token 后偶尔成功”，而是固定大表 fixture 在受控 token 预算下稳定得到 Markdown 和明确的结构状态。

## 3. 范围与非范围

### 包含

1. `full_glm_ocr -> full_vlm_ocr` 的结果保留和回退顺序。
2. 大表输出预算估算及可预测的路由决策。
3. Markdown、表格结构和单元格几何的分阶段提取。
4. dual JSON 失败后的纯 Markdown 恢复。
5. 稳定错误码、最小指标日志和聚焦回归测试。
6. 澄清 `context_window` 与 `max_tokens` 在 PDF2MD 中的职责边界。

### 不包含

1. 不更换 GLM-OCR 或 VLM Provider。
2. 不依赖无限提高 `max_tokens` 解决大表。
3. 不允许模型猜测不可读单元格、合并关系或 bbox。
4. 不修改 Membership 表格持久化、Table Lookup 或 Review UI。
5. 不在计划阶段调用外部模型、重建或重启容器、部署、提交或重跑生产任务。
6. 不把 `context_window` 作为本次抽取失败的直接修复项。

## 4. 固定契约

### 4.1 Provider 参数语义

- `context_window`：输入与输出总上下文能力元数据，用于模型选择和请求预算校验；不得直接当作输出上限。
- `max_tokens`：单次请求允许的最大输出 tokens；PDF2MD 运行参数必须显式、可追踪地使用它或使用更小的任务级预算。
- `dual_output_max_tokens`：PDF2MD 整页 dual-output 的任务级输出预算；默认 4096，并受 Provider `max_tokens` 和上下文剩余预算共同限制。
- 自动检测值必须携带来源与可信度；模型自报、名称推断和默认值不能被展示为供应商已验证事实。
- 将 `context_window` 作为只读预算元数据注入 PDF2MD，但不得把它作为参数直接发送给 OpenAI-compatible API。
- dual-output 实际输出预算按以下原则计算：`min(provider.max_tokens, dual_output_max_tokens, context_window - estimated_input_tokens - safety_margin)`；无法可靠估算输入时必须保守降级，不得把 `context_window` 直接当作 `max_tokens`。

### 4.2 大表降级契约

按以下优先级保留结果：

```text
可信 GLM Markdown + 可信结构
  > 可信 GLM Markdown + 结构不完整状态
  > VLM 纯 Markdown + 结构不完整状态
  > 明确 FAILED
```

- 缺少 `tables` 结构不能抹掉已经通过基本质量检查的 GLM Markdown。
- `structured.complete=false` 与页面任务成功可以同时存在。
- 不得用空数组或空对象把结构缺失表示为完整成功。
- 大表的 `source_cells` 只能来自可靠布局结果或分块结果；不要求整页 VLM 一次生成全部单元格。

## 5. Goals Loop

每个 Goal 必须遵循：

```text
先建立失败测试
  -> 记录当前行为
  -> 实施最小改动
  -> 运行聚焦测试
  -> 检查输出契约和安全日志
  -> 未满足 Exit criteria 则留在当前 Goal
```

### Goal 1：冻结大表失败基线与预算证据

目标：在不调用真实模型的情况下，准确复现两级失败，并量化为何单次 dual JSON 不可行。

行动：

1. 以授权的最小裁剪/合成 fixture 表达约 10 列、60 行、合并单元格的页面特征，不提交商业文档整页内容。
2. Mock GLM 返回：Markdown 可用，但 `tables=[]`。
3. Mock VLM 返回：被截断的 dual JSON、代码围栏 JSON、纯 Markdown和空响应。
4. 记录请求预算、响应字符数、解析结果和稳定失败类别。
5. 增加静态断言，证明 Provider `max_tokens=20480` 时当前 dual 调用仍被限制为 4096。
6. 先贯通只读 `context_window` 和 `dual_output_max_tokens`，使用同一 mock 大表响应分别验证 4096、8192、16384 三档实际请求预算；该实验只判断增大输出预算是否改善完整 JSON 概率，不作为最终修复的替代。

验证：

- 测试可稳定复现 `glm_ocr_insufficient_structured_output -> dual output json parse failed`。
- 测试不依赖外部 API、网络或生产文件。
- 预算证据能说明问题来自输出契约规模，而不是 `context_window`。
- 三档实验能记录配置值、Provider 上限和最终 effective max；若上下文剩余预算更小，必须显示被再次压低。

Exit criteria：

- 失败链和至少四种 VLM 响应形态均有独立测试。
- 4096、8192、16384 三档预算行为均有确定性测试结果。
- 在修改实现前，现有失败断言明确且可重复。

### Goal 2：保留 GLM 可用 Markdown

目标：结构不完整时不丢弃已取得的页面内容。

行动：

1. 将 GLM Markdown 质量与结构完整性分开判定。
2. GLM Markdown 可用但缺表格结构时，保存其为候选 render，并记录 `table_structure` 缺失。
3. 后续 VLM 结构补全失败时回到该候选 render，而不是让整页失败。
4. GLM Markdown 本身为空、乱码或明显损坏时，仍按现有坏文本规则回退。

验证：

- “可用 Markdown + 空 tables + VLM 失败”返回页面成功、Markdown 保留、语义状态不完整。
- “坏 Markdown + 空 tables + VLM 失败”仍返回明确失败，不伪装成功。
- 普通 GLM 成功页输出不变。

Exit criteria：

- 可用内容不会因结构补全失败被覆盖或丢弃。
- 既有坏文本保护规则保持有效。

### Goal 3：将大表整页 dual 输出拆为有界阶段

目标：避免一次生成数百个单元格 JSON。

行动：

1. 在模型调用前使用确定性指标估算表格规模，例如文本量、行列候选数、表格占页比例和预计 JSON 开销。
2. 小表继续使用现有 dual 路径，避免扩大修改范围。
3. 超预算表按阶段执行：先取得/保留 Markdown，再提取最小表格元数据；单元格级结构仅在可靠且有界时处理。
4. 如需分块，按稳定行区间处理并保留表头上下文；合并结果必须检查列数、行序、重复行和缺失区间。
5. 不能可靠生成 `source_cells` 时省略该字段并标记结构不完整，不生成虚假 bbox。

验证：

- 固定大表 fixture 不再调用“整页文本 + 全部 source_cells”的单一响应契约。
- 小表 fixture 仍走原路径且结果兼容。
- 分块边界不会重复或遗漏数据行。

Exit criteria：

- 大表输出规模受确定性预算约束。
- 不以单纯提高 token 上限作为通过条件。

### Goal 4：补齐 dual 解析失败后的最终回退

目标：所有可恢复的响应都进入明确的降级路径。

行动：

1. 区分 `EMPTY_RESPONSE`、`INVALID_JSON`、`TRUNCATED_JSON`、`SCHEMA_INVALID` 和 `EMPTY_RENDER`。
2. dual JSON 解析失败后允许执行现有纯 Markdown 回退，而不是在 `full_page_dual_output` 内提前终止整个页面。
3. 若 VLM 返回纯 Markdown，使用现有可信度规则恢复 render。
4. 若 GLM 候选 Markdown 更可信，优先保留 GLM 结果，避免低质量 VLM 覆盖。

验证：

- 截断 JSON、围栏 JSON、纯 Markdown、空响应各有确定结果。
- 回退调用次数有上限，不形成 GLM/VLM 重试循环。
- 两个来源都不可用时仍返回稳定错误，而不是空成功。

Exit criteria：

- 大表页至少可保住可信 Markdown。
- 每种失败类别都能从状态中判断最终采用了哪个来源。

### Goal 5：安全可观测性与 Provider 预算边界

目标：下次无需记录正文即可判断真实失败原因，并防止 UI 参数造成误解。

行动：

1. INFO 日志仅记录 task/page、route、provider/model、请求 `max_tokens`、响应字符数、`finish_reason`、解析类别、对象数量和最终来源。
2. 不记录 prompt、响应正文、页面正文、图片、凭证、异常中的供应商响应体。
3. 在运行结果中暴露稳定的预算摘要：provider max、context window、dual configured max、task effective max、是否及为何被 cap。
4. 为 `context_window` 增加来源语义测试：`predefined`、`llm_query`、`name_inference` 或 `default`；未验证值不得标成可靠自动探测。
5. MCP 注入新增 `context_window` 和 `dual_output_max_tokens` 时仍保持最小集合；两者仅用于 PDF2MD 本地预算检查，不直接传给 OpenAI-compatible API。

验证：

- 日志能回答“是否截断、实际请求多少 tokens、哪个回退被采用”。
- 日志和任务结果中不出现正文或凭证。
- UI 的 `Context Window` 与 `Max Tokens` 在测试中保持不同语义。

Exit criteria：

- 诊断所需指标齐全且满足最小化日志要求。
- 自动检测的可信度不会被 UI 状态 `Detected` 掩盖。

### Goal 6：回归、真实页验收与发布门槛

目标：在部署前证明修复既解决大表，又不破坏普通页。

行动：

1. 运行 PDF2MD Enhanced 现有聚焦测试及新增的大表测试。
2. 检查小表、公式页、图形页、纯文本页和坏文本页的兼容性。
3. 经单独授权后，使用目标页副本进行一次真实模型验收；不直接覆盖既有生产任务。
4. 对照 Markdown 行数、表头、首末数据组、结构状态、route 和模型调用次数。
5. 部署和生产重跑必须另行授权，并保留回滚镜像/版本。

验证：

- 目标页不再以 `dual output json parse failed` 结束。
- 至少保留完整可读 Markdown；结构不完整时状态明确。
- 普通 fixture 输出契约无非预期变化。

Exit criteria：

- 本地全部聚焦测试通过。
- 真实页验收满足内容保留、状态诚实、日志安全三项要求。
- 未取得部署授权前停止，不重建或重启生产容器。

## 6. 建议实施顺序与提交边界

1. Goal 1 单独建立失败测试和预算证据。
2. Goal 2 与 Goal 4 作为最小可靠性修复，可在同一代码提交中完成。
3. Goal 3 的大表分阶段/分块属于独立提交，避免与基础回退混杂。
4. Goal 5 的日志和 Provider 元数据语义独立提交。
5. Goal 6 只做验证记录；部署、生产重跑和提交均需用户分别确认。

## 7. 执行前确认点

执行时默认采用以下取舍：

1. 第一优先级是“不丢页面 Markdown”，第二优先级才是完整单元格结构。
2. 不因截图中 `context_window=4096` 直接修改模型配置；先贯通该字段并通过日志确认预算行为。
3. 先用 `dual_output_max_tokens=4096/8192/16384` 做受控测试，但不把 Provider `max_tokens` 无限制传给大表 dual 请求；实验后仍以拆分输出契约为正式方向。
4. 如 GLM 已返回可信 Markdown，VLM 仅负责补缺，不拥有无条件覆盖权。
5. 任何结构化缺失都显式标记，不把降级结果伪装成完整提取。
