# GB 扫描 PDF 解析与 RAG 预处理 MCP 详细设计

## 1. 目标与范围

### 1.1 目标
1. 将扫描版 PDF 转为可渲染 Markdown，并保留版面结构。
2. 精确识别文本、表格、图片、公式等区域，输出 block 级结构数据。
3. 在 embedding 前对非文本区域进行语义化描述，生成可检索文本。
4. 通过标准 MCP 协议接入现有 `AIPlanner` MCP Router/Proxy 架构。
5. 与现有 `paddleocr` 并存，支持灰度与回滚。

### 1.2 非目标
1. 不在本阶段改造前端页面。
2. 不在本阶段重构现有知识库索引引擎。
3. 不在本阶段实现大规模分布式调度。

## 2. 总体架构

### 2.1 架构概览
新增独立 MCP Server：`mineru-qwen-mcp`，放置在：
`AIPlanner/mcp/servers/mineru-qwen`

核心链路：
1. PDF 输入
2. MinerU 版面解析（初始 OCR + 区域检测）
3. 低置信/复杂区域增强（Qwen-VL）
4. Markdown 合成（渲染输出）
5. 非文本语义化与 chunk 生成（RAG 输出）

### 2.2 双通道输出
1. 渲染通道：`document_markdown + layout_blocks`
2. 检索通道：`rag_chunks + metadata`

## 3. 模块设计

### 3.1 `server.py`
职责：
1. MCP 工具注册与对外接口暴露。
2. 输入参数校验与错误码标准化。
3. 调度解析与预处理任务。

### 3.2 `parser/mineru_pipeline.py`
职责：
1. 调用 MinerU 执行版面分析与初始内容抽取。
2. 标准化输出为 block 列表。
3. 输出基础置信度与页面级统计。

### 3.3 `enhancer/qwen_vl_client.py`
职责：
1. 对低置信文本块、表格块、图片块、公式块做二次识别。
2. 管理重试、超时、降级策略。
3. 统一返回增强结果与质量标签。

### 3.4 `postprocess/markdown_builder.py`
职责：
1. 按阅读顺序合并 block。
2. 生成可渲染 Markdown（文本段、表格、公式、图片占位）。
3. 保留块到 markdown 的映射关系。

### 3.5 `postprocess/rag_preprocessor.py`
职责：
1. 对非文本块生成语义化描述。
2. 将描述与正文上下文融合，形成 embedding-ready 文本。
3. 生成 RAG 元数据（页码、块引用、类型标签）。

### 3.6 `core/chunker.py`
职责：
1. 按标题层级和语义边界切分 chunk。
2. 控制 chunk 长度、overlap 与质量评分。

### 3.7 `core/policy.py`
职责：
1. 集中管理策略参数：阈值、并发、重试、超时、降级。
2. 提供运行时开关（如禁外发模式）。

### 3.8 `core/io_guard.py`
职责：
1. 文件路径白名单与扩展名/MIME 校验。
2. 文件大小、页数等资源限制。
3. 临时文件生命周期管理与清理。

### 3.9 `observability/logger.py`
职责：
1. 结构化日志输出。
2. 关键指标采样：耗时、调用次数、失败率、降级次数。

## 4. MCP 工具接口设计

### 4.1 `parse_standard_pdf`
输入：
1. `file_path: str`
2. `options: dict`（可选）

输出：
1. `document_markdown`
2. `layout_blocks`
3. `assets`
4. `stats`
5. `warnings`
6. `errors`

用途：
1. 供前端渲染。
2. 供后续调试和质量分析。

### 4.2 `prepare_rag_chunks`
输入：
1. `file_path: str`
2. `options: dict`（可选）

输出：
1. `rag_chunks`
2. `embedding_metadata`
3. `stats`
4. `warnings`
5. `errors`

用途：
1. 直接作为 embedding 上游输入。

### 4.3 `health_check`
输出：
1. 服务状态
2. 依赖可用性（MinerU/Qwen 配置）
3. 版本信息

## 5. 数据模型

### 5.1 `LayoutBlock`
字段建议：
1. `block_id`
2. `page`
3. `type`（`text/table/image/formula`）
4. `bbox`
5. `confidence`
6. `raw_content`
7. `normalized_content`
8. `source`（`mineru` 或 `qwen`）
9. `order`

### 5.2 `DocumentParseResult`
字段建议：
1. `document_markdown`
2. `layout_blocks`
3. `assets`
4. `stats`
5. `warnings`
6. `errors`

### 5.3 `RagChunk`
字段建议：
1. `chunk_id`
2. `text`
3. `token_estimate`
4. `page_refs`
5. `block_refs`
6. `tags`
7. `quality_score`

### 5.4 `EmbeddingMetadata`
字段建议：
1. `doc_id`
2. `source_file`
3. `parse_version`
4. `created_at`
5. `non_text_enhanced`

## 6. 关键策略与算法

### 6.1 区域增强触发策略
触发条件：
1. `confidence < threshold`
2. `type in {table, image, formula}`

执行动作：
1. 截取目标区域。
2. 发送 Qwen-VL 进行定向识别/描述。
3. 回写 `normalized_content`。

### 6.2 表格语义化策略
输出双格式：
1. 结构化表格文本（Markdown/CSV）
2. 语义摘要（列含义、关键数值、结论）

### 6.3 图片语义化策略
输出：
1. 图像标题（caption）
2. 业务语义描述（对象、关系、上下文）

### 6.4 公式语义化策略
输出双格式：
1. 标准 LaTeX
2. 自然语言解释（变量定义、公式用途）

### 6.5 Chunk 切分策略
1. 优先按标题层级分段。
2. 保持语义块完整，不跨图表/公式任意拼接。
3. 通过 `max_tokens` 与 `overlap` 控制检索友好性。

## 7. 错误处理与降级

### 7.1 Qwen 调用失败
策略：
1. 指数退避重试（配置化次数）。
2. 超限后降级 `mineru-only`。
3. 将降级信息写入 `warnings`。

### 7.2 单页失败
策略：
1. 保留成功页面结果。
2. 将失败页写入 `errors.pages_failed`。
3. 不因个别页失败中断整文输出。

### 7.3 输入校验失败
策略：
1. 返回标准错误码（如 `INVALID_PATH`、`UNSUPPORTED_FILE`）。
2. 不执行解析任务。

## 8. 性能与资源控制

### 8.1 并发控制
1. 文档级串行，页级并发受信号量控制。
2. Qwen 调用并发独立限流。

### 8.2 超时控制
1. 文档级超时。
2. 页级超时。
3. 单次 Qwen 请求超时。

### 8.3 缓存策略
缓存 key：
1. `file_hash`
2. `options_hash`
3. `parse_version`

缓存命中后可直接返回已解析结果。

### 8.4 资源上限
配置项建议：
1. `max_file_size_mb`
2. `max_pages`
3. `max_qwen_calls_per_doc`

## 9. 安全与合规

1. API Key 仅通过环境变量注入。
2. 日志脱敏：密钥、长文本片段、敏感路径。
3. 临时文件存储在受控目录，任务完成自动清理。
4. 提供禁外发模式：敏感文档仅本地解析，不调用 Qwen。

## 10. 与 AIPlanner 的集成设计

### 10.1 服务落位
目录：
`AIPlanner/mcp/servers/mineru-qwen`

### 10.2 Router 直连
通过 `EXTERNAL_MCPS` 注册：
1. `transport=stdio`（默认）
2. 可选 `transport=websocket`

### 10.3 Proxy 接入
在 `AIPlanner/mcp/proxy/config/mcp-proxy-config.yml` 增加 `mineru-qwen` 配置，Router 连接 Proxy 暴露的 websocket 地址。

### 10.4 灰度与回滚
1. 与 `paddleocr` 并存。
2. 通过策略开关按文档类型或租户灰度切流。
3. 异常时快速切回 `paddleocr`。

## 11. 测试与验收设计

### 11.1 单元测试
覆盖：
1. block 分类与标准化。
2. markdown 合成。
3. rag chunk 生成。
4. 降级逻辑。

### 11.2 集成测试
覆盖：
1. MCP `initialize`。
2. `tools/list`。
3. `tools/call`（两类工具）。
4. Router 端到端调用。

### 11.3 质量测试
1. 建立 GB 文档样本集（含水印、公式、表格、图）。
2. 对比基线（现有 OCR）：
   - 公式可读性
   - 表格结构完整性
   - 图片语义可检索性

### 11.4 稳定性测试
1. 大文件、长文档压力测试。
2. 限流与超时场景测试。
3. 局部失败容错测试。

## 12. 配置项设计（建议）

### 12.1 LLM 配置来源
1. 不新增独立的 Qwen 配置项。
2. 统一复用 MCP Router/AIPlanner 现有 LLM Provider 配置（如 `config/llm_providers.yaml` 与对应环境变量注入机制）。
3. `mineru-qwen-mcp` 仅通过 Router 注入的标准运行上下文读取模型配置，不维护第二套密钥与模型定义。

### 12.2 仅新增解析运行参数
1. `MINERU_OUTPUT_DIR`
2. `MAX_FILE_SIZE_MB`
3. `MAX_PAGES`
4. `MAX_QWEN_CALLS_PER_DOC`
5. `QWEN_TIMEOUT_SEC`
6. `QWEN_MAX_RETRIES`
7. `ALLOW_EXTERNAL_VLM`（true/false）

## 13. 版本与里程碑

### 13.1 版本规划
1. `v0.1`：MVP（parse + health + Router 接入）
2. `v0.2`：RAG 预处理（非文本语义化 + chunks）
3. `v1.0`：稳定性与可观测性完善，进入生产灰度

### 13.2 里程碑
1. M1：接口与数据模型冻结
2. M2：MVP 联调通过
3. M3：质量与性能达标
4. M4：灰度上线与回滚演练完成

## 14. 风险与对策

1. 依赖版本漂移风险  
对策：锁版本，启动时自检并输出版本。

2. Qwen 限流/成本风险  
对策：并发限流、请求配额、失败降级。

3. 水印复杂场景识别波动  
对策：预处理开关 + Prompt 模板版本化 + 质量回归样本。

4. 大文档耗时过长  
对策：页级并发、缓存、可中断与断点续跑（后续版本）。

## 15. 交付清单

1. 设计文档（本文件）。
2. MCP Server 源码与依赖文件。
3. Router/Proxy 配置模板。
4. 测试脚本与验收报告模板。
5. 运维排障文档。

## 16. 实施任务清单

### 16.1 需求冻结
1. 确认工具接口：`parse_standard_pdf`、`prepare_rag_chunks`、`health_check`。
2. 确认统一返回字段与错误码规范。

### 16.2 工程骨架搭建
1. 创建目录：`AIPlanner/mcp/servers/mineru-qwen`。
2. 初始化入口、依赖管理、配置加载、日志模块。

### 16.3 MCP 基础能力
1. 实现 `health_check`。
2. 完成 stdio 模式下 `initialize/tools/list/tools/call` 联调。

### 16.4 解析主链路（MVP）
1. 接入 MinerU：PDF -> layout blocks。
2. 实现 markdown builder。
3. 实现 `parse_standard_pdf` 基础输出。

### 16.5 Qwen 增强链路
1. 实现低置信与复杂块触发策略。
2. 实现表格、图片、公式三类增强处理。
3. 增加 Qwen 失败自动降级（MinerU-only）。

### 16.6 RAG 预处理
1. 实现非文本语义化描述生成。
2. 实现 chunker（含 metadata）。
3. 实现 `prepare_rag_chunks` 输出。

### 16.7 安全与稳定性
1. 路径白名单、类型校验、文件大小与页数限制。
2. 并发控制、超时控制、重试退避、调用配额。
3. 临时文件清理与日志脱敏。

### 16.8 Router/Proxy 集成
1. 提供 `EXTERNAL_MCPS` 接入配置样例。
2. 提供 MCP Proxy 接入样例（可选）。
3. 与现有 `paddleocr` 并存灰度验证。

### 16.9 测试与验收
1. 单元测试：block 分类、markdown、chunk、降级逻辑。
2. 集成测试：MCP 端到端工具调用。
3. 样本对比测试：公式、表格、图片描述质量与检索效果。

### 16.10 文档交付
1. 部署手册。
2. 运维排障手册。
3. 验收报告模板与回滚说明。
