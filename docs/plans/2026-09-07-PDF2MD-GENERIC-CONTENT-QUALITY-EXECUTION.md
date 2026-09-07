# PDF2MD 通用内容质量 Goals Loop 执行报告

## 续执行最终结果（2026-09-07，以本节为准）

状态：剩余可离线执行的 MCP 实现条目已补齐并通过回归；**不宣称真实文档质量目标全部通过**。真实模型、运行镜像与 Membership 集成继续独立待验收。下文保留首轮历史记录用于红绿证据追溯，其中“pandas 未迁入生产”“只支持页面级 figure”“缺少显式父表恢复入口”等结论已被本轮实现覆盖。

基线仍为 `main@125a4904e349ab46f3498ea5b38dc35ecd577176`。续执行开始时全部 dirty 文件来自上轮实现及用户计划，未覆盖外部新增修改。CodeGraph status/query/context 已执行；context 有低置信提示，随后定向读取实际源码；每批 sync 均成功。没有创建新任务、提交、推送、真实模型调用、容器构建/启动/重启/部署或 Membership 修改/业务数据操作。

### 逐项闭环

| Goal | 本轮补齐内容 | 红测 → 绿测证据 | 离线完成范围 / 仍待验收 |
| --- | --- | --- | --- |
| G1 | 中文标题不能掩盖英文正文；继续复用统一检测；保留源名称及已有字段级原因 | 反向混合描述先失败，修复后通过；全部既有语义/入口回归仍通过 | 语言契约本地通过；真实生成质量另验 |
| G2 | pandas/lxml 已迁入唯一生产网格函数；仅展开来源 token，再回取字符串；省略闭合标签、空/重复/合并来源、rowspan=0、thead/tbody/tfoot 顺序、非单元格注释覆盖及分配前预算检查 | 首轮 3 个新增失败（解析、合并原点、精确标签诊断）转绿；后续转义比较符、rowspan=0、非单元格正文、矩阵预算红测转绿；全 td 的显式模型来源提案可查询，真实值从原文回取 | 生产迁移及契约通过；私有快照仍 0/47 deterministic complete，歧义来源要走已实现的显式语义策略，未授权调用真实模型 |
| G3 | context.structure_target 恢复明确遗漏父表；校验来源 SHA1/页/bbox 后只裁剪指定区域；复用现有恢复器并共享 GLM/VLM 调用上限；HTML 单元格内公式按来源区间建立嵌套关系 | 目标恢复与错误来源两个红测转绿；单元格内公式关联新增红测转绿，保留精确 LaTeX/显式编号且不重复生成独立公式；100×100 合成页只传 40×40 目标给 stub；超预算不暗中重试；源 LaTeX 保留 | 显式恢复能力通过；p15/p23 的真实 provider 效果不由 stub 证明 |
| G4 | 从 source_cells.image_regions 直接产生有稳定身份的图片，不再依赖页面级 figure；统一资产出口、关联、大小预算和清理 | 无页面 figure 的单元格图先失败后通过；重复调用不追加；声明 cell 与几何所属 cell 冲突先失败后修复为 unresolved 且不裁剪 | 有可靠明确 cell/region 的出口通过；自动识别遗漏图像和 Membership 显示仍需模型/E2E |
| G5 | 更新生产依赖/两种打包执行测试、契约、离线查询比较器和逐表原因；保留 v1 发布门槛 | 隔离 Python 中复制两种 Docker payload 并实际执行 pandas parser；484 项回归、编译和 diff 检查通过 | 源码、合成契约、自审和交接完成；外部验收不冒充完成 |

新回归文件 `tests/test_pdf2md_quality_completion.py` 共 18 项，全部离线。新增结构目标与图像区域是显式、可选输入；旧请求路径保持兼容。调用预算默认 1，允许 0..4；0 不构造 provider，所有尝试合计受限。单对象纯语义接口仍只有 1 次逻辑调用。

### 为什么私有样本没有全部自动通过

本计划禁止猜测表头、范围端点和条件，也不允许用诊断候选替代 v1 完整查询。本轮没有把 0/47 当作成功：这是**确定性自动语义投影未通过**的明确结果。代码现在具备 pandas 来源映射、来源提案验证与显式目标恢复能力；对于快照中没有结构表头证据的全 td 表、合并分区/脚注/条件，下一项实际内容验收需要授权真实 semantic_review/model_required 调用，或提供新的可靠来源证据。4 张 rowspan 越界、2 张合并位置冲突仍是输入结构阻塞，不能通过放宽检查变成成功。

精确字符串 `150~475` 可通过新增 `select_candidate_labels` 做 **diagnostic_only** 核对；它不会执行区间判断，也不允许部分表发布。正式 select_records 仍拒绝 unavailable。

### 私有样本本轮重新执行结果

- pandas 2.2.3/lxml 6.1.1 独立 probe：47/47 HTML 网格，5/5 人工表头查询。
- 生产 parser（pandas 2.3.3/lxml 6.1.1）：47/47 网格；与独立 probe 43/47 完全一致；41/47 来源坐标自洽。剩余 4 张跨度越界、2 张合并来源冲突均明确阻塞。
- deterministic 自动语义投影：**0/47 complete**。既有五个查询同时运行自动投影对照：**0/5 available**，全部明确 unavailable；不是返回空列表后误判“未找到”用例通过。
- 合成的明确 thead/td 表自动确定表头并通过查询；全 td 表由 stub 提供来源引用后通过真实验证器和查询器。这两者是离线能力证据，不是私有标准的真实模型验收。
- 未提交原文。审计输入 hash 与首轮一致；输出只含序号、页、布尔值和原因。

最终逐表原因（同一表可有多个原因，不可加总为表数）：

| 样本 | 表序号 | 页 | 来源坐标自洽 | 自动投影 | 原因 |
| --- | --- | --- | --- | --- | --- |
| 1 | 1 | 1 | 通过 | unavailable | ambiguous_header |
| 1 | 2 | 2 | 通过 | unavailable | ambiguous_header |
| 1 | 13 | 12 | 通过 | unavailable | conditional_source_requires_review |
| 1 | 14 | 13 | 通过 | unavailable | body_spanning_cells |
| 1 | 15 | 13 | 通过 | unavailable | body_spanning_cells |
| 1 | 16 | 14 | 通过 | unavailable | body_spanning_cells |
| 1 | 17 | 16 | 通过 | unavailable | ambiguous_header |
| 1 | 18 | 17 | 通过 | unavailable | body_spanning_cells, unsupported_condition |
| 1 | 24 | 22 | 通过 | unavailable | conditional_source_requires_review |
| 1 | 25 | 23 | 通过 | unavailable | body_spanning_cells |
| 1 | 26 | 24 | 通过 | unavailable | ambiguous_header |
| 1 | 27 | 24 | 通过 | unavailable | conditional_source_requires_review |
| 1 | 28 | 24 | 通过 | unavailable | ambiguous_header |
| 1 | 29 | 24 | 通过 | unavailable | ambiguous_header |
| 1 | 30 | 25 | 未通过 | unavailable | overlapping_source_cells |
| 1 | 31 | 26 | 通过 | unavailable | conditional_source_requires_review |
| 1 | 32 | 27 | 通过 | unavailable | ambiguous_header |
| 1 | 34 | 28 | 通过 | unavailable | ambiguous_header |
| 1 | 35 | 29 | 通过 | unavailable | ambiguous_header |
| 1 | 36 | 30 | 通过 | unavailable | conditional_source_requires_review |
| 1 | 37 | 31 | 通过 | unavailable | conditional_source_requires_review |
| 1 | 38 | 32 | 通过 | unavailable | conditional_source_requires_review |
| 1 | 39 | 33 | 通过 | unavailable | conditional_source_requires_review |
| 1 | 40 | 34 | 通过 | unavailable | conditional_source_requires_review, unsupported_condition |
| 1 | 41 | 34 | 通过 | unavailable | conditional_source_requires_review |
| 1 | 42 | 35 | 通过 | unavailable | conditional_source_requires_review |
| 2 | 1 | 1 | 通过 | unavailable | body_spanning_cells, unsupported_condition |
| 2 | 2 | 1 | 通过 | unavailable | body_spanning_cells, unsupported_condition |
| 2 | 3 | 2 | 通过 | unavailable | conditional_source_requires_review |
| 2 | 5 | 3 | 通过 | unavailable | body_spanning_cells, unsupported_condition |
| 2 | 7 | 4 | 通过 | unavailable | ambiguous_header |
| 2 | 8 | 5 | 未通过 | unavailable | table_structure_unavailable |
| 2 | 9 | 7 | 通过 | unavailable | conditional_source_requires_review |
| 2 | 10 | 8 | 通过 | unavailable | body_spanning_cells |
| 2 | 11 | 9 | 通过 | unavailable | ambiguous_header |
| 2 | 13 | 10 | 通过 | unavailable | body_spanning_cells |
| 2 | 14 | 11 | 通过 | unavailable | body_spanning_cells |
| 2 | 15 | 11 | 通过 | unavailable | conditional_source_requires_review |
| 2 | 16 | 12 | 未通过 | unavailable | table_structure_unavailable |
| 2 | 17 | 13 | 未通过 | unavailable | table_structure_unavailable |
| 2 | 18 | 14 | 通过 | unavailable | conditional_source_requires_review |
| 2 | 19 | 15 | 未通过 | unavailable | table_structure_unavailable |
| 2 | 20 | 16 | 未通过 | unavailable | overlapping_source_cells |
| 2 | 21 | 17 | 通过 | unavailable | conditional_source_requires_review |
| 2 | 22 | 18 | 通过 | unavailable | conditional_source_requires_review, unsupported_condition |
| 2 | 23 | 19 | 通过 | unavailable | ragged_table_rows |
| 2 | 24 | 20 | 通过 | unavailable | conditional_source_requires_review |

### 验证命令与产物

```sh
.venv/bin/python -m pytest -q --no-cov tests/test_pdf2md_quality_completion.py tests/test_pdf2md_content_quality.py tests/test_pdf2md_enhanced_table_query.py tests/test_pdf2md_object_semantics.py tests/test_pdf2md_enhanced_single_page_tools.py tests/test_pdf2md_enhanced_object_recovery.py tests/test_pdf2md_enhanced_upload_semantics.py tests/test_pdf2md_enhanced_bad_text_policy.py
.venv/bin/python scripts/audit_pdf2md_content_quality.py --input /tmp/docintel-pandas-current-tables/input.json --output /tmp/pdf2md-completion-sample-audit.json --pandas-reference /tmp/pdf2md-completion-pandas-reference.json --query-spec /tmp/docintel-pandas-current-tables/queries.json
```

最终 **484 passed, 64 warnings**。py_compile 和 git diff --check 通过。告警仍是既有依赖/配置告警，未广泛升级。运行日志 `/tmp/pdf2md-completion-final-tests.txt`，各轮失败/同步日志 `/tmp/pdf2md-completion-red-*.txt` 与 `/tmp/pdf2md-completion-sync-*.txt`，私有审计及独立 probe 为 `/tmp/pdf2md-completion-sample-audit.json` 与 `/tmp/pdf2md-completion-pandas-reference.json`。临时产物可能被后续清理，代码/合成测试/本报告可保留复验方法。

依赖变化：服务 requirements 加入 `pandas>=2.2.3,<3` 和 `lxml==6.1.1`；两种 Dockerfile 均安装该文件。本地已有 pandas 2.3.3/numpy 2.4.2 保持不变，仅从已安装的同架构 Python 3.12 Codex runtime 离线补入缺失 lxml 6.1.1 及其 metadata；没有网络安装或升级其他依赖。独立 probe 用现有 bundled pandas 2.2.3。打包验证实际运行 parser，但不等于镜像验收。

### 自审与消费者交接补充

- 没有按标准名称、文件名、页码或特定数值写分支；新增 fixture 全为合成。
- pandas 只接收唯一 token，防止数值转换、空值推断和空格清理损坏值；合并来源按标识验证，不能以重复字符串存在证明坐标正确。HTML 原始 bytes/hash 不变；不完整标签的 raw_html 为规范化内部表示，raw_text 保留字符。
- 显式结构恢复先核对来源再创建 provider；共用调用上限；不在 query enhancement 里开启 OCR/整页扫描。
- 单元格图片必须有唯一且与声明一致的父表/cell 几何，冲突不裁剪；不读 region 提供的 URL/路径，不输出容器路径，不插入悬空 Markdown；重复调用身份不变。
- table.image_unresolved 经过输出归一化保留；结构/语义/查询/资产质量保持分开。结构 complete 不表示字段完成，PNG available 不表示 OCR/语义正确。
- Membership 新消费字段：context.structure_target、structure_recovery.binding/diagnostics/dependencies、source_cells.image_regions、image_unresolved、table.contained_formulas/contained_formula_sources、figure.cell_image_source、parent_relation、image_asset。仍需校验当前版本、持久化资产并接入派生渲染，不可自动发布 candidate_sections。

### 续执行改动文件

- G1：`semantic_language.py`。
- G2：`single_page_tools.py`、`table_query.py`、`requirements.txt`、`requirements-quality-audit.txt`、`scripts/audit_pdf2md_content_quality.py`。
- G3/G4：`single_page_tools.py`、`page_processor.py`、`layout_ledger.py`。
- 回归：`tests/test_pdf2md_quality_completion.py`；其余首轮测试保持通过。
- 契约/记录：`TABLE_QUERY_CONTRACT.md`、`OBJECT_SEMANTIC_CONTRACT.md`、`CONTENT_QUALITY_CONTRACT.md`、本报告及原计划状态行。服务文件均位于 `mcp/servers/PDF2MDEnhanced/`。
- 首轮 Dockerfile 的共享语言模块 COPY 改动继续保留；本轮新增第三方依赖通过两种既有 requirements 安装路径打包。

### 最终权限边界与下一步验收

| 类别 | 已做 | 未做及下一步 |
| --- | --- | --- |
| MCP 本地实现/离线验收 | 已完成本轮剩余实现、失败回归、自审、契约与报告 | 无需再次授权这些已完成的本地动作 |
| 真实模型内容质量 | 仅有 stub 与确定性比较，不计真实模型通过 | 另行授权 provider/model/预算后，验证 47 表语义转换、p15/p23 目标恢复、表内图识别和中英文输出 |
| 源结构不一致 | 4 个 rowspan 越界、2 个合并来源冲突均已明确阻塞 | 提供修正来源，或授权原图目标恢复；不能从旧 HTML 猜正确值/结构 |
| 镜像/部署 | requirements 和两种隔离 payload 执行通过 | 未构建/重启/部署；用户另行授权后执行并核对 artifact/schema/body limit |
| Membership E2E | 消费字段、错误、重试类别已交接 | 未修改或运行；验证当前版本、对象回写、资产显示、查询条件、索引和分批统计 |

未提交、未推送。总体真实文档质量验收仍未完成，此处不把“剩余本地实现完成”混写为“所有外部效果验收通过”。

---

# 首轮执行记录（历史，以下结论已由续执行覆盖）

日期：2026-09-07
状态：本轮源码实现与离线回归完成；总体文档质量目标未关闭。真实模型、运行镜像和 Membership 集成均待另行授权验收。

## 基线、权限与执行方式

- 仓库 `/Users/kehongwei/workspace/AICMDEngine`；`main`；HEAD `125a4904e349ab46f3498ea5b38dc35ecd577176`。
- 初始只有用户提供的 Goals Loop 计划未跟踪。保留该文件；未改 Membership，未读写业务数据库。
- 已读取根 AGENTS.md，并检查祖先/目标子目录规则；没有额外 AGENTS.md。`docs/specs/` 不存在。
- CodeGraph status、query、context 本轮可用；索引有旧版本提示，未全量重建。每批源码修改后 sync 成功。
- 阅读两个既有契约、前序 table recovery 计划、相关测试，以及私有 pandas probe。追踪 server → single_page/page_processor → VLM/对象恢复 → 输出归一化；router 仍按工具 schema 注入配置（`src/routers/mcp.py` 的 `get_tool_schema_properties` / `choose_vlm_injection_key`）。
- 全程单代理顺序执行。未提交、推送、安装/升级依赖、构建镜像、启动/重启容器、部署或调用真实模型。模型测试均为 stub。

## G1：语言约束与可靠语义返回

目标/不变量：校验生成说明；保留原文标题、HTML、LaTeX 和对象身份；单对象增强仍最多一次逻辑调用。

失败证据：首轮 5 个失败中，4 个为 en/zh 反例、英文标题加中文正文、部分字段以及上传描述误接受；另 1 个为空行坐标（归入 G2）。之后补充 layout-enhanced 缺少语言参数、恢复 payload 丢失语言失败原因的红测，均先失败再修复。

实现：将既有单页语言检测抽到 `semantic_language.py`，复用解析和输出检查；贯穿单对象增强、上传、单页 table/formula/figure/structured、对象裁剪及 layout-enhanced。后者新增可选 `description_language` 并传入提示。未知语言保留原有行为。短符号不误判；复制原文名称不强制翻译。

响应规则：全无有效请求字段 → failed/no repairs；存在有效字段 → 沿用 complete 的“接受提案”含义，同时返回 unresolved_fields/reasons。语言错误字段清空，源内容不改，单对象失败也保留 request_id/model_calls；恢复路径保留语言原因码。

验证：正反语言、混合说明、符号、部分字段、身份/字段越界、空/错误响应、模型失败、入口传递和隔离打包测试通过。旧语言测试中明确 en 却期待中文说明的断言改成拒绝；仅测中文提示的 stub 改成中文返回，未降低拒绝条件。

限制/下一步：启发式不等于语言或语义正确性的完整证明；引用外语长句、复杂混合语种仍需真实模型样本校准。保留的原始 Markdown 不等于通过描述语言校验。Membership 必须消费字段级 unresolved，而非只看 complete。

## G2：HTML 查询投影

目标/不变量：一个既有生产解析器；位置映射优于文本存在性；保留 v1 的 complete/unavailable 和仅诊断 candidate_sections。

失败证据：空行被过滤；显式 thead 内全 td 表头不能自动投影；体内分组/条件说明被泛化为 ambiguous_header；缺少原始单元格字符串。第二轮 4 个新增失败全部转绿。自审又复现 caption 被遗漏于覆盖判断，已修复。

实现：保留空行坐标、增加 source_cells.raw_html/raw_text，旧 text/span 保持清理后文本的兼容语义；支持明确 thead 的 td 表头；caption 参与覆盖；tfoot、图片源、缺失来源单元格、rowspan 越界不冒充完成；区分条件说明、体内合并和不齐行。续表请求返回带原 binding 的 dependencies，不猜前页页码或抓取相邻页。范围标签仍保留原文，未放宽端点和条件执行门槛。

pandas/lxml 评估与计划调整：使用已安装的 Codex 离线运行时（pandas 2.2.3/lxml 6.1.1）重跑原 probe；47/47 网格、5/5 人工查询通过。但与生产网格仅 39/47 完全一致，pandas 不提供合并原点映射且可能展开超出实际观察行的 rowspan。因此没有把 pandas 替换进生产路径，也没有引入第二套增强服务；采纳其不吞表头/保留字符串的处理原则，保留既有来源映射实现。独立比较依赖记录于 `requirements-quality-audit.txt`，运行时无需新增包。此项是依据证据作出的实施调整，不宣称完成了 pandas 生产迁移。

新增 `scripts/audit_pdf2md_content_quality.py`：只读快照、零模型、输出脱敏逐表原因；可用 fresh pandas 结果作独立比较。

本轮私有样本：47/47 可形成网格；41/47 通过 MCP 来源坐标自洽检查；6/47 来源结构阻塞（4 张 rowspan 跨出观察行，另 2 张来源单元格未完整解析）。自动语义查询 complete **0/47**；5/5 人工表头基准通过，不可替代自动语义验收。8 张 pandas/生产网格差异尚未逐格对原图确认。

未解决/下一步：无明确表头的全 td 表、多区域分组、条件/脚注/范围、错误结构需要来源约束的真实语义解释或新来源证据。已有模型 proposal 验证/显式策略/预算路径沿用；未通过表全部 unavailable，不发布部分候选。完整自动复杂表转换仍未验收。

## G3：父表与表内公式

目标/不变量：保留父表、独立公式和不同公式字段；不凭邻近编号、数组顺序或相同文本猜关系。

失败证据：完整 HTML 表被 OCR 标为 formula 时进入公式数组；缺少可消费的父表/单元格关系。新增分类、合并单元格和歧义父表红测，均转绿。

实现：在 layout 身份创建前，用现有严格 HTML 结构校验确认一个完整表，将错误公式分类恢复为表。复用原有目标裁剪恢复入口，没有在 query enhancement 中增加整页扫描。仅对唯一几何包含建立 parent_relation；保留 table_layout_id、page_no、合并原点 cell_source。缺少可靠单元格 bbox、父表歧义均返回原因。独立公式保留原样，no_containing_table 不意味着其内容失败。

私有基准：只读渲染并完整查看 p15/p23。p15 确为公式密集续表；p23 上下两个父表，上方为公式表。旧检查报告记录对应父表遗漏。没有原始本轮 provider 输出，不能把遗漏精确归因于模型分类或后处理中的唯一阶段；本轮分类修复只覆盖“已经存在完整 HTML 却被标为 formula”的确定性缺口。

未解决/下一步：若 OCR 只给出独立公式、未识别父表区域，本修复不能凭空重建。需要授权真实模型后，在显式目标和原图上验证结构发现/裁剪恢复，确认 p15/p23 父表及独立公式不丢失。原图查看只是基准确认，不是修复效果验收。

## G4：原图资产与单元格关系

目标/不变量：返回真实裁剪字节及来源，不以说明冒充图片，不返回私有路径或注入悬空 Markdown。

失败证据：缺少 asset 输出、错误坐标防护与明确关联。G3/G4 合计首轮 8 个失败转绿；后续增加多表多图、输出归一化、资源失败、重复调用和数量预算用例。

实现：layout-driven upload 在页面临时栅格有效期内复用 `_crop_layout_block_image`，零 padding 裁剪，返回 PNG data URI、sha256、尺寸、pixel_bbox、page_no/layout_id。临时目录在成功/异常路径清理。每图 8 MiB、每页合计 16 MiB、最多 32 图、源栅格最多 1600 万像素。非法/缺失 bbox 不访问图片路径；资源失败只返回原因。

验证：合成源图字节解码、精确 20×30 像素裁剪、合并单元格唯一关系、同页多表多图、重复调用字节一致、归一化后 asset/关系保留、临时文件清理、无坐标和资源失败均通过。

未解决/下一步：上游未识别的表内工程图仍无法导出；缺少 cell bbox 时图片可以 available，但 cell 关系仍 unresolved。本次图像出口为 layout-driven upload，未宣称所有旧单页入口均有资产出口。需真实模型提供可靠区域，Membership 持久化后验证显示。Base64 约增加 1/3 传输量，真实 RPC/body limit 尚待部署验收。

## G5：质量、回归与消费者交接

已更新 `OBJECT_SEMANTIC_CONTRACT.md`、`TABLE_QUERY_CONTRACT.md`，新增 `CONTENT_QUALITY_CONTRACT.md`。旧 Membership 本地模型调用链标为历史快照待消费端核实，未据此重建本地模型逻辑。

质量保持独立：结构覆盖 ≠ 语义字段完整 ≠ 查询可执行 ≠ 原图语义一致。PNG 资产成功只证明源栅格裁剪；source_bound 仍非 image_verified。没有改变 v1 候选的发布资格，也没有增加文档队列或重试调度。

Membership 必须：

1. 校验 tenant/doc/version/revision/page 与精确对象身份，按字段处理 language mismatch/unresolved。
2. 原位回写所选对象，保留 HTML/LaTeX/编号/名称/语义的各自含义，拒绝候选冒充完整查询。
3. 接收父表和关系，验证 parent/cell 存在；检查图片字节/hash/尺寸，保存资产并在独立派生渲染中使用持久 URL。
4. 保留条件、单位、区间端点、source span 和续表依赖，不能扁平化为无条件值。
5. 负责任务、分批续跑、预算跳过、重试和统计；6 页预算问题不属于本轮 MCP 修复。
6. provider/语言/资源失败可由调用方按原因决定重试；缺少上下文/坐标或确定性结构阻塞需要新证据，不能盲重试。

## 离线验证与环境

- 修改前：计划指定的五组测试 **373 passed**。
- 最终：五组原有测试 + bad_text_policy + 新通用质量测试：**466 passed, 64 warnings**；新增通用质量用例 35 项。
- 两种 Dockerfile 的显式 COPY 在隔离 Python 进程导入验证通过，新增 semantic_language.py 均被复制。未实际构建镜像；runtime requirements 不增加第三方依赖，audit requirements 单独记录 pandas/lxml。
- py_compile 与 git diff --check 通过。CodeGraph 每批 sync 成功。
- 64 个告警来自现有 Pydantic/FastAPI/SWIG/requests 与 pytest asyncio_mode 配置，基线即存在；未升级环境。
- 主 `.venv` 缺少 pandas/lxml；已使用现有 Codex bundled Python 完成本次独立 probe，无网络安装。

最终测试命令：

```sh
.venv/bin/python -m pytest -q --no-cov tests/test_pdf2md_content_quality.py tests/test_pdf2md_enhanced_table_query.py tests/test_pdf2md_object_semantics.py tests/test_pdf2md_enhanced_single_page_tools.py tests/test_pdf2md_enhanced_object_recovery.py tests/test_pdf2md_enhanced_upload_semantics.py tests/test_pdf2md_enhanced_bad_text_policy.py
```

可复验私有产物（仅临时目录，未提交原文）：`/tmp/pdf2md-quality-pandas-fresh.json`、`/tmp/pdf2md-quality-sample-audit.json`、`/tmp/pdf2md-quality-final-tests.txt`，以及各轮 red/sync 日志。后续清理临时目录后需重新生成；不保证永久可用。

## 私有快照逐表结果

输入 sha256：`8e67a651f968de9048eb056e85a78418f92aad1f58ddc72b16d87a5366ab3756`。样本编号按快照顺序；不记录原文、业务 ID 或数值。坐标列只表示与来源单元格/合并位置自洽，不表示与原图一致。没有 HTML 的 20 张表不计入本轮网格投影。

| 样本 | 表序号 | 页 | 网格 | 坐标自洽 | 自动投影 | 阻塞原因 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 1 | 1 | 通过 | 通过 | unavailable | ambiguous_header |
| 1 | 2 | 2 | 通过 | 通过 | unavailable | ambiguous_header |
| 1 | 13 | 12 | 通过 | 通过 | unavailable | conditional_source_requires_review |
| 1 | 14 | 13 | 通过 | 通过 | unavailable | body_spanning_cells |
| 1 | 15 | 13 | 通过 | 通过 | unavailable | body_spanning_cells |
| 1 | 16 | 14 | 通过 | 通过 | unavailable | body_spanning_cells |
| 1 | 17 | 16 | 通过 | 通过 | unavailable | ambiguous_header |
| 1 | 18 | 17 | 通过 | 通过 | unavailable | body_spanning_cells, unsupported_condition |
| 1 | 24 | 22 | 通过 | 通过 | unavailable | conditional_source_requires_review |
| 1 | 25 | 23 | 通过 | 通过 | unavailable | body_spanning_cells |
| 1 | 26 | 24 | 通过 | 通过 | unavailable | ambiguous_header |
| 1 | 27 | 24 | 通过 | 通过 | unavailable | conditional_source_requires_review |
| 1 | 28 | 24 | 通过 | 通过 | unavailable | ambiguous_header |
| 1 | 29 | 24 | 通过 | 通过 | unavailable | ambiguous_header |
| 1 | 30 | 25 | 通过 | 通过 | unavailable | conditional_source_requires_review |
| 1 | 31 | 26 | 通过 | 通过 | unavailable | conditional_source_requires_review |
| 1 | 32 | 27 | 通过 | 通过 | unavailable | ambiguous_header |
| 1 | 34 | 28 | 通过 | 通过 | unavailable | ambiguous_header |
| 1 | 35 | 29 | 通过 | 通过 | unavailable | ambiguous_header |
| 1 | 36 | 30 | 通过 | 通过 | unavailable | conditional_source_requires_review |
| 1 | 37 | 31 | 通过 | 通过 | unavailable | conditional_source_requires_review |
| 1 | 38 | 32 | 通过 | 通过 | unavailable | conditional_source_requires_review |
| 1 | 39 | 33 | 通过 | 通过 | unavailable | conditional_source_requires_review |
| 1 | 40 | 34 | 通过 | 通过 | unavailable | conditional_source_requires_review, unsupported_condition |
| 1 | 41 | 34 | 通过 | 通过 | unavailable | conditional_source_requires_review |
| 1 | 42 | 35 | 通过 | 通过 | unavailable | conditional_source_requires_review |
| 2 | 1 | 1 | 通过 | 通过 | unavailable | body_spanning_cells, unsupported_condition |
| 2 | 2 | 1 | 通过 | 通过 | unavailable | body_spanning_cells, unsupported_condition |
| 2 | 3 | 2 | 通过 | 通过 | unavailable | conditional_source_requires_review |
| 2 | 5 | 3 | 通过 | 通过 | unavailable | body_spanning_cells, unsupported_condition |
| 2 | 7 | 4 | 通过 | 通过 | unavailable | ambiguous_header |
| 2 | 8 | 5 | 通过 | 未通过 | unavailable | table_structure_unavailable |
| 2 | 9 | 7 | 通过 | 通过 | unavailable | conditional_source_requires_review |
| 2 | 10 | 8 | 通过 | 通过 | unavailable | body_spanning_cells |
| 2 | 11 | 9 | 通过 | 通过 | unavailable | ambiguous_header |
| 2 | 13 | 10 | 通过 | 通过 | unavailable | body_spanning_cells |
| 2 | 14 | 11 | 通过 | 通过 | unavailable | body_spanning_cells |
| 2 | 15 | 11 | 通过 | 通过 | unavailable | conditional_source_requires_review |
| 2 | 16 | 12 | 通过 | 未通过 | unavailable | table_structure_unavailable |
| 2 | 17 | 13 | 通过 | 未通过 | unavailable | table_structure_unavailable |
| 2 | 18 | 14 | 通过 | 通过 | unavailable | conditional_source_requires_review |
| 2 | 19 | 15 | 通过 | 未通过 | unavailable | table_structure_unavailable |
| 2 | 20 | 16 | 通过 | 通过 | unavailable | ragged_table_rows |
| 2 | 21 | 17 | 通过 | 通过 | unavailable | conditional_source_requires_review |
| 2 | 22 | 18 | 通过 | 未通过 | unavailable | table_structure_unavailable |
| 2 | 23 | 19 | 通过 | 通过 | unavailable | ragged_table_rows |
| 2 | 24 | 20 | 通过 | 未通过 | unavailable | table_structure_unavailable |

## 自审与剩余验收

自审检查：所有修改限于 MCP、聚焦离线测试、审计脚本和契约/报告；没有私有样本入库；没有标准名/页码/具体数值分支。复用原语言检测、HTML 网格、严格结构校验和 crop helper；没有新增平行生产解析服务。新资产和关系只在明确证据下输出。补查 caption、footer、嵌入图像、空结构、独立 figure 返回路径、恢复原因透传；原有源/身份/条件/预算测试仍通过。

| 验收层 | 当前结论 | 下一步操作 |
| --- | --- | --- |
| 本轮源码/离线契约 | 通过上述合成与现有回归；未关闭所有真实内容质量问题 | 可审查当前 diff 和重复运行命令 |
| 自动复杂表转换 | 私有样本 0/47 complete；仍受表头/结构/条件证据阻塞 | 授权后用显式 semantic_review/model_required、有限预算和来源引用逐表验收 |
| 真实模型 | 未执行 | 另行授权选定 provider/model 与请求预算，核对 en/zh、p15/p23、表内图区域和错误原因 |
| 运行镜像/部署 | 未构建、未启动或重启、未部署 | 另行授权后由用户执行对应增强服务的构建/部署，确认源码包、schema、body limit |
| Membership E2E | 未修改、未执行 | 实现上述消费规则后验证当前版本、对象原位回写、资产显示、查询条件与索引/统计 |

本报告不把 stub、人工表头、PNG 裁剪、HTTP 成功或测试数量当作完整文档质量验收。未提交、未推送；工作区保留可审阅修改。

## 改动文件清单

- `mcp/servers/PDF2MDEnhanced/Dockerfile`
- `mcp/servers/PDF2MDEnhanced/Dockerfile.cn`
- `mcp/servers/PDF2MDEnhanced/OBJECT_SEMANTIC_CONTRACT.md`
- `mcp/servers/PDF2MDEnhanced/TABLE_QUERY_CONTRACT.md`
- `mcp/servers/PDF2MDEnhanced/layout_ledger.py`
- `mcp/servers/PDF2MDEnhanced/object_semantics.py`
- `mcp/servers/PDF2MDEnhanced/page_processor.py`
- `mcp/servers/PDF2MDEnhanced/requirements.txt`
- `mcp/servers/PDF2MDEnhanced/server.py`
- `mcp/servers/PDF2MDEnhanced/single_page_tools.py`
- `mcp/servers/PDF2MDEnhanced/table_query.py`
- `mcp/servers/PDF2MDEnhanced/vlm_client.py`
- `tests/test_pdf2md_enhanced_object_recovery.py`
- `tests/test_pdf2md_enhanced_single_page_tools.py`
- `mcp/servers/PDF2MDEnhanced/semantic_language.py`
- `mcp/servers/PDF2MDEnhanced/CONTENT_QUALITY_CONTRACT.md`
- `mcp/servers/PDF2MDEnhanced/requirements-quality-audit.txt`
- `scripts/audit_pdf2md_content_quality.py`
- `tests/test_pdf2md_content_quality.py`
- `docs/plans/2026-09-07-PDF2MD-GENERIC-CONTENT-QUALITY-EXECUTION.md`

用户提供的 Goals Loop 计划仍为原有未跟踪文件，未改写。
