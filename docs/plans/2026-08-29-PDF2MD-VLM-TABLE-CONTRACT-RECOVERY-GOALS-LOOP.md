# PDF2MD Enhanced VLM Table Contract Recovery Goals Loop

日期：2026-08-29
状态：Completed locally（未调用外部模型、未构建/重启/部署）
范围：仅 `mcp/servers/PDF2MDEnhanced` 的 `extract_page_tables` VLM prompt、响应归一化与聚焦测试。

## Goal

当 GLM/native table 未取得表格、VLM 对整页返回结构化 JSON 或合法 Markdown 表时，`extract_page_tables` 必须输出现有调用方可消费的非空 `tables/items` 契约，而不是 `vlm_ocr_returned_no_tables`。

固定金标为 GB/T 16749 第 12 页表 3：逻辑矩阵共 16 列（材料 + 427..816）和 5 条数据行，保留可见表题、说明与脚注。复杂表头可以展平，不要求视觉 `colspan`。

## Verified baseline

- 实际调用 prompt 主要使用中文，要求顶层单表 strict JSON、`columns`、`normalized_rows`，并附文本层上下文；描述语言指令由 `description_language` 决定。
- `extract_page_tables` 的 MCP 默认 `output_format=json`、`table_rows_format=structured_json`。
- VLM 请求使用注入的 provider/model/base URL，`max_tokens=min(provider max_tokens, 4096)`，temperature 为注入值（默认 `0.1`），先 stream、无有效内容或异常时再 non-stream。
- `normalize_text_response` 优先解析 JSON；非 JSON 响应只进入 `markdown/page_text`。后续 fallback 只恢复已有 separator 的 Markdown 表或 HTML 表，因此某些 Qwen 表格响应会得到空 `tables` 并记录 `vlm_ocr_returned_no_tables`。
- 当前运行日志不记录 prompt 或响应正文；已确认两次 VLM-only 调用仅返回约 256 字符且 `item_sources=[]`，说明专用抽取响应没有形成可消费表格，但无法从日志还原其具体原文。用户直接调用 Qwen 得到的完整整页响应作为能力金标 fixture，不冒充上述工具调用的原始响应，也不调用外部模型。

## Non-goals

- 不修改 Membership API/UI、MCP Router、普通文档 pipeline、公式或图片抽取。
- 不调用外部模型，不更换 provider/model，不调整 FastMCP body limit。
- 不构建镜像、不重启、不部署、不提交。
- 不把页后 `4.4` 公式正文误收为表说明或脚注。

## Loop

### Phase 1 — Red contract

1. 冻结实际 prompt/schema/model-budget 断言。
2. 用 page 12 的 16 列、5 行 Qwen 响应 fixture 重现旧 fallback 的双层表头误解析、题名退化及表注/脚注丢失。
3. 断言输出必须有唯一表项、表题、完整行列、Markdown、说明/脚注，且 `4.4` 正文不进入 notes/footnotes。

Exit：测试在旧 parser 上因逻辑列/数据行、题名及 metadata 契约不符而失败；运行态空表另有 VLM-only 日志证据，二者共同锁定 prompt/响应契约与 fallback 能力缺口。

### Phase 2 — Minimal recovery

1. Prompt 以 `tables:[...]` 为唯一首选 envelope，明确 title/description/notes/footnotes 字段，并继续接受现有顶层单表结构。
2. 归一化优先接受结构化 JSON：`tables`/`items`、顶层单表、`normalized_rows`/`rows`。
3. JSON 不可用时，仅恢复合法 Markdown 表块；从紧邻表格的题名、说明、脚注提取 metadata，遇到下一节标题（如 `4.4`）立即停止。
4. 输出继续经过 `_table_item`，保持 `items/tables`、`columns`、`normalized_rows/rows`、`markdown`、`tableRowsContent` 兼容。

Exit：金标和既有单页表格测试通过；正文不被误归类。

### Phase 3 — Verification and handoff

1. 运行 PDF2MD Enhanced 单页工具聚焦测试。
2. 运行相关 bad-text/structured extraction 回归。
3. `git diff --check` 并确认只改 PDF2MD Enhanced 计划、parser/prompt 和测试。

Exit：报告差异、测试和仅需重建 `pdf2md-enhanced`；停止在构建镜像、重启、提交之前。

## Risks and rollback

- Markdown pipe 可能出现在普通正文；只接受含合法 separator、至少两列且至少一条数据行的表块。
- 说明/脚注边界可能吞入后续正文；只取表块后的连续说明/脚注行，遇到 Markdown/数字章节标题立即停止。
- 模型可能输出多表；保留返回顺序和每个独立 table object，不合并、不猜对应 Membership element ID。
- 回滚为撤销本计划对应 parser/prompt/test 变更；无数据迁移或运行态回滚。

## Execution record

- 红测先在旧逻辑上失败：mixed Qwen Markdown 虽能找到 pipe 表块，但两层表头被解析为错误列结构并多出一条“数据行”，表题退化为前三个表头，且表注/脚注没有契约字段。
- prompt 已统一为 `tables:[...]` JSON envelope，并明确 title/description/notes/footnotes 与后续章节停止规则。
- parser 保留 JSON 优先，新增顶层 `rows` 矩阵兼容；Markdown fallback 仅围绕合法表块提取题名、表注和脚注，并在 `4.4` 标题前停止。
- 金标输出为 16 列、5 数据行、1 条表注、6 条脚注；`4.4` 及其公式正文未进入表 metadata。
- 本地聚焦回归：`tests/test_pdf2md_enhanced_single_page_tools.py` + `tests/test_pdf2md_enhanced_bad_text_policy.py` 共 70 项通过。
