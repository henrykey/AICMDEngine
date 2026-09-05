# PDF2MD Enhanced 全量上传语义 Goals Loop

## 后续修订：公式文本优先，失败时页面图像兜底

本节记录用户实测反馈后的新授权和当前实现，覆盖下方原始交付记录中“公式 crop 调用后跳过语义”和“一次图像语义步骤”的旧设计；其余表格、图、结构保护及对象状态契约继续有效。

- 起点：`main / 99bc34f94ab64b48d4809ca5dd4ef14da10cbc13`，工作区干净。
- 原因：公式 crop 的结构恢复不等于获得了完整上下文的语义步骤；旧实现仅因调用过 VLM 就跳过公式语义。
- 修订流程：OCR 主公式及本页正文 → 现有 VLM provider 的 text chat → 只对无有效描述的公式，发送页面图像做一次语义兜底 → 最终纯校验。正文同时使用 OCR page_text、markdown 及保留的变量说明，避免 page_text 不完整时遗漏上下文。
- 保留现有结构提取/恢复分支；公式 crop 仍可恢复 LaTeX，但不再代替正常文本语义步骤。全页原生 VLM 提取路径仍保留原有正常语义机制，不因本次修改再启动重复循环。表格继续原有图像语义步骤，图的提示词、处理及资产流程未改。
- 文本/图像合并仅接收本阶段目标 object_ref，提供了 layout_id 时必须一致；不接收新对象、重复引用或冲突引用。不覆盖原 LaTeX、OCR confidence、身份及顺序。图像阶段不能覆盖文本成功对象。
- 文本异常、空/无效响应、遗漏目标或描述只有套话时，允许一次公式图像兜底；仍失败时保留名称兜底和 missing_fields。缺名称但有有效描述不会因此发图，低语义置信度也不会自行触发循环。
- 主公式筛选：显式 inline_formula、独立变量（含下标/希腊字母/Delta 变量）、常见独立单位、明确变量解释文字归正文；保留主公式和独立数学表达式。无法确定的结构保持既有处理，不靠一个缺失等号的规则删除公式。
- 布局分类在分配 ID 前进行，主公式的原 reading_order/ID 不变；crop 后才确认是变量的条目改为 text，保留已分配 ID，不进入 formulas 成功数组，reconciliation 按 text 处理。
- 被移出公式数组的原始 LaTeX/文字保留在 render.markdown、rag.page_text 和 rag.content；原文本已有内容不重复添加，未包含时补回正文，不丢掉变量说明。
- 新增诊断：`page_result.decision.formula_semantic_calls={"text":1,"image":0}` 表示文本阶段成功，无公式图像兜底；image=1 表示有失败目标进入一次页面图像兜底。该计数是逻辑语义阶段调用数，不含原有 OCR/crop 调用；底层原有网络重试设置不变。vlm_calls 继续计入所有 VLM 逻辑调用。
- 对象语义字段继续使用下方契约，缺项和低置信度仍交由 Membership 后续处理。

执行证据：先运行新增回归得到 14 failed / 38 passed，再分批实现并执行 codegraph sync；追加回归发现并修复 OCR 部分 page_text 遮蔽 markdown 中变量说明。最终原有相关五个测试文件合计 **287 passed**，其中 upload_semantics 文件 65 项；62 条既有依赖弃用警告。测试包括真实客户端文本消息格式（只有 text、没有 image_url）及本地 PDF → process_task_page → 任务持久化，模型 wire 全部模拟。

验证命令沿用下方五文件 pytest 命令。修改的 3 个源码文件及 3 个测试文件执行 Python py_compile，配合 git diff --check 和最终差异审查。本次尚未提交、推送、部署、重启或调用真实模型；用户十五页文档的新版本验收待执行。

限制：主公式/变量分类采用明确类型和保守文本规则，复杂的多行变量说明仍可能需要真实文档样例继续校准；文字语义的事实正确性、OCR 遗漏和跨页上下文不能靠模拟测试证明。现有图像识别和结构恢复调用没有被删除；“文本优先”针对公式语义生成阶段。

---

以下为首次交付的基线、计划及历史验证记录。

## 授权与基线

- 仅本仓库 MCP、相关模拟测试及本计划；不改 Membership、历史数据或部署环境。
- 不部署、不重启、不调用真实模型、不提交或推送。
- 分支 main，HEAD `25b49d73de648bd0c2cb55a120fa77f2b4cb4ea2`。
- 初始脏文件：page_processor.py、test_pdf2md_enhanced_bad_text_policy.py；原始差异已保存到 `/private/tmp/pdf2md-semantic-baseline/preexisting.patch`。
- 旧改动评估：保留去除结构计数/上下文伪语义和名称组合的意图；重做不完整的对象状态计算；补齐名称元数据传递。既不整批沿用，也不整批删除。
- 已读取根 AGENTS.md，运行 CodeGraph status/query/context。索引提示旧引擎版本，后续每批源码修改后 sync。

## 目标与循环

1. 追踪入口与契约 → 验证 process_task_page → process_page 的 layout、GLM、VLM 分支、元数据保留和最终输出。
2. 先写失败回归 → HTML、名称组合/去重/兜底、无名称、无效描述/纯编号、结构成功语义失败、多对象隔离、独立置信度、无后补调用、图不变。
3. 修复现有分支 → 复用 extract_region_structured 的 VLM 请求能力，为 OCR 对象执行一次正常语义生成，严格按对象引用合并语义字段；VLM 原生分支强化提示词。结构、LaTeX、身份和顺序保持原有逻辑。每批源码后 codegraph sync。
4. 纯后处理 → 有效描述与显示摘要分开；记录对象 missing_fields、semantic_status，可靠语义 confidence 单独保留；页级汇总引用及缺项。无任何语义后补模型循环。
5. 验证与交付 → 模拟回归、相关既有测试、Python 语法、git diff --check 和最终差异审查；补充最终 JSON 契约和限制。

## 验收语义

- 表格 title、公式 formula_name 保留原名；formula_no 单独保留且编号不充当名称。
- description 是有效描述；semantic_summary 是名称与描述的展示组合。仅有名称时 description 缺失。
- semantic_status：complete=有有效描述（无原名也允许）；name_only=仅有名称；missing=两者都没有。
- missing_fields 记录 title/formula_name、description；无名但有描述仍记录名称缺项，不能按摘要非空判定无缺项。
- semantic_confidence 仅来自明确语义置信度，不能复制结构 confidence 或制造分数。

## 执行记录

- 基线审查：布局成功及 GLM 成功分支缺少正常表格/公式 VLM 语义调用；公式名称在 normalize 阶段丢失；页级变量兜底可能串对象。
- 已完成失败回归、分批实现、模拟验证、语法检查及最终差异审查，详见下方执行证据。

## 已完成的循环与证据

1. 新增测试先运行：12 failed / 4 passed；失败对应语义状态、名称传递、对象隔离、独立置信度及布局成功跳过 VLM。
2. 首批修复后新增 16 项全部通过；随后逐批增加失败回归，修复全页 VLM 失败后重复语义请求、Markdown 投影覆盖 HTML、公式裁剪名称/置信度丢失、结构失败对象缺项汇总，以及 OCR 纯编号阻止有效名称合并。
3. 每批源码修改后执行 `codegraph sync`，全部成功。既有两个脏文件逐段评估：保留去除假语义的目标及原有两项回归，替换旧的非空即完整判断和元数据复制实现。
4. Python `py_compile`（3 个源码文件与 4 个测试文件）、`git diff --check` 均通过；最终 HEAD/分支不变。CodeGraph sync 成功，status 显示 up to date，但仍提示索引最初由旧引擎创建；未做无关的全量重建。
5. 最终相关测试：**260 passed**，包括新增 38 项语义用例（含附录/子公式/罗马编号不充当名称）。62 条依赖弃用警告，无失败。真实本地 PDF、crop、客户端 JSON 解析、process_task_page、任务落盘与 finalize 使用模拟 wire；未调用真实模型。

验证命令：

```sh
python -m pytest tests/test_pdf2md_enhanced_upload_semantics.py tests/test_pdf2md_enhanced_bad_text_policy.py tests/test_pdf2md_enhanced_single_page_tools.py tests/test_pdf2md_enhanced_object_recovery.py tests/test_pdf2md_enhanced_task_manager.py -q -o addopts='' --disable-warnings --tb=short
```

## 最终调用边界

- `server.process_task_page` 沿用原有配置和任务语言传递，调用 `page_processor.process_page`，原样持久化/返回 page_result；server 和 task_manager 未修改。
- 成功 layout：保留 layout payload 及 recovery；表格/公式以 `object_ref=collection:index` 和原有 layout_id、bbox、HTML/LaTeX、名称、对象自身 context/variables，进入现有 `extract_region_structured` 的语义模式。整页图像提供可见原名、必要正文和变量说明；提示词要求仅使用与目标关联的内容。
- 成功 full/hybrid GLM：对现有对象运行同一正常语义步骤。OCR 名称保留；纯公式编号转入 formula_no，不阻止 VLM 返回真正名称。OCR 描述不作为已完成 VLM 语义的证据。
- 已执行公式 crop VLM 的对象不再参加第二次语义生成；其名称、说明、语义置信度直接保留。表格 crop 的 HTML-only 调用只证明结构，因此仍需要正常语义步骤。
- full/region VLM 原生路径强化表格/公式提示词与 schema，正常步骤后直接校验。全页 VLM 失败并保留 GLM 内容时不再发起语义请求。
- 语义合并只允许名称、编号、description、variables、context、明确的语义置信度；不写结构 confidence、HTML、LaTeX、身份或顺序。乱序按引用绑定；重复/缺失/冲突引用拒绝合并。原有图提示、输出、资产和恢复分支保持不变。
- 后处理不调用模型；不存在按 missing_fields 或低语义置信度驱动的后补循环。已有结构恢复重试、传输重试及 render cleanup 配置未改变。
- 优先保留已识别 table 对象；避免 render Markdown/placeholder 重新选择时遗漏 HTML 或脱离语义元数据。没有已识别对象时仍沿用原有 render 解析/占位策略。

## 返回 Membership 的最终字段契约

适用位置：`page_result.elements.tables/formulas[]`，同时出现在 `page_result.rag.elements`；无需 Membership 已修改才生效。单页 Enhance 工具的既有独立契约不在本次修改范围。

| 字段 | 定义 |
| --- | --- |
| title | 表格原名（含表号），取不到为 `""`；不生成“未命名表”等名称 |
| formula_name | 公式原名，兼容输入 name/title；纯编号不算名称，取不到为 `""` |
| formula_no | 可选原公式编号；独立保留，不能充当名称或描述 |
| description | 经校验的有效内容/用途/关系说明；取不到或仅为名称、编号、已知无效兜底时为 `""` |
| semantic_summary | 展示用名称＋有效描述，已有名称不重复；有名无描述仅显示名称（公式可含原编号）；两者皆无为 `""`，由 missing 状态表达缺失 |
| missing_fields | 表格缺 `title`、`description`；公式缺 `formula_name`、`description`。即使 summary 非空，描述缺失仍记录。没有原名但有有效描述时仍记录名称缺项 |
| semantic_status | `complete`：有有效描述，允许原文无名；`name_only`：只有有效原名；`missing`：两者均无。此字段不是质量合格/高置信度标志 |
| semantic_confidence | 可选有限数值 `[0,1]`；只透传明确语义置信度且带来源，不从结构 confidence 推导，无证据就省略 |
| semantic_confidence_source | 与 semantic_confidence 成对出现的明确来源；来源非空、数值有效才保留，不意味着经过校准 |
| confidence / status | 原有 OCR/结构置信度和结构状态，未改写；与 semantic_status 独立 |
| layout_id / source_block_index / reading_order / bbox | 原有身份、顺序和几何，保持原值。非布局链路以页面、集合和数组下标定位，不捏造布局 ID |

页级复用 `page_result.semantic_status`（以及 decision 内同一状态）：保留 `complete / missing / reason`，新增 `objects` 缺项明细。任何对象缺项会使页级 complete=false；这与对象 complete=“描述存在”不同。低置信度本身不改成 missing，Membership 可自行按独立分值筛选。

`objects` 每项携带 `collection`、`index`、可用时的 `layout_id`、`missing_fields` 和对象 `semantic_status`。布局对象结构失败、未进入成功数组时，index=null，以 layout_id 定位，缺项还包括 markdown 或 latex；原有 layout/reconciliation 继续记录结构失败。不得把 index=null 当数组下标。

### 名称兜底：结构成功，描述仍缺失

```json
{
  "layout_id": "p1-o002-table",
  "source": "glm_ocr_layout",
  "status": "EXTRACTED",
  "title": "表 1 灭火剂适用性",
  "markdown": "<table><tr><td rowspan=\"2\">气体</td><td>水</td></tr><tr><td>可用</td></tr></table>",
  "description": "",
  "semantic_summary": "表 1 灭火剂适用性",
  "missing_fields": ["description"],
  "semantic_status": "name_only"
}
```

### 有效公式描述，语义低置信度独立存在

以下分数仅为模拟契约示例，不是实测分数。

```json
{
  "layout_id": "p1-o004-formula",
  "latex": "F=ma",
  "formula_name": "牛顿第二定律",
  "formula_no": "(3)",
  "description": "合力等于物体质量与加速度的乘积。",
  "semantic_summary": "牛顿第二定律 (3)：合力等于物体质量与加速度的乘积。",
  "missing_fields": [],
  "semantic_status": "complete",
  "confidence": 0.97,
  "semantic_confidence": 0.15,
  "semantic_confidence_source": "vlm_ocr"
}
```

### 只有编号，不得认为语义完整；页级保留对象引用

```json
{
  "elements": {
    "formulas": [{
      "layout_id": "p1-o005-formula",
      "latex": "E=mc^2",
      "formula_name": "",
      "formula_no": "(4)",
      "description": "",
      "semantic_summary": "",
      "missing_fields": ["formula_name", "description"],
      "semantic_status": "missing"
    }]
  },
  "semantic_status": {
    "complete": false,
    "missing": ["formulas[0].formula_name", "formulas[0].description"],
    "reason": "object_semantic_fields_missing",
    "objects": [{
      "collection": "formulas",
      "index": 0,
      "layout_id": "p1-o005-formula",
      "missing_fields": ["formula_name", "description"],
      "semantic_status": "missing"
    }]
  }
}
```

无原名但有有效描述的例子：`title=""`、`description="比较各介质适用条件。"`、`semantic_summary="比较各介质适用条件。"`、`semantic_status="complete"`、`missing_fields=["title"]`。

## 剩余限制

- 这是源码与模拟模型验证，不是部署结果、真实文档质量验收或 Membership 集成验收。
- 原文不存在名称与模型未取得名称，目前都表现为名称缺项，MCP 不猜测原因；Membership 可以据此选择后续 Enhance/人工确认。
- 后处理只能过滤已知空洞描述和无效形式，不能证明任意自然语言描述的事实正确性；模型关联质量及置信度校准需要另行授权真实文档验证。
- 未配置 VLM、正常 VLM 失败、引用不确定或模型省略对象时，返回明确缺项；不追加语义模型循环。
- 非布局的旧结构标准化仍沿用基于内容的去重/关联；本次不重建对象身份体系。布局路径以 layout_id 保持相同内容的不同对象隔离。
- 未修改 Membership、历史数据、部署环境；未部署、重启、提交或推送。
