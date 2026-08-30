# PDF2MD 正常上传 Layout / Mixed-page Goals Loop

日期：2026-08-30
状态：Executing（Goals 0–3 与 Goal 4 本地验收已完成；真实模型、构建与发布未授权）
主责任：`AICMDEngine/mcp/servers/PDF2MDEnhanced`
兼容边界：Membership / DocIntel 既有入库、语义描述、稳定 ID、占位回填、RAG、问答与 Review 消费链保持不变
当前授权边界：已授权 PDF2MD 正常上传实现和本地 mocked 测试；不修改 Membership、不提交、不构建/部署、不调用真实模型

执行记录（2026-08-30）：

- Goal 0：已确认当前主链为 `process_task_page -> page_processor.process_page`；未提交候选仅供逐项审查，未整体复制或合并。
- Goal 1：已在正常上传主入口接入 `pdf2md-layout-ledger-v1`；layout 成功时驱动对象输出，layout 不可用时保留 legacy 输出并显式标为 reconciliation incomplete。
- Goals 2–3：Membership 兼容证据支持零改动；本地 mocked 测试覆盖两表、图+表、图+公式、表+图+公式、单项失败继续、unknown、bbox 和 rollback。
- Goal 4（本地部分）：临时一页 PDF 已通过 `start_task -> process_task_page -> TaskManager` 持久化与 `finalize_task` mocked 链路；layout/reconciliation 被保留，legacy RAG 汇总 shape 不变。真实模型与用户指定原文档仍待单独授权。
- 当前验证：99 项相关测试通过，`py_compile` 与 `git diff --check` 通过。
- Goal 5：未进入；真实授权验收、发布审查、构建与部署均为后续门槛。
- 未执行：真实模型、真实文档、构建、容器、部署、提交和 Membership 修改。

## 1. 问题陈述

当前正常上传链路是：

```text
start_task
  -> process_task_page
     -> page_processor.process_page
        -> route / OCR / VLM
        -> render.markdown
        -> rag.page_text + rag.elements.{tables,formulas,figures}
  -> TaskManager 持久化 page_result
  -> finalize_task 汇总 rag
  -> Membership 既有消费链
```

现状中，`process_task_page` 的结构完整性仍由 legacy `rag.elements` / top-level `elements` 三个成功数组间接表达；`page_processor.process_page` 没有把 layout 的对象类型、阅读顺序和位置作为页面对象的权威清单。`decision.layout_probe` 只在调试开关下记录探针结果，不承担编排或完整性对账。

因此，某一类或某一个对象提取失败时，空数组无法区分“页面没有该对象”和“layout 已发现该对象但提取失败”。围绕表格做 DPI 回退、按表编号拆分或紧凑重试，也无法证明同页后续的图、公式或第二张表没有被遗漏。

第 24、25 页的两表情况仅作为基线样本。要解决的是任意混合页：两表、图+表、图+公式、表+图+公式，以及这些页面上任意单个对象失败后的继续处理和完整对账。

## 2. 已确认前提与非目标

### 2.1 已确认前提

1. Membership 已提交的消费链是本计划的兼容基线：保留正常页面文字以及表、图、公式对象；用同页文字生成语义描述；为三类对象生成稳定 ID；用语义描述占位回到原阅读位置；随后进入 RAG、问答和 Review。
2. 图形当前只展示 `[FIGURE:id]` 与语义描述。没有图片裁剪、原图回填或 S3 对象，是已知且接受的现状。
3. `rag.elements.tables|formulas|figures` 和 top-level `elements` 必须继续作为成功对象的 legacy 兼容视图，直到单独批准契约迁移。
4. `POST /mcp 200 OK` 只表示协议调用成功；页面对象完整性必须由页面结果中的 ledger 与 reconciliation 判断。

### 2.2 非目标

1. 不修改 Membership 既有表、图、公式入库模型、语义描述生成、稳定 ID 规则、占位格式、RAG、问答或 Review 行为。
2. 不实现图片裁剪、图片二进制回填、S3 上传/下载或图片预览。
3. 不把表格专用恢复、DPI 回退、按表号拆分或第 24/25 页条件判断提升为主流程。
4. 不更换 OCR/VLM 供应商，不重写当前路由策略，不顺带重构 Markdown 清洗、表格规范化或任务状态体系。
5. 不用增加 token 预算或一次真实模型成功代替对象级完整性证明。
6. 不修改 MCP Router、Membership 或部署配置，除非后续 Goal 的证据证明契约无法兼容，并获得对应仓库的单独授权。
7. 本计划不采纳、提交或合并任何现存未提交 worktree 修改。

## 3. 当前基线与待审查候选

### 3.1 当前已提交基线

- `server.process_task_page` 直接调用 `page_processor.process_page`，随后由 `TaskManager.update_page_result` 保存结果。
- `page_processor.process_page` 按路由生成 `render.markdown`、`rag.page_text` 和结构化数组；`_build_output_elements` 只为成功返回的表、图、公式生成 legacy 对象。
- `TaskManager.finalize_task` 汇总已完成页的 `rag`，不会基于 layout ledger 复核对象数量。
- 单页工具 `analyze_page_layout` / `extract_page_layout_enhanced` 能返回 layout blocks，但 README 明确这些是单页补漏工具，不改变 `start_task` / `process_task_page` 主上传契约。

### 3.2 未提交 worktree 只能作为候选

“恢复 layout 驱动的页面结构提取”任务报告称，另一个未提交 worktree 修改了：

- `mcp/servers/PDF2MDEnhanced/single_page_tools.py`
- `mcp/servers/PDF2MDEnhanced/README.md`
- `tests/test_pdf2md_enhanced_single_page_tools.py`

报告还称其为单页 structured/layout 工具增加了 ledger、reconciliation、两表和混合失败隔离测试。上述内容没有在本 checkout 逐行审查或复跑，且报告范围没有证明 `page_processor.process_page` 的正常上传链路已经接入。因此：

1. 不把该候选实现或其测试结果当作已验证事实。
2. Goal 0 必须先审计完整 diff，区分可复用的契约/纯函数/fixture 与只适用于单页补漏的代码。
3. 禁止整分支合并、整文件覆盖或默认 cherry-pick；只允许在用户批准后按已验证失败测试逐块采纳最小代码。
4. 即使候选单页测试全部通过，也不能替代 `process_task_page` 主上传回归。

## 4. 页面 Layout Ledger 契约

### 4.1 契约位置与兼容策略

正常上传的 `page_result` 新增两个加法字段：

```text
page_result.layout              # 权威页面对象 ledger，按阅读顺序排列
page_result.reconciliation      # ledger 与成功对象视图的对账结果
```

以下现有字段保持兼容：

```text
page_result.render.markdown
page_result.rag.page_text
page_result.rag.content
page_result.rag.elements.tables|formulas|figures
page_result.elements.tables|formulas|figures
```

legacy typed arrays 只包含成功对象，并由 `layout_id` 回链 ledger。空数组不再能单独证明页面没有该类型；AICMDEngine 的完整性判定必须读取 `layout` / `reconciliation`。

### 4.2 页面级元数据

```json
{
  "layout_status": "EXTRACTED",
  "layout_version": "pdf2md-layout-ledger-v1",
  "bbox_space": "normalized_page",
  "page_width": 1.0,
  "page_height": 1.0,
  "layout": [],
  "reconciliation": {}
}
```

要求：

1. `layout_status` 的终态只有 `EXTRACTED` 或 `FAILED`。layout pass 失败时不得用空 ledger 表示“无对象”。
2. 权威 bbox 使用 `[x0, y0, x1, y1]`，坐标空间固定为 `normalized_page`，四值满足 `0 <= x0 < x1 <= 1`、`0 <= y0 < y1 <= 1`。若保留供应商原始坐标，只能放在去敏诊断字段，不能让消费者猜测坐标空间。
3. 空白页由既有 blank route 明确标记；只有明确空白页才允许 `layout=[]` 且 reconciliation complete。
4. 非空页 layout pass 失败时，保留可用 `render.markdown` / `rag.page_text`，但 `reconciliation.complete=false`，不能伪装为结构完整。

### 4.3 Ledger item

建议最小 shape：

```json
{
  "layout_id": "p24-o003-table",
  "source_block_index": 7,
  "type": "table",
  "layout_type": "table",
  "reading_order": 3,
  "bbox": [0.08, 0.31, 0.92, 0.56],
  "status": "EXTRACTED",
  "content": "<table>...</table>",
  "payload_ref": {"collection": "tables", "index": 0},
  "error": null
}
```

字段要求：

- `layout_id`：页面结果内唯一、确定生成的相关键；用于 ledger 与 typed arrays 对账。Membership 既有稳定对象 ID 仍由 Membership 生成，不能被 `layout_id` 替代。
- `source_block_index`：保留供应商 block 标识供审计，不作为阅读顺序。
- `type`：规范类型 `text|table|figure|formula|unknown`。供应商的 `title`、`paragraph`、`caption` 等文本型标签归一为 `text`，原标签保存在 `layout_type`。无法安全映射的对象保留为 `unknown` 并显式失败，不能删除。
- `reading_order`：从 1 开始、页面内唯一且连续；这是插入占位和验证顺序的权威字段，不能依赖 typed array 顺序或表号。
- `bbox`：规范化页面坐标。bbox 缺失/非法的已识别语义对象必须进入 `FAILED`，错误码为 `layout_bbox_missing` 或 `layout_bbox_invalid`；不能静默丢弃。
- `status`：ledger 输出终态为 `EXTRACTED|FAILED`。内部可有 pending 状态，但不得出现在最终成功响应中。
- `content`：text 为原阅读块文字；table 为可审计的 Markdown/HTML；formula 为原始/LaTeX；figure 为 caption/layout hint。它不是 Membership 语义描述的替代物。
- `payload_ref`：成功语义对象指向 legacy typed array；text 可为 `null`，其文字仍进入页面文本/Markdown。
- `error`：成功时 `null`；失败时至少含稳定 `code`、`stage`、`retryable`。消息必须去敏，不记录全文、提示词、模型响应、图片或凭证。

typed array 对象最小新增 `layout_id`、`reading_order`、`bbox`、`bbox_space`；其现有 title/markdown/latex/description/context 等字段保持不变。

### 4.4 Reconciliation

```json
{
  "identified": 6,
  "extracted": 5,
  "failed": 1,
  "by_type": {
    "text": {"identified": 2, "extracted": 2, "failed": 0},
    "table": {"identified": 2, "extracted": 1, "failed": 1},
    "figure": {"identified": 1, "extracted": 1, "failed": 0},
    "formula": {"identified": 1, "extracted": 1, "failed": 0}
  },
  "unmatched_layout_ids": [],
  "unmatched_payload_layout_ids": [],
  "duplicate_layout_ids": [],
  "accounted_for": true,
  "complete": false
}
```

不变量：

1. `identified == extracted + failed`。
2. 每个 ledger item 恰有一个终态；每个成功语义 item 恰有一个 typed payload；每个 typed payload 恰好回链一个成功 ledger item。
3. `accounted_for=true` 表示没有静默遗漏或重复，即使存在明确失败。
4. `complete=true` 仅当 `layout_status=EXTRACTED`、`accounted_for=true`、`failed=0`。
5. 一个对象失败后，同页其它对象仍继续处理；页面可以 `accounted_for=true` 且 `complete=false`。
6. layout 自身失败时，`identified` 不得伪装为可信的 0；必须有页面级 error，`accounted_for=false`、`complete=false`。

## 5. 正常上传责任边界

### 5.1 AICMDEngine 负责

1. 对每个非空正常上传页先取得一次权威 layout 清单，再决定语义对象提取，而不是先分别猜测表、图、公式是否存在。
2. 规范化类型、阅读顺序和 bbox，创建 ledger 并为每项初始化终态责任。
3. 优先用一次整页或有界 batch 完成对象提取；只对 ledger 中尚未完成的对象做按 block/小 batch 恢复。
4. 表格紧凑重试只可用于 ledger 已确认的 table block；它不能决定页面主流程，也不能重新枚举页面表数。
5. 单个 block 的超时、截断、空内容或解析错误，只更新该 item 为 `FAILED`；循环继续处理其它对象。
6. 从成功 ledger items 派生现有 `rag.elements` / `elements`，保持 Membership 可消费字段不变。
7. 生成 reconciliation，并在保存 page_result 前执行不变量校验。校验失败必须显式标记页面结构不完整。
8. 保留当前 VLM `finish_reason`、截断与预算诊断，但日志只记录页码、layout_id、类型、状态、错误码和响应形状。

### 5.2 Membership 负责且本计划不改变

1. 继续消费页面文字以及成功的表、图、公式 legacy arrays。
2. 继续基于同页文字生成语义描述，生成既有稳定对象 ID 与占位，并进入既有 RAG、问答和 Review。
3. 图仍只显示 `[FIGURE:id]` 与描述，不要求图片二进制或 S3 key。

### 5.3 明确不由 Membership 补偿

Membership 不负责重新做 layout、推断漏掉的对象数量、按表号拆页、重试 OCR/VLM 或从空数组猜测失败。识别完整性与失败隔离必须在 AICMDEngine 的 `process_task_page` 返回前完成。

## 6. Goals Loop

每个 Goal 都遵循：

```text
冻结基线/失败断言
  -> 实施该 Goal 的最小变更
  -> 聚焦验证
  -> 检查 ledger/legacy 输出/失败隔离
  -> 未满足 Exit criteria 则留在本 Goal
  -> 用户审查后才进入下一提交或外部环境
```

### Goal 0：冻结正常上传基线并审查候选

目标：证明首次缺口在 `process_task_page -> page_processor.process_page`，冻结兼容输出和 fixture 期望；在此之前不修改实现。

行动：

1. 记录当前 checkout、HEAD、dirty paths 和已提交 transport/截断诊断能力。
2. 用 mocked OCR/VLM 响应追踪 `start_task -> process_task_page -> TaskManager page_result -> finalize_task`。
3. 为第 24/25 页样本或等价脱敏 fixture 记录 layout 期望清单，不执行真实模型。
4. 对现有输出保存去敏 golden：`render.markdown`、`rag.page_text`、typed arrays 的字段 shape。
5. 审查未提交候选 diff，列出可复用纯函数、测试和不适用于主上传的部分；不复制实现后再补理由。

验证：

- 测试可复现：layout fixture 有两个 table blocks，而现有正常上传只有 legacy arrays，无法表达某一 table 失败仍被识别。
- 证明单页 `extract_page_layout_enhanced` 不在正常上传调用链。
- Membership 兼容 golden 明确哪些字段不得变化。

Exit criteria：首次丢失/不可判定边界明确；四类 fixture 的期望 ledger 已冻结；候选 diff 有逐项审查记录。

最小改动边界：仅测试、脱敏 fixture 和基线说明。
禁止事项：不改路由、OCR/VLM、page result；不调用真实模型。
提交边界：经用户批准后可单独提交“基线 fixture/tests”；不得与功能实现混提。
回滚：删除该独立测试提交即可，不影响运行时。

### Goal 1：让正常上传以 Layout Ledger 编排混合页

目标：`process_task_page` 返回的 layout 成为对象完整性的权威，同时保持现有成功对象输出兼容。

行动：

1. 在 `page_processor.process_page` 的一次页面生命周期内接入 layout pass；复用经 Goal 0 审查的 normalization helper，避免调用单页 MCP 工具形成内部协议跳转。
2. 按规范类型和 `reading_order` 初始化 ledger；文本、表、图、公式全部入账。
3. 对 ledger-confirmed 语义对象做整页/有界 batch 提取，再仅恢复缺失 block；每次恢复只更新目标 item。
4. 从成功 ledger item 构建 typed arrays；继续运行现有 Markdown、page_text、table normalization 和 semantic fields 逻辑。
5. 计算 reconciliation 并校验不变量；为失败 item 保留 bbox、类型、顺序和稳定错误。
6. layout 失败时保住可信页面文字，但显式返回 incomplete；不得把空 ledger 当作成功。

验证：

- 两表 fixture 的 ledger 有两个不同 `layout_id`，reading_order 和 bbox 正确，两个 typed payload 均可回链。
- 强制第一张表失败后，第二张表、后续 text/figure/formula 仍处理；failed item 不出现在成功数组，但保留于 ledger。
- legacy golden 的必填字段、页面文字和已有 semantic fields 不回退。
- reconciliation 的计数和双向关联不变量有单元测试。

Exit criteria：主上传 mocked 测试证明 `layout` 是权威清单；所有识别对象均为 `EXTRACTED` 或 `FAILED`；没有因一个失败而提前返回/跳过后续对象。

最小改动边界：优先只改 `page_processor.py`、必要的 layout normalization 模块和对应测试；如复用 single-page helper，只抽出无 I/O 的共享纯函数。
禁止事项：不改 Membership；不新增表号/DPI/page-number 特例；不删除 transport 与 VLM 截断诊断；不重写路由。
提交边界：用户批准且聚焦测试通过后，AICMDEngine 主上传实现单独提交；候选 worktree 不整体合并。
回滚：用配置开关关闭 ledger-driven orchestration，回到当前 committed route/legacy arrays；新增字段为加法字段，旧消费者不需数据迁移。

### Goal 2：Membership 兼容性证明；仅在有证据时提出最小适配

目标：默认零 Membership 改动。只有契约兼容测试证明现有消费者无法忽略/传递加法字段，才形成单独、可拒绝的最小适配提案。

行动：

1. 用 Goal 0 golden 验证 Membership 所需的 `render.markdown`、`rag.page_text` 和三个 typed arrays shape 不变。
2. 验证成功对象继续带现有 title/markdown/latex/description/context，并只增加可忽略的 layout 关联字段。
3. 验证 `reconciliation.complete=false` 不会导致 Membership 丢弃同页其它成功对象。
4. 若现有 DTO 严格拒绝未知字段或成功对象无法被保留，记录精确丢失边界、文件与失败测试，再请求 Membership 仓库单独授权。

验证：

- 首选结果：Membership 兼容测试通过，代码变更为 0。
- 若不通过：最小提案只能是 DTO/adapter 接受加法字段或保留部分成功对象；不得改入库、语义描述、ID、占位、RAG、问答或 Review 业务规则。

Exit criteria：有证据证明零改动兼容，或用户明确批准一个独立的最小适配 Goal；没有证据时不得修改 Membership。

最小改动边界：默认无代码；必要时仅跨边界 DTO/adapter。
禁止事项：不改变任何已确认正确的 Membership 消费语义；不在 AICMDEngine 提交中夹带 Membership。
提交边界：若确需适配，必须在 Membership 仓库单独测试、单独审查、单独提交；本计划当前不授权该提交。
回滚：回滚独立 adapter 提交；AICMDEngine 仍保留 legacy arrays，不需回滚已入库数据。

### Goal 3：混合页面 Fixture 与失败隔离矩阵

目标：用本地脱敏 fixture 和 mocked 模型覆盖用户指定组合，证明对象数、顺序、位置和失败不会相互阻断。

行动：

1. 冻结下面矩阵的 layout response、对象 extraction response 和期望 page_result。
2. 每个 fixture 至少包含一个前置/后续 text block，以验证对象仍回到原 reading order。
3. 每个组合同时测试全部成功和一个对象失败；三对象混合页至少分别注入 table、figure、formula 失败。
4. 覆盖 layout 成功但对象空内容、解析异常、`finish_reason=length`、bbox 非法、typed payload 无匹配 ledger 等情况。
5. 对专用 table compact retry 只断言其作用于目标 table layout_id，不影响其它对象。

验证矩阵：

| Fixture | Layout 顺序示例 | 成功断言 | 失败注入与隔离断言 |
|---|---|---|---|
| 用户文档第 24/25 页或脱敏等价页：两表 | text → table A → text → table B → text | 两个 table layout_id、两个 payload、顺序/bbox/计数一致 | A 失败时 B 与后续 text 仍 EXTRACTED；反向也测 |
| 图+表 | text → figure → text → table | figure/table 均有独立 bbox 和 payload_ref | figure 描述失败不阻断 table；table 失败不阻断 figure |
| 图+公式 | text → figure → formula → text | figure/formula 均成功且占位顺序可由 reading_order 重建 | 任一失败时另一对象与后续 text 仍成功 |
| 表+图+公式 | text → table → figure → formula → text | 四类 ledger 全部入账，三个成功数组双向可对账 | 分别注入 table/figure/formula 失败；每次只产生一个 FAILED，其他对象继续 |

每个 fixture 必须记录：来源类型、脱敏说明、fixture hash、页码、期望 block 数、规范类型、reading_order、bbox、成功/失败状态、错误码和 reconciliation。真实商业文档全文不得写入测试日志或 snapshot。

Exit criteria：矩阵全部 mocked 测试通过；`identified=extracted+failed`；每个失败用例均证明“一个失败不阻断同页其他对象”。

最小改动边界：仅测试文件、最小脱敏 fixture 和必要测试 helper。
禁止事项：不使用仅含两表的测试替代混合矩阵；不联网、不调用真实模型、不依赖容器。
提交边界：fixture/tests 可与 Goal 1 功能提交分开，便于先审查失败断言；不得提交未授权原始 PDF。
回滚：删除 fixture/test 提交，不改变生产代码或数据。

### Goal 4：端到端本地验收与真实模型授权门槛

目标：先在本地 mock/stub 环境证明完整任务链，再在用户单独授权后用指定文档做真实模型验收。

行动：

1. 本地无真实模型：执行 `start_task -> process_task_page -> get_task_status/finalize_task`，检查持久化 page_result、merged rag、ledger 和 legacy arrays。
2. 本地兼容验收：使用 Membership contract fixture/录制 payload 验证页面文字和所有成功对象仍进入既有链；不启动、修改或部署 Membership。
3. 形成真实验收申请，列明文档 hash、页码、模型/provider、预计调用次数、日志去敏和停止条件。
4. 只有用户明确批准后，才调用真实模型测试用户指定第 24/25 页及至少一个三类混合页。
5. 真实结果逐对象与原 PDF 人工核对，不以模型自报计数或 HTTP 200 为准。

验证：

- 本地任务结果落盘后仍可由 finalize 汇总，失败 item 不污染成功数组，也不丢其它成功对象。
- 真实授权验收时比较原页 layout 清单、page_result、Membership 接收 payload 和 Review 可见对象；若 Membership 未运行，则只报告到可证明的边界，不宣称端到端通过。
- 图形验收只检查 `[FIGURE:id]` + 描述和原页定位，不检查裁图/S3。

Exit criteria：本地完整链通过；真实模型验收必须单独获批且所有混合页逐项可解释。未获授权时 Goal 4 停在“本地通过、真实待验收”，不能进入发布。

最小改动边界：验收脚本/记录；不为让真实样本通过而加入页面特例。
禁止事项：当前计划阶段不运行测试、不调用模型、不启动容器；未来也不得在一次授权外扩展文档或页码。
提交边界：验收记录可独立提交；真实输出若含文档内容不得入库。
回滚：清理临时任务产物；不修改业务数据。若验收失败，回到对应 Goal，不部署。

### Goal 5：发布门槛、分阶段启用与运行回滚

目标：只有契约、回归、兼容和真实验收都达标后，才允许发布 layout-driven 主上传。

行动：

1. 汇总测试：layout normalization、ledger/reconciliation、主上传 route、任务持久化、四类 fixture、legacy contract。
2. 增加只记录计数/错误码的运行指标：页面 complete/partial、按类型 identified/extracted/failed、unmatched、layout pass failure。
3. 用配置开关分阶段启用：默认旧链 -> 指定测试任务 -> 受控租户/环境 -> 全量；每阶段都能回退。
4. 定义阻断阈值：任何 unmatched/duplicate、typed payload 无 ledger、layout 失败被视为空页、单对象失败导致后续对象缺失，都阻断发布。
5. 构建、容器重启、部署和生产真实文档执行分别请求授权；本计划不提供这些授权。

验证：

- 全部本地聚焦回归和 contract tests 通过，`git diff --check` 通过，dirty paths 与批准范围一致。
- 真实授权样本无静默遗漏；部分失败页 `accounted_for=true/complete=false`，成功对象仍可消费。
- 关闭 feature flag 后输出恢复到当前 legacy 行为，不需要数据迁移或删除已有记录。

Exit criteria：所有发布阻断项为 0；用户审查实现 diff、测试证据和真实验收证据后另行批准构建/部署。

最小改动边界：配置开关、指标和运行文档；不引入新存储系统。
禁止事项：不以 fixture-only 通过宣称可发布；不自动启用全量；不在发布提交中夹带 Membership 或裁图/S3。
提交边界：实现、测试、可观测性分别保持可审查提交；部署变更另行授权和记录。
回滚：关闭开关并恢复上一 AICMDEngine artifact；保留 legacy arrays；不回滚/删除 Membership 已有正确对象。

## 7. 总体提交与授权顺序

```text
用户批准本计划
  -> Goal 0 基线测试提交（可选、独立）
  -> Goal 1 AICMDEngine 主上传实现提交
  -> Goal 2 零改动兼容证明；若失败则暂停并申请 Membership 授权
  -> Goal 3 fixture/失败隔离测试提交
  -> Goal 4 本地验收
  -> 用户单独授权真实模型验收
  -> Goal 5 发布审查
  -> 用户单独授权构建/部署/启用
```

任何 Goal 未满足 Exit criteria，都不能用下一 Goal 的操作掩盖；尤其不得用部署观察替代本地失败测试，不得用真实模型偶然成功替代 reconciliation 不变量。

## 8. 待用户审查的关键决策

1. **兼容策略**：是否同意 `page_result.layout` / `reconciliation` 为新增权威字段，同时保留 legacy typed arrays 作为成功对象视图。
2. **坐标契约**：是否同意强制统一为 `normalized_page [x0,y0,x1,y1]`；bbox 缺失的语义对象显式 FAILED，而不是继续输出无位置的成功对象。
3. **完成语义**：是否同意同时区分 `accounted_for`（无静默遗漏）与 `complete`（所有对象成功），允许部分失败页保留其它成功对象。
4. **Membership 边界**：是否确认 Goal 2 默认零改动；只有严格兼容测试失败并再次授权时，才做独立 DTO/adapter 适配。
5. **候选 worktree**：是否同意只按 Goal 0 的逐项审查结果复用小块，不整体合并当前未提交 layout 候选。
6. **验收样本**：请在实施前确认第 24/25 页所属文档及一个表+图+公式页面；若原件不可进入测试仓库，则制作 hash 可追溯的脱敏 fixture。
7. **真实/发布授权**：真实模型调用、构建、容器操作和部署继续保持四个独立授权门槛。
