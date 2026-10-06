# 通用计算书链路执行记录

日期：2026-10-06（北京时间）。
状态：**MCP 源码、离线验证及服务部署完成；消费方联调／真实文档验收待完成**。
部署补记见文末；前文未部署描述为实现阶段记录。
本记录不是部署、真实模型准确率或发布成功证明。

## 执行边界和基线

- 仓库真实路径：`/Users/kehongwei/workspace/AICMDEngine`。
- 分支 `main`，HEAD `e09a3d428a1362b8e20d31debeccac832dbedca2`。
- 执行前唯一 dirty file 是未跟踪的本轮 Goals Loop 计划；无已有代码改动。
- 已读取根 AGENTS.md；mcp、tests、docs 内未发现子目录 AGENTS.md。
- 已读取 2026-09-13 的 contract-draft 和 execution，仅以当前源码与测试作为本轮证据。
- CodeGraph `status/query/context` 本次可用，status 报告 up to date、旧引擎版本提示；context 有低置信匹配提示，调用链用精确源码交叉核对。未全量重建索引，编辑后执行增量 `codegraph sync`。
- 只读 Docker 检查确认运行容器 `pdf2md-enhanced-mcp`，镜像 ID：
  `sha256:37861cc0072560dca8f97e60559027a399980e54c6f907f3b2b4ac0852a4f4fd`，
  容器创建于 `2026-09-22T13:20:05.50240905Z`。
- 修改前以下源码与容器 `/app/PDF2MDEnhanced/` 的 SHA-256 完全一致：

| 文件 | 修改前／运行中 SHA-256 |
| --- | --- |
| calculation_processing.py | ac4662b57bf8e27acbf90475af7f5a2f460582816d337ddf4f4b6833e9e95c3a |
| calculation_input.py | 96e77609c3bc90d697077f02754740a8080c3bee2887c09cb58f40903b9b7b4a |
| vlm_client.py | 2c69585870ea9192706c9767849c21d894c26584207c4948081a4c472bc218de |

没有提交、推送、构建／启动／重启容器、修改 Membership 文件／数据库、调用真实文档模型或消息通知其他 chat。仓库要求的 Jev 有界判断只使用了抽象的未闭合数学分隔符处理规则，不含文档内容。

## G0：已证实和未证实

调用链：`server.extract_page_tables` → `single_page_tools.extract_page_tables_direct` →
`_process_calculation_request` → `process_request`。
自动上传和旧单页路径经 `complete_calculation_batch` → `extract_calculation_items`；
本轮与人工路径共同使用 `structure_calculation_source`。

已证实：原图片处理一次要求转录、结构化和关联判断；程序分节原来仅接入已有内容整理及部分专用提取入口。
原 `_read_response` 将字段缺失、空白、错误类型和超长转录合并为 `calculation_source_missing`。
只读 Membership 源码再次确认计算书图片路径固定 150 DPI，整理已有内容走文本路径；引擎选项传递仍需消费方修改。

未证实：历史 p13_t1 最近失败的完整模型响应、WebUI 与 MCP 的实际模型／图片字节／参数一致性，以及原图逐项公式准确性。本次没有访问生产记录来重复确认历史时间和条目数量，也没有将旧记录当作本轮现场证据。G0 的线上失败复现部分仍待受控诊断样本。

## 各轮结果

| Loop | 状态 | 本轮证据及剩余依赖 |
| --- | --- | --- |
| G0 | 源码／运行基线完成；历史响应未取得 | 调用链、镜像和修改前哈希、205 项基线测试；未断言具体模型漏字段原因。 |
| G1 | MCP 候选契约和失败测试完成；消费方冻结待确认 | 首批 8 个预处理测试、随后 9 个阶段测试先失败；扩展 nested fixture，未改变已有顶层 calculation_sheet_json。 |
| G2 | 源码完成 | 独立图片转录；HTMLParser 块边界；完整／嵌套／未闭合数学、CRLF、Unicode、空标题节及明确例外说明测试。 |
| G3 | 源码完成 | source_revision、输入单元绑定、覆盖统计、重复／未知／跨批 ID 负例；公式片段和以 note 隐藏公式均不能成为完整结果。 |
| G4 | MCP 源码完成 | 共同文本结构化、长输入按完整单元分批、局部失败占位、显式整理恢复；单页与自动路径回归、模拟 HTTP 图片／文本与物理计数验证。消费方持久化恢复不在此完成声明内。 |
| G5 | 未完成 | Membership 代码只读确认能保留嵌套 map；新版 fixture 尚未同步，未运行消费方测试或编辑／保存／刷新流程。 |
| G6 | 未执行 | 未获得或使用本轮真实模型、镜像变更和业务数据操作授权；原图核验、真实页面及发布回读仍待完成。 |

## 实现与契约

修改五个既有模块，不新增解析器模块：

- `calculation_input.py`：扩展原分节函数，数学环境使用成对分隔符栈；未闭合尾部整体保留并标为未完成。识别 Markdown 标题，保持未知行；相邻完整公式可拆开，明确标记的紧邻例外说明保留在公式单元中。
- `calculation_sheet.py`：沿用 HTMLParser 读取块／单元格文本，保护比较符号；规范文本保留数学内部换行。既有 validator 继续验证来源字段，并拒绝以整条公式的片段充当完整 LaTeX。计算书元数据传递包含恢复来源。
- `calculation_processing.py`：共同结构化函数、分批、恢复原文、阶段状态和细分错误。
- `vlm_client.py`：图片阶段不再要求计算书语义字段；语义阶段仅接收文本和确定性数组，严格解码 JSON。分析范围内关闭 SDK／外层重试，共享 HTTP pre-send 计数，包括 fallback／redirect／token correction。无结果且 finish_reason 为截断／过滤时不再隐式改走 fallback。
- `single_page_tools.py`：计算书元数据分类纳入分析请求守卫；返回图片哈希、物理页号、PDF 身份哈希和可证明的渲染来源。调用者传图片时 render_dpi 为 null，不把默认值冒充上游实际 DPI。

保持 `calculation_sheet.contract_version=1`；共享 fixture 的版本升为 3，表示新增可审阅候选契约，消费方对齐待完成。

新增信息放在已被消费方复制的嵌套对象内：

| 字段 | 含义 |
| --- | --- |
| calculation_source.original_content | 原始 HTML／文本／图片转录；失败后的显式重试可使用该字段。 |
| calculation_source.sha256 | original_content UTF-8 哈希，保留原定义。 |
| calculation_source.text_sha256 | 规范 citation text 的 UTF-8 哈希。 |
| calculation_source.source_revision | UTF-8 `calculation-source-v2` + NUL + 原始内容的 SHA-256；规范化版本和原始内容变化均使版本改变。 |
| range_unit / range_scope | `unicode_codepoint`、`text`；半开区间，绝不是 HTML 字节偏移或 JS UTF-16 偏移。 |
| calculation_source.normalization | `html_blocks_v2`／`text_lines_v2`；原文、规范文本及各自哈希保留以供转换审计。 |
| calculation_source.pipeline | transcription、framing、semantic、validation 状态，单元计数、批次数、模型／提供方、单请求 timeout/max_tokens 和可用物理预算。 |
| calculation_sheet.coverage | input_units、represented、structured、needs_review；原文占位只增加 represented，不冒充 structured。 |
| source_section_id / source_item_id | 当前来源版本内稳定的程序编号；不依赖模型输出顺序。 |
| source_part_id / source_item_ids | 同单元多个输出必须显式区分 part；多个输入共同解释必须显式列出当前批内来源。 |

模型字段约束：真实 staged 客户端必须回显来源版本；协调器拒绝错版本／身份和改写 citation text。兼容旧注入客户端时缺失 revision 可按当前请求处理，但真实 provider JSON 不享受该兼容。公式／数值／单位仍是来源字段，semantic_desc 是独立生成说明。语义缺失不能通过设置状态掩盖。

当前策略：每批最多 40 单元、约 12000 字符，整单元分批；单个超大单元不切断、不调用模型，返回 `calculation_unit_budget_exceeded` 和原文占位。字符上限不是 provider tokenizer 的 token 保证，真实模型上下文适配需在 G6 验证。

逻辑预算继续复用 `table_analysis_max_model_calls`（0–8，默认 2）。人工请求物理上限仍是文本默认 2、图片默认 4，可降低不能提高。邻页联合判断和语义共用预算，默认预算不足时返回待完成原文，不增加调用额度。已有 OCR 的识别成本属于原提取入口，新增语义阶段不再次 OCR；通用图片/OCR 的非分析请求不被伪称为 calculation_scope 内请求。每次实际分析 HTTP 请求都计数；单请求 timeout 延用配置，没有新增跨进程总任务 deadline，外层调度仍需约束整任务时限。

所有输出仍是审核草稿。图片转录成功不等于逐字符图像核验；`image_verified` 仍为 false。跨页只保留现有关联建议，不合并数据库主体。

## 验证

失败测试记录：第一组 8 项均因目标缺陷失败；第二组 9 项均因目标缺陷失败；后续新增公式片段、显式拆分／关联、超大单元、未闭合 HTML 数学及例外说明用例也先观察到对应失败后修复。

基线：计划指定的三组测试 **205 passed**。
最终六组定向及回归命令：

```sh
.venv/bin/python -m pytest -q --no-cov \
  tests/test_pdf2md_calculation_processing.py \
  tests/test_pdf2md_calculation_sheet.py \
  tests/test_pdf2md_enhanced_single_page_tools.py \
  tests/test_pdf2md_enhanced_upload_semantics.py \
  tests/test_pdf2md_enhanced_table_query.py \
  tests/test_pdf2md_content_quality.py
```

结果：**497 passed，64 条既有配置／依赖警告**。计算书处理测试新增 37 项。
普通 data_table 查询、单页和上传回归通过；没有运行收费模型或远程业务请求。

- httpx.MockTransport + 实际 OpenAI 客户端/SSE 解码验证：第一请求携带指定 PNG；第二请求只有文本；logical_calls=physical_requests=2；SDK retries=0；image_sha256 等于实际发送图片字节哈希。
- 单物理请求上限阻止 fallback／redirect／token correction／后续语义调用突破预算。
- 非 ASME 合成符号、公式、HTML、Unicode 和不同布局；长输入后批失败与不同对象失败隔离。
- Python UTF-16 编码断言及 Node 实际执行确认非 BMP 字符之后 codepoint offset 10 对应 JS UTF-16 offset 11。
- 五个模块 AST 检查、测试中的包导入通过；两个 Dockerfile 的显式 COPY 已包含全部五个修改模块，无需新增 COPY。
- `codegraph sync`、`git diff --check` 通过。

## Membership 交接：必须完成后再宣称端到端可用

1. 同步并执行新版 producer/consumer fixture；核对新增来源版本、覆盖、阶段产物在 normalize → draft → edit → save → readback 全程保留。当前 MCP fixture SHA-256 为 `71322792a4caa22495caf1f8e0963685dba25a526cd720afc3980f5ab964040e`；Membership 仍为 `52a8ad9cfe31b9068079e2815f3d1aeaabe1ac577ecc17210827e4c0e7529b0c`，**不一致，未完成对齐**。
2. 传递用户选择的引擎／模型、裁剪和渲染参数；上游图片的真实 DPI 必须由上游记录，MCP 不能推断。
3. 持久化成功转录及 partial/failed 中可恢复来源；下一次由用户明确选择 organize_existing，并使用原授权身份和该 original_content。校验来源版本，禁止旧审核状态套用到新来源。
4. 分开保存“最新尝试”和“当前展示草稿”；失败不得覆盖人工编辑或已发布版本。验证失败 envelope 内恢复产物是否会被保留。
5. 展示 represented／structured／needs_review 差异及具体失败阶段；多来源字段保留，审核清除不能仅按相同公式文本去重。
6. source_range 为 Unicode codepoint；前端引用规范 text 前须转换 UTF-16 索引。
7. 跨页建议与单页发布独立；保留原人工发布语义，不因本轮 partial 自动发布或隐式阻断正常人工确认。

## 运行交接与剩余验收

源码目前未提交；目标镜像尚未构建，运行容器仍为上述旧镜像。
仓库禁止本 agent 构建／启动／重启容器；运行变更由获授权的操作方执行。
运行方需先保留上述旧 image ID，按现有部署配置构建并记录新 image ID，部署 `pdf2md-enhanced-mcp`，逐个核对容器 `/app/PDF2MDEnhanced/` 五个文件哈希，再调用业务入口验收。回退使用上述旧镜像及原部署配置；本轮不包含数据库迁移。

真实验收应覆盖 p13_t1、p12 的计算书、另一标准和不同语言／布局；逐项原图核对 LaTeX、条件、例外说明及整体／逐项语义，再验证普通表、人工草稿、发布、重建和刷新回读。原图中期望数量只能作为对应样例断言，生产代码没有样例／标准／页码分支。

未完成项：G0 历史完整响应取证、G5 消费方确认和持久化恢复、G6 真实模型／镜像／UI／发布验收。因此本轮不能将总目标或全部 Definition of Done 标成完成。


## 部署补记（2026-10-06 11:43，北京时间）

用户随后明确指令“部署一下”，据此执行本次构建和服务重建。仅部署
`pdf2md-enhanced-mcp`，没有重启 Router、Membership 或其他服务。

使用运行容器标签确认的原 Compose 配置：

```sh
docker compose -p aicmdengine -f docker-compose.mcp-servers.yml -f docker-compose.mcp-servers-cn.yml build pdf2md-enhanced-mcp
docker compose -p aicmdengine -f docker-compose.mcp-servers.yml -f docker-compose.mcp-servers-cn.yml up -d --no-deps --no-build --force-recreate pdf2md-enhanced-mcp
```

- 新镜像：`sha256:b1b4214fa1029c31fdf5b289a0c7b885e0d4fe3d6a8adfd208811788ff4b76e0`。
- 旧镜像已保留标签：`pdf2md-enhanced-mcp:rollback-20261006-calculation`。
- 容器启动于 `2026-10-06T03:43:03.214299917Z`，即北京时间 11:43:03。
- 部署前无网络、无数据挂载的一次性容器通过 server 导入、真实 SDK 初始化和 HTML 预处理烟雾检查。
- 部署后容器状态 `running / healthy`；通过真实 MCP HTTP 调用 `health_check` 返回 `ok=true`。
- 运行容器中五个修改模块 SHA-256 全部与已测试工作区一致：

| 文件 | 已部署 SHA-256 |
| --- | --- |
| calculation_input.py | 9ebb573cfdd316e9b4d30ce61d27e68fb7aef99dd66a8e5b4f2ce878baf31d9c |
| calculation_processing.py | d7cad1fa29fbf743d0644ef42885c2d24cf4391bb3fb2e21902d898f5ca77318 |
| calculation_sheet.py | ca25b8aea3215545e4e64010fea5d0f2663e746937ee58cc13ff0baed8db038d |
| single_page_tools.py | 89aa7ccdf30673fbdbb1b92389074b6112b240c9c47b8864354b53891357e607 |
| vlm_client.py | b519c03fed5cf81a3b44fe9731672bcf255c455770a628bf81b735f81ef8d479 |

本次正常构建重新解析了原 requirements 中未固定版本的依赖（包括 openai 3.24.0）；
新镜像环境已完成上述烟雾检查，但不将主机上的 497 项测试冒充镜像内全量回归。
没有发起收费模型请求、修改业务数据或提交 Git。G5 消费方联调及 G6 真实文档／发布回读仍未完成。

如需回退，使用已保留旧镜像重新建立目标服务：

```sh
docker tag pdf2md-enhanced-mcp:rollback-20261006-calculation pdf2md-enhanced-mcp:latest
docker compose -p aicmdengine -f docker-compose.mcp-servers.yml -f docker-compose.mcp-servers-cn.yml up -d --no-deps --no-build --force-recreate pdf2md-enhanced-mcp
```

## 2026-10-06 人工补齐 E2E 修复循环（进行中）

用户后续明确授权两侧必要修复、真实模型、针对性构建部署与样例操作；本轮验收范围收紧为现有人工补齐界面的抽取/整理、完整显示、编辑、保存、必要发布和刷新回读，不扩展自动上传、批量或 RAG 的全面验收。遵守现有架构，保留本文件前述 MCP 改动，不进行无关提交或 push。

真实 E2E 已确认：reextract 两次物理请求、2 节13单元全部保留；9个 note 因外层数学分隔符与无分隔符公式比较被拒；4个校核的空 output 被误报；普通保存将13项 semantic_status 一律改为 human_edited。

当前循环：R1 为三类缺陷补通用正负回归；R2 最小修正并执行受影响契约/普通表回归；R3 核对运行版本、定向部署；R4 真实人工补齐复验，逐项核对4条校核与9条符号说明及语义，确认保存不虚标、人工编辑不丢失、刷新回读一致；失败回到 R1。所有计数只用于样例验收，生产代码不含页码/标准特例。

本轮追加既有续页机制验收：先完成13项识别内容，再验证当前Table 4.12.2续页自动归属前页同名计算书。实际对象为p13_t1续p12_t2；p13_t2是另一表，不切换目标。采用已有continuation提案、身份校验、calculation_relation持久化及calculation_parts完整预览；不设计数据库合并。生产逻辑匹配明确续页标记、同标题主体、邻页、同租户/文档/版本/来源和计算书类型，不硬编码上述对象。


## 2026-10-06 人工补齐 E2E 收尾

本节取代上节“进行中”状态，仅完成用户本轮收紧后的人工补齐验收范围，不把其他标准、自动上传、批量或全面 RAG 验收标成通过。

### 本轮确认并修复的原因

- 旧对象框漏掉上方正式表头与续页标记。Membership 复用现有标题恢复框的上边界，保留原下边界，避免夹带下方另一张表；计算书使用220 DPI，并向MCP记录实际渲染DPI和裁剪框。
- MCP来源校验不应把最外层数学分隔符误当公式正文；空的可选 output 也不应成为来源错误。只去掉完整外层分隔符，保留符号/公式改变时的拒收。
- 语义模型反复抄写公式会改变记法、丢掉并列符号。通用预处理为每个单元提供原文 math 数组，模型选择 latex_source_index，程序原样回填并校验编号、来源和冲突值；不使用样例特例。
- 模型偶尔把表头重复到 source_text。只有前缀与独立 table_title 完全一致（允许换行空格差异）才在结构化前分离，image_transcription 保留完整原始转录。分类仍先使用原始证据。
- 复用既有 continuation 提案和 calculation_relation：按明确续页标记、相同表头、同租户/文档/版本/来源及邻页范围匹配，不合并物理表记录。
- 普通保存保留语义来源状态；仅实际修改说明的条目成为 human_edited。已发布计算书回读优先使用持久化正式表名，普通数据表优先级不变。

### 最终真实结果

- UI真实请求：reextract、calculation_sheet、page13；最后抽取任务 `6ac486c65c74ff50b02b73b0`。
- Qwen / qwen3-vl-flash：2次逻辑调用、2次物理请求（图片转录一次、文本语义一次），上限4；不是读取旧缓存冒充重新抽取。
- 2节13项，input_units=represented=structured=13，needs_review=0；语义阶段和来源校验均complete。
- 对原图逐项核对4条验收不等式、9组符号，包含大小写和内/外表面下标；13项均有语义解释，整表语义存在。早期150DPI试验的小写s误读为大写S已在最终220DPI结果消除。
- 真实UI普通保存HTTP200，刷新仍13项；编辑首项说明并点击13次 Confirm reviewed，保存HTTP200，刷新13项Reviewed，修改内容保留。12项保持model_proposed，只有实际编辑的1项human_edited；calculation_source保存前后相同。
- 从UI执行Publish and Rebuild。草稿published、reason为空；规范表13项保留，自动关系confirmed，source=automatic，predecessor=p12_t2。发布测试脚本最初误监听`/publish`而实际路由是`:publish`，脚本等待超时并非发布失败；通过规范表/草稿持久化及新的只读UI回读确认成功，未重复发布。
- 发布后刷新无空内容提示；13项Reviewed、编辑结果及正式表名保留。默认High筛选中目标消失属于问题已解决；切到All可见，无High/Draft标记。
- 现有“Preview complete calculation sheet”中p12和p13各一部分，既有逻辑主体包含两页，页号/来源仍独立；没有手选前页。
- 与测试前备份对照：43张规范表中仅p13_t1改变，其他42张完整记录不变（含前页和普通表）。无数据库直接修补。

### 测试和部署证据

- Membership最终5组测试96项通过（Inventory31、Recovery30、TableOverride14、KnowledgeEdit9、Contract12），模块编译/JAR成功；标题优先级回归先红后绿。
- MCP最终366项通过（calculation processing/sheet、single-page、ordinary table query），既有依赖告警64项；新增公式编号正反向、标题前缀保留/分离和原转录保留契约。
- 前端既有编辑器/续页预览测试9项通过，实际UI回读另行验证；没有前端源码变更或镜像重建。
- 两仓codegraph sync完成；git diff --check通过。保留MCP侧原未提交改动及Membership无关文档；本轮未提交、未push。
- 最终MCP镜像：`sha256:7f2751d31bfe86817ec14de34a28a2c6b8f47828fbae244a476f1c9c41ae4dfd`；最终API镜像：`sha256:824becbfb0d96ef2b5832069a92557dd0d8ee12694613acf8a0054ff8438b0e8`，两个容器healthy。
- 使用原运行镜像为基底定向覆盖5个MCP模块和3个Membership类。运行模块/类与已测试源码/编译结果一致；保留原基底标签供回退。没有重启Router或其他服务。
- 私有备份/截图/脚本存放 `/private/tmp/calculation-e2e-oct06/`，不提交来源内容或认证信息。`after-publish.png`及`complete-preview.png`为最终界面证据。

本轮人工补齐目标闭环通过；这不代表所有文档布局上的OCR绝对无误，也不扩展为自动上传/批量/全量RAG验收。

## 2026-10-06 通用性复验（T2 暴露问题后的继续循环，未完成）

此前 T1 单例通过不能作为通用链路完成。当前目标仍是同一人工补齐链路的自动输出正确、来源完整和可编辑保存；人工改写不得替代自动识别验收。保留已发布 T1，T2 未发布。

### 当前证据与通用修复

- T2 实际调用 qwen3-vl-flash；不是旧转录缓存。首轮失败来自末尾无效 JSON。仅计算书分阶段请求显式使用 JSON object 输出协议，保留原错误分类及物理预算。
- 完整渲染核对证明原布局框底部切到了末条公式。计算书恢复图像改用 300 DPI，复用同页邻接边界加最多 0.02 页高的底部余量，不能越过下一对象或可定位标题。已有可信/人工标题也需要恢复图像边界，不能因标题已知而跳过；普通标题读取入口不变。
- 220 DPI 完整图仍有 I/J→l/j 混淆。请求 400 DPI 被既有渲染器限制为实际 300 DPI，实验记录不能把请求值当实际值。300 DPI + Qwen 高分辨率图片参数明显改善；同图简洁转录提示词的一次对照 11 式逐项一致，但这不是整个链路最终验收。
- Qwen 高分辨率参数只加于其已知官方兼容端点的 qwen3-vl 计算书图片调用；其他模型、普通 OCR 与纯文本语义调用保持原参数。
- 转录阶段简化为保真正文和最小 JSON 字段，保留不可信来源隔离、标题/续页契约；语义阶段继续程序分节/分项/math 数组和严格来源回填校验。
- 发现“整理已有内容”没有传递已有表头语义上下文；补齐 Membership→MCP→语义目标传递，仍不发送图片、不重新 OCR。
- 当前生产 diff 检索和路径审查未发现文档 ID、页码、表名、样例公式答案或固定条目数专用分支。人工类型约束通过既有 effectiveHint 保留；新来源按 source_revision 验证。计数仅用于测试。
- 对照基准本身曾错误记入额外 2N 分母及若干系数/表面下标；已按原始完整图纠正私有测试基准。早期人工改写草稿不能作为自动识别证据，不应发布。

### 验收矩阵与证据要求

| 范围 | 自动判型/人工类型 | 入口 | 验证 |
|---|---|---|---|
| T1 原真实续页 | 保留原人工类型 | 已发布只读回读 | 13项、来源、前页关系、完整预览，无回退 |
| T2 原真实非续页 | 人工类型约束 | UI真实重新抽取 | 完整图片、实际DPI、11式逐字对照、3节、语义、保存刷新；禁止用手改代替 |
| T2 原始内容 | 人工类型约束 | 整理已有内容 | 不发图片、不重新OCR、完整保留数学及标题语义上下文 |
| 合成其他工程内容/版式 | 自动与人工约束 | auto/reextract/organize_existing | 同一处理函数，分类/语义/来源/条目覆盖及未识别失败可见 |
| 续页/非续页和邻接对象 | 自动与人工 | 既有提案机制 | 无标记不误关联、有标记按限定身份关联，单页发布独立 |
| 普通数据表/其他视觉模型 | 既有类型 | 原入口 | 无计算书视觉参数泄漏，无类型覆盖和网格行为回归 |

离线：MCP 六组 521 passed；Membership 恢复/标题/编辑/列表/普通表 92 passed，计算书契约另 12 passed；裁剪与视觉参数、文本表头回归先失败再修复。CodeGraph sync 完成。真实多样例验收仍在进行，不宣称全面完成。


### T2 图片及文本授权后复验结果（仍未整体通过）

- 新部署真实 UI 任务 `6ac4b0fdaa461e57bbb00d57`：T2 三节、十一条公式与完整原图对照一致，没有手工修改公式；覆盖 11/11，图片及语义共两次物理请求。视觉阶段仅要求正文与表头，调用端绑定实际请求身份，显式冲突仍拒绝；语义阶段版本及来源引用校验不变。
- UI 原样 Save 返回 200，刷新无空内容警告、无原始 HTML 残片，十一条公式与来源文本逐字不变。保存只改变 validation_status。此结果未发布，不能混淆为人工改正后的准确率。
- 语义人工核对未通过：部分描述仍把矩形容器解释成球壳，或从未知符号猜测弹性模量、分段数等。覆盖计数通过不等于事实正确，因此 T2 不可宣称完整验收通过。
- 整理已有 T2 正文的真实调用：一轮 11/11、一次物理请求、无图片，公式不改写；仍存在语义事实问题。之后更改语义提示词的实验出现 response_truncated，已局部撤回该实验至当前运行提示词，失败没有覆盖应用草稿。
- 非敏感合成热量计算书：自动分类先遗漏分类证据、后误判 data_table；明确返回结构和分类判据后有一轮 calculation_sheet 且 7/7。该自动分类提示词局部修改仍在源码，尚未部署。人工类型分支仍有纯文字条目错误返回数学索引、转录缺少数学分隔符等不稳定表现，不能以单次 auto 成功替代通用验收。
- 已发布 T1 只读复验：十三项 Reviewed、原人工说明保留，无空内容警告；完整预览 p12、p13 各一部分。测试前后 43 条正式 doc_tables 记录完全一致，无直接数据库修补。
- 离线六组 526 passed；撤回语义实验后两组 195 passed；依赖告警仍为既有 64 项。Membership 本轮此前 92+12 项通过。两仓 diff --check 通过，CodeGraph sync 完成。
- 当前运行 API：`sha256:c8ad01f096623a3eb6903e9dbcc49d605ca5aa5bc84afa14716d8a772e082595`；MCP：`sha256:43a61a8b9340a3baea7d7e1c119050bacb49f2fd1f9e00c250f145c732f013fc`，均 healthy。未提交、未推送。
- 后续必须以“原公式保真、纯文本项正确处理、语义仅陈述来源支持事实”共同通过为关闭条件。不得增加针对 T2 标题、页号、公式答案的规则，不得降低校验或人工修正来伪装自动成功。


### 2026-10-06 授权后的最终图片／文本复验：公式链路通过，语义验收仍未通过

本节为后续实测结论，覆盖前文旧镜像状态；目标尚未关闭。不得把覆盖率、公式匹配或 `needs_review` 草稿就绪视为语义正确。

**已修复并部署的通用问题**

- 单个源公式由程序原样绑定，不再依赖模型多余的 index=0；纯文本 null 索引合法，非法索引及多公式选择冲突仍拒绝。数学内容不因被归类 note 而消失。
- 语义输入只发送程序分节／分项的 source_sections，不重复发送整段 source_text；内部来源和版本校验保留。
- 短标题后接明确纯文本定义时保留独立分节；避免把普通 HTML 参数名／等式拆坏。合成其他工程版式的 auto 和人工约束实际模型路径均得到 3 节 6 项，覆盖 6/6。
- 当前草稿表头在创建整理任务时原来丢失。Membership 仅为缺少正式标题的计算书目标继承草稿表头，已有人工／正式标题优先，普通表不变；恢复服务复用既有标题解析，MCP 将实际表头保存在 calculation_source。回归先失败后修复。
- 仅官方 DashScope 的受支持 Qwen VL 计算书语义文本调用启用有限 thinking；普通文本、图片转录和其他模型不受影响。该设置没有保证语义准确，以下实测仍失败。
- 两端共享 V3 契约 fixture 已对齐，SHA-256 为 `71322792a4caa22495caf1f8e0963685dba25a526cd720afc3980f5ab964040e`。

**真实界面及来源对照**

- UI 重新抽取任务 `6ac4bda7e81e3d41c18d9fb1`：3 节、11 项；11 条公式与独立原图基准一致。比较保留多字符指数分组，只消除等价排版符号。2 次物理请求，预算 4，SDK 重试 0。
- 随后的 UI 整理任务 `6ac4bee2e81e3d41c18d9fb2`：3 节、11 项，11/11 原式保持；只调用 1 次文本处理，预算 2，没有图片转录。表头、original_content 和 source_revision 与重新抽取相同；source_revision 为 `9c714b60b5f90ae771980a701d4298a90794249abbb323c6a05e99519cc846e1`。
- T2 无续页标记，continuation=none，没有强迫等待下一页。
- 原样保存 HTTP 200，刷新无空内容或原始 HTML 残片。另对第一项语义做有依据的编辑并保存，刷新保留；公式与来源未改。该人工编辑仅验证持久化，不能计入模型语义正确率。没有将全部项标为 Reviewed，T2 未发布。
- 已发布 T1 只读回归：标题正确、13 项 Reviewed、原人工说明保留、无空内容警告；完整预览 p12、p13 各一部分。43 条正式 doc_tables 与本轮测试前逐记录相同，无直接数据库修补。

**未通过项及实验边界**

- 重新抽取和整理后的语义仍给未定义符号猜测物理含义，例如把系数说成模量、把符号解释成半径或分段数。标题保留和有限 thinking 没有消除此问题。
- 在获授权的同一 T2 文本上，私有对照实验分别将 system/user 分离、进一步限制为标题／明示定义支持的语义，仍出现无依据解释。这些提示词实验未部署，未覆盖草稿，也未引入文档专用规则。
- 后续应先解决语义事实约束／复核策略，而不是继续以非空 semantic_desc 或计数作为事实验收。此处不声称完整 E2E 通过，不发布错误结果。

**验证和运行状态**

- 最新 MCP 六组：536 passed，64 项既有依赖告警。Membership 相关 8 组：145 项通过，编译及 JAR 成功。两仓 diff --check 通过，源码修改批次已执行 CodeGraph sync。
- API：`sha256:2eef00da251ca4eaed7897d5a21672ed5dc9326bb5245a4c7d5caea50fd166bb`；MCP：`sha256:10f882da85c9ade6e6f0348d1cc6c325b1379a0a297f8a8279924c013bde22de`，均 healthy。
- 容器中 5 个相关 Python 模块及 5 个 Java 主类与已测试工作区／编译产物逐字节一致。只定向更新 API 与 PDF2MDEnhanced，没有重建 UI 或重启 Router。
- 私有证据在 `/private/tmp/calculation-t2-e2e/`：final-reextract-draft.json、latest-draft.json、edit-persistence-response.json、相关截图和测试日志；不提交文档内容及凭据。
- 保留已有未提交改动和无关文件，本轮未提交、未推送。


### 2026-10-06 后续循环：语义自检及转录采样约束

- 独立语义复核对照找出并删除了此前 11 项候选中的无来源物理定义。进一步的单次请求实验采用来源限定自检，并将指令与来源 JSON 分为 system/user 消息，得到不再猜测未定义字母含义的逐项描述。
- 已接入原有 staged semantic 入口：模型先排除无依据解释，再返回 semantic_desc；discarded_assumptions 仅属于模型分析响应，不新增持久化契约。程序仍原样回填源公式并验证来源版本、ID、条件与引用。没有新增模型调用，也没有增加预算。
- 英文、中文语义输出要求保持独立；来源中的指令留在 user 数据，不混入 system 指令。新增回归在旧实现因单 user 消息失败，再修复通过。普通文本消息和普通视觉任务设置不变。
- 同一 T2 图片在温度 0.2 下的一次正式调用出现最后两项上标转录错误，失败任务 `6ac4c341e81e3d41c18d9fb3` 保留，不能计为准确通过。保持图片、提示词、模型不变，仅温度改为 0 的两次独立对照均 11/11 匹配，转录内容完全一致；这不构成所有模型／文档零误差保证。
- 计算书 transcription/classification_transcription 现显式使用温度 0；不改全局 Provider 温度。旧实现的两项范围测试因温度仍为 0.7 失败，新实现保持其他视觉任务 0.7 并仅本阶段置 0。
- 最终六组回归 540 passed，64 项既有告警；CodeGraph sync 和 diff --check 通过。
- 当前 MCP 镜像 `sha256:c1209486e2d21d7637001e867b6fe216c42dda764e94fcc86e7429a54ee73e66`，healthy；API 保持 `sha256:2eef00da251ca4eaed7897d5a21672ed5dc9326bb5245a4c7d5caea50fd166bb`。
- 最终正式 reextract 任务 `6ac4c505e81e3d41c18d9fb4`：3 节 11 项，原式逐项 11/11，11 项描述均有来源用途依据，continuation=none，2 次物理调用／上限 4。模型遗漏整表 semantic_desc，系统如实标记 calculation_semantic_partial，保留全部内容。接下来验证显式 organize_existing 的文本恢复，不能将此 partial 直接声称整体成功。
- 自动和人工类型约束的不同版式合成样例均为 3 节 6 项、6/6，2 次模型调用／上限 4；公式、验收条件、纯文本符号定义保留。既有 T1 再次只读回归通过。


### 独立语义复核的决策点（尚未实现固定阶段）

- 恢复任务 `6ac4c5d4e81e3d41c18d9fb5`：1 次物理文本请求，11/11 公式与来源版本、表头、原文不变，总说明补齐。但逐项语义再次出现无依据的物理定义，因此“单请求自检”策略没有通过稳定性验收，不能仅凭 pipeline complete 判定事实正确。
- 私有独立复核试验的 11 条结果 ID 齐全且无重复，复核返回仅包含描述与删除的无依据解释，没有公式载荷；逐项人工核对未见此前的模量、半径、分段数臆测。
- 建议将独立复核设为既有 structure_calculation_source 的固定后续步骤，而不是再建解析器：仅回填复核描述，公式、来源、kind、条件、顺序及人工内容不可改；校验对象／来源版本、唯一 ID、完整候选集合、语言和非空语义。整表语义同时复核。
- 需要明确的行为变化：图片默认 3 次逻辑调用（转录、结构化、复核），已有文本 2 次（结构化、复核）；维持图片物理上限 4、文本物理上限 2，不提高 transport/SDK 重试，不循环修复。显式更小预算仍严格执行，复核未完成必须保留可恢复草稿并显式标记，不伪装通过。
- 计划修改范围：MCP 统一语义服务、模型适配器、预算契约与共享 fixture／契约测试。Membership 继续消费 typed JSON 和阶段诊断；若发现消费者不能表达复核失败，再单独列出必要补丁。普通表及源公式处理保持原机制。
- 已向用户提出默认成本／延迟选择，固定复核阶段尚未实施。T2 保持未审核、未发布；T1 保留。


### 等待独立复核成本选择期间的契约补修

- 检查发现 staged 提示词将 `conditions/references` 错写为单数 `condition/reference`，与既有解析器的字符串数组契约不一致。这是本轮提示词调整引入的问题，已纠正为数组并在输出示例中显式声明；没有新增处理阶段或模型调用。
- 回归先因缺少 `conditions:[]` 失败。补充的正反例证明：原文条件／引用可保留；旧单数字段、错误数组类型及无来源条件不会被接受，原文仍以未完成项保留。
- 最终六组 545 passed，64 项既有告警；CodeGraph sync、diff --check 通过。
- 已定向部署 MCP 镜像 `sha256:5a6fd4954d5e49409b6482d332bf652c012c0ecfcac539fa1f196cb3fe4d67ac`，healthy；运行 vlm_client.py 与已测源码一致。API／Router／UI 未变，没有新真实模型请求或数据修改。
- 独立语义复核的默认调用次数／成本选择仍未收到用户答复，因此该固定阶段没有实现。T2 的语义事实验收仍未通过，目标保持未完成；代码未提交／推送。
