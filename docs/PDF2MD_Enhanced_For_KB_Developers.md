# PDF2MD Enhanced MCP - 知识库开发者应用说明

## 1. 这是什么

`pdf2md-enhanced` 是一个面向知识库构建场景的 MCP 服务，用于把 PDF 按“任务 + 单页”方式解析为可用的 Markdown 与 RAG 数据。

它的定位不是“最终知识库系统”，而是“稳定的文档理解入口层”。

---

## 2. 解决什么问题

在标准文档、扫描件、复杂表格文档中，直接做全文抽取常见问题是：

- 表格结构不稳定（尤其横向/大表）
- 页级结果无法恢复（中断后重跑成本高）
- 结果过大导致传输失败
- 模型配置切换需要改服务代码

`pdf2md-enhanced` 的核心目标是：

1. 保证“单页可落盘、可恢复、可追踪”  
2. 让复杂页至少产出“语义占位”而不是失败  
3. 把 merge/chunk/index 留给客户端知识库流水线

---

## 3. 核心特性

1. 任务化 + 单页处理
- `start_task` 创建任务
- `process_task_page` 逐页执行
- `get_task_status` / `retry_failed_pages` / `finalize_task` 管理状态

2. 动态 VLM 注入
- 模型参数由 MCP Router 运行时注入（provider/model/base_url/key）
- 不需要重启服务即可切换模型

3. 多路由策略
- `DIRECT`：文本层可靠，直接抽取
- `REGION_VLM`：文本可用，局部增强
- `FULL_VLM`：扫描/噪声页，全页理解

4. 大表/横向表稳定策略
- 对不稳定大表可自动改为 `[TABLE_PLACEHOLDER]` 语义占位
- 占位包含：表名、页号、用途与维度说明
- 避免“伪表格”污染 RAG

5. 面向知识库的输出设计
- `render.markdown`：展示与人工核对
- `rag`：检索侧信息
- 客户端可基于页级结果做 chunk / embedding / ES / vectorless

---

## 4. 与旧 PDF2MD 的关键区别

1. 不依赖 MinerU 路径（Enhanced 路径使用 Fitz + 外部 VLM）
2. 默认不做服务端大合并（`merge_mode=none`）
3. 更强调客户端控制（合并、切片、索引）
4. 对复杂表格优先“稳态语义占位”，不是强行抄全表

---

## 5. 工具接口（最常用）

1. `health_check`
2. `start_task`
3. `process_task_page`
4. `get_task_status`
5. `retry_failed_pages`
6. `finalize_task`

推荐流程：

1. `health_check`
2. `start_task`
3. 循环 `process_task_page`（按页）
4. `get_task_status`
5. `finalize_task`（通常 `merge_mode=none`）

---

## 6. 输出给知识库开发者的重点

## 6.1 Markdown 输出

- 用于阅读、审核、回溯
- 包含页标记（如 `<!-- page:80 -->`）
- 可能包含布局注释（如 `<!-- Table (x1,y1,x2,y2) -->`），可留作后处理

## 6.2 RAG 输出

- 用于检索语料构建
- 推荐使用页级对象中的：
  - `page_text`
  - `elements[*].semantic_desc`
  - `page_no/trace`

---

## 7. 推荐接入模式（知识库项目）

1. 处理模式
- 始终按页落盘（增量写入）
- 多页任务也按页顺序处理

2. 合并策略
- 服务端默认 `merge_mode=none`
- 客户端自行合并 md/rag

3. 索引策略
- 客户端（LangChain 或自研）做 chunk
- 构建向量索引或 page-index（vectorless）

4. 出错恢复
- 通过 `get_task_status` 找 pending/failed 页
- 调 `retry_failed_pages` 或按页重跑

---

## 8. 关键可调参数（常用）

在 `process_task_page.routing_config` 中常用：

- `render_dpi`：渲染清晰度（220~300 常用）
- `render_rotate_deg`：旋转（处理横向表）
- `full_vlm_retry_markdown`：FULL_VLM 失败后 markdown 回补（建议开启）
- `large_table_placeholder_enabled`：大表语义占位开关（建议开启）
- `large_table_min_cols/min_rows/min_cells`：大表判定阈值

---

## 9. 对知识库团队的落地建议

1. 把它当“文档理解前置层”，不要把所有下游逻辑塞进 MCP
2. 优先保证“页级稳定产出”，再优化表格细节
3. 对复杂标准文档，允许语义占位优先，原文页码回查兜底
4. 保留 `page_no` 与源文档映射，便于审核与纠错

---

## 10. 适用场景与边界

适合：

- 国标/行业标准
- 大量表格文档
- 扫描 PDF
- 需要断点续跑的大体量文档

边界：

- 不是最终结构化数据库映射器
- 不保证每页都还原完整数值表体
- 对“必须全量精确抄表”的页面，应结合人工核对或专门后处理

---

## 11. 一句话总结

`pdf2md-enhanced` 是一个“面向知识库构建的、稳定优先的 PDF 页级解析 MCP 服务”：  
它保证可恢复与可追踪，复杂页提供可检索语义占位，真正的知识库编排（合并、切片、索引）由客户端掌控。

