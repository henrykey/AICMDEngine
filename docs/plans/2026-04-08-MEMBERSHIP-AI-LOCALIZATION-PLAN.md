# Membership 管理 AI 化与本地化方案

## 1. 目标

本方案的目标不是单纯把现有 `cmdengine` 改快，而是把 **Membership 管理能力 AI 化**，并且在架构上支持：

1. 本地演示可行
2. 对敏感客户可切换到纯本地
3. 远端能力可作为增强，而不是唯一依赖

核心要求：

- 命令检索可以本地完成
- 规划能力可以按场景切换本地 / 云
- 即使 `DocIntel` 不可用，系统仍能完成命令召回和基础规划
- 对担心数据泄露的客户，可以运行在“本地安全模式”

## 2. 范围

本阶段关注的是：

- Membership 命令知识的检索
- 自然语言到命令候选集的规划前召回
- Planner 的本地/云切换策略
- 面向演示和安全落地的运行模式设计

本阶段暂不重点解决：

- 所有领域实体解析策略的细节
- 所有 membership 业务语义的深度程序化封装
- 完整离线部署自动化

## 3. 总体原则

### 3.1 主链路与兜底链路分离

系统应明确分为三层：

1. `DocIntel` 主检索链路
2. 本地轻量语义检索链路
3. 全量命令库存兜底链路

要求：

- `DocIntel` 不可用时，不应导致命令规划不可用
- 本地 ES 不是唯一 fallback
- 最差情况下仍可回退到 full inventory

### 3.2 检索本地优先，本地安全优先

检索层比 planner 更适合先本地化。

原因：

- 命令检索是结构化、可索引问题
- 本地 embedding + 本地向量检索足够支撑 Top-N 召回
- 对客户更容易解释“知识不出本地”

### 3.3 Planner 做成可切换，而不是强制全本地

Planner 不建议第一阶段全部切到本地。

应支持：

- 本地 planner
- 云 planner
- 自动选择

这样既能演示，又能兼顾质量和保密需求。

## 4. 运行模式

建议定义三种正式模式。

### 4.1 Standard

适合内部开发和常规使用：

- 命令检索优先 `DocIntel`
- 不可用时回退本地语义检索
- Planner 可使用云模型

### 4.2 Demo Local

适合客户现场演示：

- 命令检索本地完成
- embedding 使用本地 Ollama
- planner 可以先使用 Ollama cloud 或云模型
- 不依赖远端 `DocIntel`

特点：

- 可快速演示
- 架构上已证明可脱离远端检索服务

### 4.3 Secure Local

适合对数据泄露敏感的客户：

- 检索本地
- embedding 本地
- planner 本地
- 不依赖外部在线服务

特点：

- 全链路本地可控
- 牺牲部分 planner 质量换安全性

## 5. 本地检索栈建议

本地 fallback 不建议复制一套完整 `DocIntel`。

建议采用轻量方案：

### 5.1 Full Text

使用：

- `SQLite FTS5`

原因：

- 零额外服务
- 足够支持命令文本检索
- 本地开发和演示友好

### 5.2 Embedding

使用本地 Ollama embedding 模型：

- `qwen3-embedding:0.6b`

原因：

- 本地已有
- 体积小
- 对 command retrieval 足够
- 比较适合作为默认 fallback embedding 模型

不建议第一阶段默认使用：

- `qwen3-embedding:latest`

原因：

- 成本更高
- 对 fallback 场景收益有限

### 5.3 Vector Retrieval

使用：

- `FAISS`

原因：

- 本地轻量
- 不需要额外服务
- 适合作为 command retrieval 的本地向量索引

### 5.4 检索策略

采用 hybrid retrieval：

1. SQLite FTS5 做关键词召回
2. FAISS 做语义召回
3. 合并排序
4. 产出 Top-N 候选命令

## 6. 命令知识建模

每条命令继续保留标准化检索文档形式：

- `command`
- `summary`
- `description`
- `tags`
- `parameter_names`
- `parameter_descriptions`
- `risk_level`
- `source_type`
- `source_name`

统一生成 `retrieval_text`，供：

- full text 索引
- embedding 向量化

## 7. 与现有链路的关系

### 7.1 DocIntel

`DocIntel` 继续作为主检索链路。

保留价值：

- 更完整的文档体系
- UI 可见性
- 远端检索和运维能力

但不再是单点依赖。

### 7.2 Local Semantic Retrieval

新增本地语义检索链路，作为正式 fallback。

优先级：

1. `docintel`
2. `local_semantic`
3. `full_inventory`

### 7.3 Full Inventory

保留为最后兜底：

- 直接加载 Mongo 中全量 commands
- 再加 MCP tools

说明：

- 这是最差 fallback
- 不应作为日常主要检索方式

## 8. Planner 策略

Planner 建议支持 provider 可切换：

- `cloud`
- `local`
- `auto`

### 8.1 第一阶段建议

- 检索本地化优先
- planner 先保留现有 provider 管理体系
- 本地 planner 作为可选模式接入

### 8.2 第二阶段建议

根据任务复杂度路由：

- 简单任务：本地 planner
- 复杂任务：云 planner

## 9. 配置建议

建议后续增加明确配置项：

- `COMMAND_RETRIEVAL_MODE=docintel|local_semantic|full_inventory|auto`
- `LOCAL_RETRIEVAL_ENABLED=true|false`
- `LOCAL_FTS_DB_PATH=...`
- `LOCAL_FAISS_INDEX_PATH=...`
- `LOCAL_EMBEDDING_PROVIDER=ollama`
- `LOCAL_EMBEDDING_MODEL=qwen3-embedding:0.6b`
- `PLANNER_MODE=cloud|local|auto`
- `LOCAL_PLANNER_PROVIDER=ollama`

## 10. 前端可见性建议

当前前端容易把“Local ES disabled”误解成“命令规划不可用”。

建议前端明确展示三层状态：

- `DocIntel`
- `Local Semantic`
- `Full Inventory`

在 `Command Sets` / `Task Playground` 中显示：

- 当前主检索来源
- fallback 是否可用
- 当前 planner 模式

## 11. 实施顺序

### Phase 1

完成本地轻量检索基础设施：

1. 新增本地 embedding service（Ollama）
2. 新增 SQLite FTS5 索引
3. 新增 FAISS 向量索引
4. `CommandRetriever` 接入 `local_semantic`

### Phase 2

完善状态和 fallback：

1. 后端显式暴露 `docintel / local_semantic / full_inventory`
2. 前端展示当前检索链路状态
3. `Command Sets` 页面不再把 Local ES disabled 误导成系统不可用

### Phase 3

接入 planner 模式切换：

1. `cloud / local / auto`
2. Demo Local 模式
3. Secure Local 模式

## 12. 验收标准

### 12.1 Demo Local

在没有 `DocIntel` 的情况下：

- 命令检索仍可工作
- 能召回合理 Top-N 命令
- planner 可继续执行

### 12.2 Secure Local

在不依赖外部在线服务的情况下：

- 命令知识可本地检索
- planner 可本地运行
- 基本 membership 管理任务可完成

### 12.3 用户感知

前端能清楚回答：

- 当前是否使用 `DocIntel`
- 如果不是，当前是否使用本地语义检索
- 如果再不是，是否已经回退到 full inventory

## 13. 结论

Membership 管理 AI 化的关键，不是继续堆单点规则，而是先建立稳定的基础能力：

- 主检索链路可用
- 本地语义 fallback 完整
- planner 可切换

在这个前提下，系统才能同时满足：

- 演示
- 安全
- 本地化落地

建议当前正式采纳路线：

- 主链路：`DocIntel`
- 本地 fallback：`SQLite FTS5 + Ollama embedding + FAISS`
- 最终兜底：`full_inventory`
- planner：`cloud/local/auto` 可切换
