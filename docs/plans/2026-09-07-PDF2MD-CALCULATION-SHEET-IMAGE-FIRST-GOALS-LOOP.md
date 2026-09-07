# 计算书图像直提与人工指定类型 — 可执行 Goals Loop 计划

日期：2026-09-07
状态：仅计划，尚未执行本计划的代码修改或验证。
仓库：/Users/kehongwei/workspace/AICMDEngine
编写时基线：main / 2733ca3；工作区在创建本文件前干净。

## 1. 已确认的目标与权限边界

本轮目标是正常提取与可持久化的记录契约，不包含问答、检索效果或问答测试。
计算书仍是现有 table 对象的子类型，不创建重复的顶层计算书对象。
普通表格保持现有解析；计算书从图像直接提取 JSON，不依赖先生成正确 HTML。

本次用户仅要求创建可执行计划。后续执行本计划需要实施指令；获得实施指令后可开展
MCP 源码、测试、契约和执行报告修改。提交、推送、构建、重启、部署、Membership
代码与数据库操作不随本计划自动授权。Membership 落库作为独立交接与验收阶段。

真实模型调用另行明确样本、外部目的地、调用/token 预算及重试规则后执行。
此前 p15 向 Qwen 的两次单次授权均已消耗，不沿用为本计划的额度。
不得把模拟响应、人工整理的 JSON 或旧测试数量冒充新方案的真实验收。

## 2. 设计决策

### 2.1 复用工具，增加解析路径参数

不新增 MCP 工具。给现有 extract_page_tables 增加：

```json
{"table_kind_hint": "auto"}
```

| 值 | 行为 |
| --- | --- |
| auto（默认） | 图像主导、OCR 辅助分类，再选择解析方法 |
| calculation_sheet | 人工指定计算书，跳过分类，直接调用图像计算书提取 |
| data_table | 人工指定普通表格，沿用普通表格解析，不由分类模型覆盖 |

这是强制路径选择，不是可被模型覆盖的软提示。非法值在 provider 构造前拒绝。
返回记录保留 table_kind 与 table_kind_source=manual/auto；manual 仅表示类型由调用方
明确指定，不代表已经人工审查内容，也不作为授权凭证。兼容旧确定性路径且未分类时，
table_kind_source 使用 unclassified，不能假称自动识别成功。

人工选择与范围选择分开：类型决定怎么解析；文件身份、页码、layout_id、bbox 决定解析哪里。
复用 context.structure_target 的身份、源文件哈希、页码和 bbox 校验，不另建目标协议。
指定目标时只处理该目标；不按同页相邻内容补全。无区域时明确为整页范围；整页有多个对象，
不得将它们强行合成一个计算书，不确定则返回目标范围不明确。

query_enhancement 与强制计算书提取同时传入时，在调用前返回参数冲突；不可绕进旧查询路径。
不得把表格行列输出格式参数解释为要求将计算书 JSON 转成 CSV/TSV/HTML；计算书对象明确返回
content_format=calculation_sheet_json，并说明 table_rows_format 仅适用于普通数据表。

### 2.2 分类与提取分开

自动路径：确定目标图像 → 分类（可参考 OCR）→ 普通表格或计算书专用解析。
人工计算书路径：验证目标 → 渲染/裁剪 → 计算书专用解析，分类调用为 0。

分类不再要求依据必须是 OCR 的精确原样子串。保存模型图像判断依据及不确定状态，不能仅因
OCR 错字、符号损坏而否决图像判断。不要以标题或单个公式作为唯一分类依据。
自动分类为 mixed/uncertain 时保留来源并标记待核对，不自动分区、不强行切换路径。

计算书提取请求只包含：目标图像、服务端确定的对象身份、页码、图像区域及必要输出协议/语言。
不传旧 OCR 文本、错误 HTML、旧语义说明或用户提供的参考答案作为内容依据。
分类结果只控制分流；不把分类阶段的 OCR 推测内容带入正式提取提示。
图片来源使用真实解码图像绑定；文件哈希与图像/裁剪哈希分别命名，替换现有 OCR 文本哈希绑定。
禁止把旧 source_sha256 的含义从文本偷偷改成图像。

复用现有 extract_calculation_sheet 方法和裁剪能力；不增加第二套同用途解析器。
裁剪坐标、旋转、归一化坐标与原页回映必须明确。若模型接收裁剪图，其 item bbox 按裁剪图
归一化，再由代码回映到原页，不再次套用原页 bbox。

### 2.3 正式内容是 JSON

建议返回契约（键名在 G1 固化，需版本化）：

```json
{
  "type": "table",
  "table_kind": "calculation_sheet",
  "table_kind_source": "manual",
  "content_format": "calculation_sheet_json",
  "layout_id": "既有对象身份",
  "title": "原文表名",
  "calculation_sheet": {
    "contract_version": "2",
    "sections": [
      {
        "title": "原文分组",
        "items": [
          {
            "id": "对象内稳定标识",
            "kind": "input",
            "name": "原文计算项名称",
            "symbol": "",
            "formula": "",
            "unit": "",
            "conditions": [],
            "checks": [],
            "references": [],
            "source_region": []
          }
        ]
      }
    ],
    "footnotes": []
  }
}
```

source_region 的坐标空间和页码通过明确来源元数据提供；未知位置不编造。
原图/文件来源与质量字段沿用可复用的现有契约；不为示例重复建立 identity 或 quality 体系。
item.kind 支持 input/formula/branch/check/reference/note；名称不明时允许留空并记录疑点，
不能为了通过必填检查而编造名称。保留脚注标识及关联，避免只保留脚注文本却丢失适用对象。
每项保留内容和原文顺序，不自行生成计算依赖、查图值、数值结果或所谓物理意义修正。

JSON 是正式提取内容：即使 markdown/raw_html 为空，合法计算书仍必须能生成、返回和保存对象。
旧 OCR/HTML 可作为诊断材料留存，不作为成功前提或计算书校验基准。展示派生不是首要验收项。
不把计算书 JSON 塞成字符串伪装为普通表格行列，不生成普通 lookup_sections。
保留普通表格查询能力，不在本计划开发计算过程问答。

### 2.4 数学字符原则（暂定，需验证）

Unicode 希腊字母可保留；参数说明不强制 LaTeX 化。复杂公式可采用 LaTeX。
目标是语义准确、字符不丢失、能够正常显示，不以某一种编码作为成功条件。
字段 formula 表示公式表达，不命名为强制 latex；v1 的 latex 字段须有显式兼容/迁移说明。
不进行全局希腊字母替换、强制字符归一化或 LaTeX 重写。最终显示效果另列为兼容验证，
不能仅以 JSON round-trip 宣称 Membership 公式渲染通过。

### 2.5 质量与预算

删除计算书对 OCR 子串、OCR 字符覆盖率的强制校验；普通数据表的来源校验不改。
继续验证身份、页码、图像哈希、目标范围、JSON 结构、非空有效计算项、类型、长度上限、
分支条件、校核关联以及明确 LaTeX 表达的括号/环境完整性。未知/无法检查的表达标记疑点，
不能因普通 Unicode 参数缺少 LaTeX 语法而拒绝。

分别报告分类、提取、结构验证和原图复核状态。结构合法不代表公式或项目完整。
未独立复核的图像内容保持待核对；不盲目沿用 v1 的 source_validated 字样。
人工指定类型不等于内容质量通过。空 sections/items、截断、身份错配不可标完成。

沿用明确预算机制，但预算归属必须重新核对：自动分类与专用提取共用一个分析预算；
人工指定计算书不扣分类调用，预算 1 应可执行一次提取。多对象不各自获得新预算。
显式目标的 max_model_calls 与分析预算同时存在时取可用上限的较小值，不相加；
分别记录 OCR、分类、提取逻辑调用及传输重试。保留预算为 0/禁用 provider 时零调用行为。
不暗中提高 token/重试上限；分类无旧 OCR 可用时不得为取得辅助文本而隐式追加 OCR 调用。

## 3. 执行前检查

- 核对实际 checkout、分支、HEAD、dirty hunks；当前基线仅是编写快照。
- 阅读各级 AGENTS.md 和现有 CONTENT_QUALITY_CONTRACT、CALCULATION_SHEET_CONTRACT、
  TABLE_QUERY_CONTRACT，以及首版 EXECUTION 报告。
- CodeGraph status/query/context 查相关调用链；失败则记录并定向读源码，不擅自全量重建。
- 追踪 server.py 工具签名、single_page_tools.py 的 direct/_extract_single_page/structure_target
  分支、page_processor.py 正常上传/恢复/输出归一化、vlm_client.py 专用调用、
  calculation_sheet.py 验证器、table_query.py 类型门禁及 Docker COPY。
- 同时检查提前按空 markdown 丢弃 table、按 HTML 闭合判成功、只从字符串构造 metadata 的路径。
  仅改提示词不算完成，不得为了保住对象而生成虚假 HTML。
- 查询入口、正常上传、人工补齐必须共享分流/提取实现，不创建互相分化的副本。

## 4. Goals Loop 与分项验收

每个 G：记录现状/不变量 → 先建立失败用例 → 最小修改 → 针对回归 → 自审 → 更新执行报告。
每批代码变动尝试 CodeGraph sync；计划编写阶段不运行 sync、模型或测试。

### G1：工具与记录契约

工作：为现有 extract_page_tables 签名、转发和暴露的 schema 增加 table_kind_hint；
固化 v2 JSON、来源绑定、质量字段与 v1 兼容规则。禁止新增同用途 MCP 工具。

验收：旧调用可用；三个值正确传递；非法值/参数冲突/无效目标在 provider 构造前拒绝。
输入 hint 与返回实际类型、来源区分；人工强制类型不被模型覆盖。

### G2：人工路径与自动路径分流

工作：人工计算书在 OCR、native grid、HTML 恢复和类型分类之前分流；直接使用目标图像。
自动路径允许 OCR 辅助分类，但不依赖 OCR 原样证据；正常上传复用相同分类与专用提取。
人工普通表格保持原路径。已识别计算书不得因 OCR 没有产出 table payload 而被漏掉。

验收：坏 OCR、空 OCR、无 HTML 三种情况下强制计算书均能进入专用图像调用；
分类为 0、pandas 为 0；普通表格反例不改变；mixed/uncertain 不静默改路。
目标页/对象外的区域与数据均不参与；目标哈希不符时零 provider 调用。

### G3：图像直提与质量校验

工作：专用调用移除 OCR/text source quotes 约束，采用单一计算项 JSON schema；
原图提取，不猜测修正。更新解析器和图像来源身份校验，保留分组、公式、条件及脚注关系。

验收：检查实际 wire payload，确认无旧 OCR、HTML、旧描述、人工参考 JSON；
错误 OCR 内容更换不会改变专用请求（目标图像/身份不变时）。
支持 Unicode 参数、Unicode/LaTeX 公式及混合表示；允许正常转写而非强制 OCR 子串一致。
空项、截断、错误身份、越界/错坐标空间、不完整分段条件均有失败用例；不夸大图像覆盖率。

### G4：JSON 对象贯穿输出与持久化交接

工作：消除计算书对非空 markdown/table HTML 的依赖，贯穿 output elements、RAG elements、
单页 items/tables、首表字段提升、TaskManager 本地任务结果序列化及显式补齐返回。
维持同一 layout_id，不重复插入对象；普通表格查询门禁保留。

验收：仅 JSON 的计算书能在上述入口完整 round-trip；脚注、条件、Unicode、来源、质量不丢失。
自动与人工在同一目标上输出同一契约；区别仅在类型来源、调用记录及真实提取内容。
TaskManager 文件结果不是 Membership 数据库验收，必须分别报告。

交接给 Membership（本计划仅写契约/检查清单，不修改其代码或数据）：
1. 人工补齐提供自动/普通表格/计算书选择并传递 hint、目标和预算。
2. 确认既有表格实体及数据库记录可以保存 table_kind、content_format 和嵌套 calculation_sheet。
3. 同对象补齐按既有生命周期更新该记录，保留身份，不产生第二个计算书对象；禁止空 HTML 导致丢弃。
4. 验证 MCP raw → API 映射 → 数据库 → 重新读取各字段一致，尤其检查是否丢弃未知字段。
5. 源字符与公式显示兼容单独检查。不做问答测试、不修改问答链路。

### G5：离线回归、自审与报告

优先扩展 tests/test_pdf2md_calculation_sheet.py 及现有 single_page/upload/object_recovery 测试。
删除/改写本轮明确废弃的 OCR 子串断言，不顺带放松普通表格数据来源断言。

```sh
.venv/bin/python -m pytest -q --no-cov \
  tests/test_pdf2md_calculation_sheet.py \
  tests/test_pdf2md_quality_completion.py \
  tests/test_pdf2md_content_quality.py \
  tests/test_pdf2md_enhanced_table_query.py \
  tests/test_pdf2md_object_semantics.py \
  tests/test_pdf2md_enhanced_single_page_tools.py \
  tests/test_pdf2md_enhanced_object_recovery.py \
  tests/test_pdf2md_enhanced_upload_semantics.py \
  tests/test_pdf2md_enhanced_bad_text_policy.py
```

再运行相关 py_compile、git diff --check 和已有 Docker COPY 隔离导入测试，不实际构建镜像。
529 passed 是旧版本证据，不是本计划结果。报告记录新命令、通过/失败数量及未解决项。
自审特别检查：隐式 OCR/VLM 调用、错误类型回退、区域泄漏、JSON 被丢弃、字符改写、重复对象。

### G6：有界真实提取验收（另行授权）

样本：p15 复杂计算书、一份可用的简单计算书、一页普通数据表。样本清单与去向确认后运行。
用户提供的对话 JSON 只作结构参考，已知含公式/脚注识别疑点，不作为正确答案或模型输入。
简单样本缺失时先报告，不用合成样本冒充真实标准样本。

建议首批最多 5 次逻辑调用，不含 OCR、不自动追加：
- p15 自动分类 1 + 图像提取 1；
- 同一 p15 人工指定计算书提取 1；
- 简单计算书人工指定提取 1；
- 普通表格分类反例 1。

这是待批准预算，不是授权。运行前确认实际 provider/model/endpoint、每次输出 token 上限、
传输重试/物理调用上限；不得把界面别名等同于已验证底层模型。
对原图逐项核对：分类、输入项、计算式、上下标、单位、条件、校核、引用、脚注和顺序；
区分缺失、误识别和额外编造。出现问题先保存证据/做离线修正，不循环消耗外部额度。
不以 JSON 合法、EXTRACTED 或流程未报错替代原图准确性验收；不测问答。

## 5. 执行报告与完成条件

执行时新建同目录 2026-09-07-PDF2MD-CALCULATION-SHEET-IMAGE-FIRST-EXECUTION.md。
保留旧执行报告作为历史，不把历史失败改写成新版本成功。

报告分别列明：
- G1–G5 源码与离线契约完成情况、变更文件、失败前后证据；
- G6 真实分类/提取结果和具体缺陷；
- TaskManager 本地序列化结果；
- Membership 数据库集成是否授权/是否实际验收；
- 源码提交、镜像/runtime 来源与部署状态；
- Unicode 存储/输出兼容与真实显示验证各自结论。

G1–G5 可独立完成，不因未授权部署或 Membership 写入而停止本地工作；
真实或数据库未验收时必须明确未完成，不宣称端到端完成。
本计划不包含模型能力比较研究、计算执行、问答、自动混合分区、跨页推理或历史数据批量迁移。
