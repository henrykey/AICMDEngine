# PDF2MD Object-crop Structured Recovery Goals Loop

日期：2026-08-31

状态：本地实现与验证完成；真实E2E、Membership集成及部署待单独授权。

执行目录：`/Users/kehongwei/workspace/AICMDEngine`。
基线：`02a5c06`，工作树干净；保留其无 API key 自托管 OCR 支持。此前恢复提交为 `ab6004581`。

## 1. 问题、证据与成功定义

正常上传为 `process_task_page -> page_processor.process_page -> TaskManager`。整页 GLM layout 已经提供 text/table/figure/formula/unknown、稳定 layout_id、reading_order 和 normalized bbox；它是页面对象权威清单。layout 成功不等于所有对象内容已提取完整。

2026-08-31 北京时间 08:36 的既有运行证据（只读取得，不重放模型）：

| 样本 | 任务 | layout | 第二表原内容 | 临时裁图 | 恢复结果 |
|---|---|---|---|---|---|
| GBT16749-2018-p10-p39.pdf 第16页 | task_d8cf3224c1c5db92 | 2 text + 2 table | 350字符，无闭合table | 4338×2652 | GLM/VLM均 invalid_recovered_content |
| 同文档第17页 | task_f17ed0d474faa28b | 2 text + 2 table | 393字符，无闭合table | 4342×3677 | GLM/VLM均 invalid_recovered_content |

两页第二表均为 `p1-o004-table`（输入是原文档单页副本），原始 source page 16/17 由调用方映射。两页 reconciliation 均 table identified=2/extracted=1/failed=1；两组 legacy tables 数组各1，Mongo doc_rag_pages/doc_tables也各1。不是 UI 隐藏已成功返回的第二表。

旧路径先对裁图再次调用 layout_parsing，再对 VLM 使用整页恢复提示。它把“发现对象”与“完整转录对象内容”混在一起。GLM 非空候选仍缺闭合table；VLM正确关联ID但内容为空或未闭合，现有数据不能二分。原响应形状和 finish_reason 未持久化，不能断言 token/DPI 是根因。不得将原始350/393字符冒称为裁图响应长度。

本轮成功定义：缺失/不完整对象使用真正的对象裁图内容提取契约；每个对象有界重试与独立终态；每次尝试有足够脱敏诊断；只有完整、有效、原ID关联的结果进入成功数组。真实两页完整识别必须单独验收，不以 mocked 通过宣称已修复生产结果。

## 2. 非目标与硬边界

- 不改 Membership、MCP Router、数据库数据、provider配置、其它worktree或自托管OCR鉴权行为。
- 不做按页码/表号/两表数量分支，不以DPI多次回退成为主流程，不更换或硬编码供应商。
- 不伪造缺失单元格/行，不自动补HTML结束标签，不把无效payload放进legacy/RAG成功数组。
- 不上传S3、不持久化裁图/图像data URI、不回填原图；裁图仍只在现有TemporaryDirectory内用于提取。
- 不复制其它worktree的单页候选，不改single_page_tools实现，不扩大为全站表格清洗重构。
- 允许本地mocked测试、静态检查与窄范围提交；禁止本轮真实模型调用、构建、重启、部署、push。

## 3. Provider能力决策矩阵

| 输入/能力 | 本轮用途 | 决策依据与禁止事项 |
|---|---|---|
| 已配置GLM layout_parsing | 保留整页权威清单及已完整对象内容 | 已有正常上传契约；不添加未文档化max_tokens控制 |
| GLM crop layout_parsing | 不再用于对象内容恢复 | 实测返回候选仍不完整；layout endpoint不承担新的完整转录契约 |
| 已配置DynamicVLMClient image chat/completions | table/formula/figure裁图内容提取及一次紧凑重试 | 既有接口和本次实际JSON响应证明此调用路径可用；显式预算不超过注入max_tokens与本地安全上限 |
| GLM或自托管OCR的chat/completions能力未知 | 不自动尝试，不由layout URL推导chat URL | 无供应商能力证据不得猜测；不影响现有无key OCR支持 |
| VLM未配置/被关闭 | 不调用layout端点替代，不假定空对象 | 保留FAILED/review_required，诊断provider_unavailable |

不要求供应商支持JSON Schema/response_format扩展；使用既有image-chat文本提示+严格本地解析/校验。若供应商实际不支持图像、返回schema或预算，必须诊断失败，不能自动切换到未配置供应商。

## 4. 外部与内部契约

### 4.1 权威对象身份与兼容输出

- 保持 `layout_version=pdf2md-layout-ledger-v1`、`layout`、`reconciliation`、`semantic_status`；不改变text/unknown处理。
- ledger的layout_id/type/reading_order/bbox只来自整页layout，裁图响应不得改写它们。裁图像素坐标仅为诊断，不代替normalized_page bbox。
- `elements` 与 `rag.elements.tables|formulas|figures` 保持shape与成功对象字段兼容；每个成功payload精确回链原layout_id。
- 失败对象保留原安全partial content、FAILED/error/review_required=true、payload_ref=null；reconciliation计入failed，不消失。成功后review_required=false。
- 恢复成功仅替换该对象内容，不重新检测/合并/排序页面，不重新生成其它成功对象。

### 4.2 单对象裁图内容响应

每次请求只包含一个既有block；明确图片已经是该对象的裁图，原bbox仅是页面关联元数据，不能再次按原bbox切图。原不完整文本不作为答案模板发送，防止回显残片。

最小响应为单对象JSON：`layout_id`、`type`、`status`、`complete`，及类型payload。

- table：`markdown`（完整HTML或pipe Markdown）、可选title；完整保留行列、合并单元格与公式。compact重试只输出身份、状态、完整性、markdown，省略重复描述但不得省略数据。
- formula：`latex`，可选description/variables/context；不能用标题代替公式。
- figure：`description`，可选caption；要求图示内容描述，不得只有通用标题或宣称已保存图片。
- 可读且完整时 `status=EXTRACTED, complete=true`；不可读/截断/未完成时 `status=FAILED, complete=false`。模型自报完整性只是必要条件，仍须本地校验。
- 非dict、非法JSON、空内容、身份/类型不匹配、缺完整性声明、显式失败、截断finish_reason、无效HTML/Markdown/LaTeX均不得晋升。
- HTML要求单一完整table、正确嵌套并闭合的表结构、实际行/单元格；不修改返回内容以“修复”结构。Markdown要求表头分隔行及一致列数；LaTeX要求非空且成对分组/环境闭合；图描述要求非空且非未读占位。结构有效不等于视觉准确，仍需真实验收。

### 4.3 有界恢复

- 延续 `layout_recovery_max_objects` 默认8、硬上限16；0关闭对象恢复并明确记not_attempted。
- 每个对象最多2次内容请求：initial + compact。只对内容缺失、不完整、非法JSON、截断等可重试问题再试；身份/类型冲突及provider异常不盲目语义重试，继续同页其它对象。
- 每页逻辑内容请求上限 `2 * max_objects`；现有transport重试/stream fallback仍按已有固定上限，不增加它们。page级超时保持现有责任边界；报告逻辑尝试数而非假称实际HTTP次数。
- 显式输出预算 `min(provider注入max_tokens, 16384)`，同时尊重既有runtime provider cap；不自动提高provider配置，不用默认4096覆盖更大合法注入预算。

### 4.4 可观测性与脱敏

`layout_recovery`保留pending/attempted/limit/objects，增加contract版本。每对象保留layout_id/type/crop/outcome/review_required/provider。

每次attempt至少记录：attempt序号、mode(initial/compact)、provider类别、outcome、稳定reason；以及以下白名单形状字段：

- `response_chars`、`json_status`、`candidate_chars`、HTML table/tr/td/th开闭数量、结构校验reason。
- `finish_reason`（固定枚举或other）、`requested_max_tokens`、`effective_max_tokens`、`truncated`、`call_mode`（stream/nonstream/unknown）。
- 缺失provider元数据写null/unknown，不能伪造length；在每次调用前清除旧诊断避免跨对象污染。
- API异常仅错误类名，不记异常message/URL/header；身份不匹配仅记录reason，不回显模型返回的任意ID。

禁止保存原prompt、模型全文、HTML/LaTeX文本片段、API key、认证头、base_url查询参数、图片/data URI、临时路径。partial content仅保留在既有ledger字段，不重复放诊断。TaskManager原样持久化加法诊断，测试必须证明JSON可序列化且无敏感值。

## 5. Goals（每Goal执行 红测/证据 -> 最小实现 -> 验证 -> Exit）

### Goal 0：基线与计划冻结

行动：检查status/HEAD、当前AGENTS、既有正常上传计划、原两页page_result及现有provider接口。创建本计划。只审查已提交代码，不合并其它worktree。

验证/Exit：基线02a5c06、工作树干净；本计划明确未证实的provider生成原因，未假设GLM layout token参数；现有聚焦测试基线可复跑。

边界/提交/回滚：仅新计划文件；无生产写；计划随实现一个窄提交，回滚删除本轮计划只在用户授权下进行。

### Goal 1：先建立可证伪的对象契约与诊断红测

行动：添加真实DynamicVLMClient的网络mock prompt/预算/JSON/finish_reason测试；新增内容校验与redaction测试；通过page_processor fixture覆盖crop响应失败、重试、失配、不影响其它对象和TaskManager持久化。

验证：在实现前运行新测试并记录预期红测，原因必须是新契约/诊断缺失而非环境失败。

Exit：每个后续行为都有失败断言；不使用真实模型、不修改测试配置绕过失败。

边界/提交/回滚：只新增/调整PDF2MD mocked测试；不改Membership测试或真实数据；与实现一并提交，可按整个提交revert。

### Goal 2：真实对象内容提取契约与明确校验

行动：新增VLM单对象crop方法，保留旧整页/单页工具方法；采用4.2响应与4.4诊断。引入可复用纯校验函数，给出明确拒绝码/形状；使用完整JSON解析，不修补HTML或从损坏JSON拼造成功对象。

验证：prompt明示crop、bbox为metadata-only、无原残片；max_tokens确实透传且有上限；table/formula/figure严格身份及完整性；finish_reason=length即使JSON可解析也拒绝；空/无效/恶意输出不会泄漏。

Exit：所有客户端/纯函数测试通过；不添加新依赖或新Docker COPY文件。

边界/回滚：仅vlm_client/layout_ledger及测试；不改OCR客户端/路由注入；旧方法保持兼容，revert本提交回到ab60045恢复行为。

### Goal 3：正常上传有界对象恢复与诊断持久化

行动：替换重复crop layout调用为单对象VLM内容提取；保留crop helper和权威清单；initial失败后按稳定可重试reason最多compact一次；成功调用现有payload接入，失败继续后续对象；累积不匹配诊断，不能被后一次成功覆盖。

验证：矩阵全部通过；3张完整表不调用恢复；每失败对象最多2次；max_objects上限精确；原ID/order/bbox不变；只有成功对象进入两组数组；FAILED有review_required；TaskManager page JSON保留诊断且不含secret。

Exit：正常process_page与mocked process_task_page路径通过；无GLM crop layout调用；所有pending对象成功或显式失败/未尝试，不静默丢弃。

边界/回滚：仅page_processor及上述模块；不改Membership/server任务生命周期；可先用现有max_objects=0停止内容恢复（仍保留ledger），完整回滚需用户授权revert+重新部署。

### Goal 4：兼容回归、静态检查与Review依赖

行动：复跑bad_text_policy、single_page_tools、新object恢复测试及自托管配置注入测试；py_compile与diff checks；审查Membership现有消费边界，不改文件。

Exit：legacy成功payload形状/语义不变；layout/reconciliation失败语义不变；既有无key自托管OCR测试不退化。附加诊断不改变原消费链。明确Membership另一个worktree的review_items消费者仍待独立集成，不能宣称已部署或强行创造新schema。

边界/回滚：只修复本轮导致的回归；不借机修改单页实现、UI、数据库或provider管理。

### Goal 5：窄提交与交付

行动：逐文件diff、git status、显式git add、cached文件清单/完整diff/cached --check；仅提交本计划、必要README契约说明、3个恢复模块及相关测试。

Exit：提交哈希可复核、工作树干净、报告已测与未测；不包含02a5c06之外其它用户改动或worktree候选。完成本地工作不是生产两页验收完成。

### Goal 6：真实E2E与发布门槛（本轮禁止执行）

前置：用户自行或另行授权build/recreate `pdf2md-enhanced-mcp`；只读核验运行文件hash匹配新提交。单独授权真实模型调用与原文档测试；不使用新随机样本代替原页。

验收：GBT16749-2018-p10-p39.pdf第16/17页均仍识别2table；每个成功表与原页逐行/列/合并单元格比较，不仅检查</table>。若第二表失败，必须获得明确拒绝码、response_chars、finish_reason/预算；ledger计数与成功数组一致。另验混合table/figure/formula，任一对象失败不阻断其它对象。

Membership门槛：独立review_items工作树需审查其契约适配、按原source page和layout_id关联失败项、显示review_required、不晋升失败内容、不覆盖既有成功对象。MCP本地完成不意味着此依赖完成。

Exit：真实两页内容完整+混合页验收+失败可见性集成分别留证据才可宣称端到端完成。失败则保留新诊断，回到Goal 1补fixture，不按页号补丁、不伪造闭合标签。发布/回滚均需另行授权。

## 6. Fixture覆盖矩阵

| fixture | 关键断言 |
|---|---|
| 2/3张完整表 | 不crop、不调用VLM、全部保留 |
| 不完整大型HTML表 | 不进成功数组，触发仅该对象crop |
| crop initial成功 | 原ID/order/bbox不变，完整payload晋升 |
| crop空/未闭合/非法JSON -> compact成功 | 恰好2逻辑调用，诊断保留每次独立形状 |
| crop两次不完整 | FAILED+review_required+partial原内容，零伪造闭合 |
| GLM layout不完整 -> VLM image-chat | 不再次调用GLM crop layout，显式预算 |
| finish_reason=length但JSON有效 | 不接纳，compact仍length则失败 |
| 错ID/错type/重复对象 | 不按位置猜测，不污染其它对象 |
| table/formula/figure混合 | 某对象失败时后续两类仍执行并对账 |
| formula不平衡LaTeX/figure空描述 | 不用非空标题代替有效payload |
| provider异常/不可用 | 不暴露message/密钥，无假成功，后续对象继续 |
| fanout=0/1/上限 | 未尝试对象明确标记，调用数有界 |
| TaskManager持久化 | 诊断与reconciliation保留，敏感标记不出现 |
| 既有p16/p17-style残片 | 泛化长表fixture，无页码/表号实现分支 |

## 7. 执行记录

- 2026-08-31：Goals 0–4完成。基线115项测试通过；新契约红测确认缺失能力后实施。曾修正测试导入/参数夹具错误，并将旧GLM-crop预期迁移为单对象image-chat契约，未放宽身份、位置或失败隔离断言。
- 当前完整聚焦回归159 passed（既有62条依赖弃用警告）。新增44项涵盖真实VLM客户端的mock传输、严格拒绝条件、compact有界恢复、redaction、provider不可用/过滤、错误ID诊断不被后续成功覆盖、失败隔离及持久化。
- 两个本地集成场景使用真实临时PDF、真实crop、真实VLM JSON解析，仅mock网络返回，经过start_task/process_task_page/TaskManager/finalize_task；分别验证第二对象成功和持续失败，同页公式与图继续成功，legacy数组与reconciliation一致。
- 已移除正常上传中的GLM crop layout恢复；未修改整页OCR客户端、single_page_tools、自托管provider配置注入或Membership。恢复候选仅白名单字段进入成功payload；未知模型字段/返回坐标不改写权威布局。
- Goal 5：py_compile与git diff --check通过；本计划与恢复代码以一个窄范围提交交付，暂存审查结果及提交哈希见任务最终报告。Goal 6保持未执行，当前不能声称真实第16/17页已修复。
- 真实模型、原两页E2E、Membership review_items集成、build/recreate/deploy：均未执行，不在本轮授权内。
