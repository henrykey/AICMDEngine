# Local Retrieval 微服务设计

## 1. 目标

设计并实现一个独立的本地命令检索微服务，用于在 `DocIntel` 不可用或不适合使用时，提供本地可控的命令语义检索能力。

该服务的设计目标：

1. 对 `mcp-router` / planner 来说，它只是另一套 command corpus service
2. 接口尽量兼容 `DocIntel` command corpus 子集
3. 第一阶段优先支持 Membership command sets
4. 后续可扩展到 BPMN 2.0、Form、其他 command sets
5. 支持本地演示和本地安全模式

## 2. 设计原则

### 2.1 不改变现有主结构

`mcp-router` 的职责不变：

- planner
- execution
- command set 管理
- 调用外部 command retrieval service

本地检索能力不嵌入 `mcp-router`，而是单独微服务化。

### 2.2 尽量兼容 DocIntel

本地检索服务应尽量兼容 `DocIntel` 的 command corpus API 子集：

- `POST /v2/documents/search/commands`
- `POST /v2/documents/commands/sync/batch`
- `POST /v2/documents/commands/delete`

兼容目标包括：

- 路径结构
- 请求体结构
- 响应体结构

这样 `mcp-router` 可尽量复用同一套 client 抽象，只通过 base URL 切换后端。

### 2.3 通用 command corpus，而非 membership 专用

该服务存储的是通用命令文档，而不是 membership 专属数据。

因此后续可扩展支持：

- membership
- bpmn
- form
- mcp tool command sets

## 3. 服务定位

建议服务名：

- `local-retrieval`

建议端口：

- 独立端口，固定且便于记忆
- 例如：`8088`

说明：

- 端口不必与 `DocIntel` 完全相同
- 但接口路径应尽量兼容
- 对 `mcp-router` 而言，只切换 base URL

## 4. 内部技术栈

### 4.1 Full Text

使用：

- `SQLite FTS5`

作用：

- 提供本地全文检索
- 支撑关键词 / BM25 风格召回

原因：

- 零额外依赖
- 轻量
- 对 command text 检索足够

### 4.2 Embedding

使用本地 Ollama：

- 默认模型：`qwen3-embedding:0.6b`

说明：

- 第一阶段优先轻量模型
- 后续可切换更大模型

### 4.3 Vector Retrieval

使用：

- `FAISS`

作用：

- 提供本地向量近邻检索

### 4.4 组合策略

使用 hybrid retrieval：

1. SQLite FTS5 召回
2. FAISS 向量召回
3. 分数融合 / 合并排序
4. 返回 Top-N

## 5. 数据模型

每个 command / MCP tool 统一表示为一个命令文档：

- `externalId`
- `title`
- `category`
- `content`
- `classification`
- `includeInKb`
- `metadata`

### 5.1 推荐 metadata 字段

- `entity_type = command`
- `command_id`
- `command`
- `source_type = command | mcp_tool`
- `source_name`
- `command_set_id`
- `risk_level`
- `tags`
- `parameter_names`
- `domain`
- `http_method`（可选）
- `path`（可选）
- `mcp_server`（可选）
- `mcp_tool_name`（可选）

### 5.2 category 命名建议

使用统一 namespace：

- `cmdengine.command.membership`
- `cmdengine.command.bpmn`
- `cmdengine.command.form`
- `cmdengine.command.mcp`

### 5.3 content 内容

继续使用标准化 retrieval text，例如：

- command
- source type
- source name
- summary
- description
- tags
- examples
- parameter names
- parameter descriptions
- risk level

## 6. 对外 API

## 6.1 `POST /v2/documents/commands/sync/batch`

用途：

- 批量写入 / 更新命令文档

请求体：

```json
{
  "documents": [
    {
      "externalId": "command:1:abc123",
      "title": "COMMAND: POST /v2/members",
      "category": "cmdengine.command.membership",
      "content": "Command: POST /v2/members\nSummary: Create member ...",
      "classification": 0,
      "includeInKb": false,
      "metadata": {
        "entity_type": "command",
        "command_id": "abc123",
        "command": "POST /v2/members",
        "source_type": "command",
        "source_name": "Membership API v2.4.1",
        "command_set_id": "set1",
        "domain": "membership"
      }
    }
  ]
}
```

响应：

```json
{
  "synced": 1,
  "tenantId": "1",
  "documentIds": ["command:1:abc123"]
}
```

## 6.2 `POST /v2/documents/commands/delete`

用途：

- 按 `externalIds` 删除命令文档

请求体：

```json
{
  "externalIds": ["command:1:abc123"]
}
```

响应：

```json
{
  "deleted": 1,
  "tenantId": "1",
  "externalIds": ["command:1:abc123"]
}
```

## 6.3 `POST /v2/documents/search/commands`

用途：

- 命令语义检索

请求体建议兼容现有 DocIntel 风格：

```json
{
  "query": "create a member and assign role",
  "topK": 20,
  "searchMode": "TWO_STAGE",
  "sourceTypes": ["command"],
  "sourceNames": ["Membership API v2.4.1"]
}
```

响应体建议兼容现有 command search 结果：

```json
{
  "results": [
    {
      "documentId": "command:1:abc123",
      "title": "COMMAND: POST /v2/members",
      "category": "cmdengine.command.membership",
      "totalScore": 0.91,
      "content": "...",
      "metadata": {
        "command": "POST /v2/members",
        "source_type": "command",
        "source_name": "Membership API v2.4.1",
        "risk_level": "high"
      }
    }
  ],
  "total": 1
}
```

## 6.4 可选管理接口

用于本地运维和演示：

- `GET /v1/status`
- `POST /v1/rebuild`
- `GET /v1/stats`

建议返回：

- SQLite 文档数量
- FAISS 向量数量
- 按 `source_name` / `category` 的分布

## 7. 索引存储

建议使用容器内数据目录：

- `/data/retrieval.db`
- `/data/faiss.index`
- `/data/docstore.json`

Docker 部署时挂载 volume：

- `./data/local-retrieval:/data`

## 8. 检索实现

### 8.1 写入流程

`sync/batch` 时：

1. 保存命令文档元数据到 SQLite
2. 更新 FTS5 表
3. 调本地 Ollama 生成 embedding
4. 更新 FAISS 向量索引
5. 更新 docstore 元数据映射

### 8.2 查询流程

`search/commands` 时：

1. SQLite FTS5 召回 Top-N1
2. FAISS 召回 Top-N2
3. 按 `sourceTypes/sourceNames/category/domain` 过滤
4. 融合排序
5. 返回结构化结果

## 9. 与 mcp-router 集成方式

### 9.1 建议抽象

把当前检索 client 抽象成统一接口：

- `CommandCorpusClient`

实现：

- `DocIntelCommandCorpusClient`
- `LocalRetrievalCommandCorpusClient`

### 9.2 检索优先级

建议：

1. `docintel`
2. `local_retrieval`
3. `full_inventory`

### 9.3 同步优先级

建议：

- 主链路存在时同时同步：
  - `DocIntel`
  - `local-retrieval`

如果其中之一失败：

- 记录日志
- 不阻断命令集导入主流程

## 10. 运行模式

### 10.1 Standard

- `DocIntel` 主检索
- `local-retrieval` fallback
- `full_inventory` 最终兜底

### 10.2 Demo Local

- `local-retrieval` 主检索
- `full_inventory` 最终兜底
- planner 可继续用云或 Ollama cloud

### 10.3 Secure Local

- `local-retrieval` 主检索
- planner 使用本地模型
- 无外部在线依赖

## 11. Docker 部署建议

新增独立服务：

- `local-retrieval`

组成：

- 一个 Python HTTP 服务
- 内部使用 SQLite + FAISS + Ollama client

说明：

- SQLite 和 FAISS 不是独立服务
- 它们作为该微服务内部组件即可

## 12. 为什么不做成 ES/Qdrant 两个独立服务

原因：

- 目标是轻量 fallback
- 演示部署应尽量简单
- Docker 组件越少越稳

因此：

- SQLite FTS5 足够承担全文检索
- FAISS 足够承担本地向量检索

## 13. BPMN 2.0 扩展

该服务不应设计成 membership 专属。

后续 BPMN 2.0 接入方式：

1. 生成 BPMN command documents
2. 设置：
   - `domain = bpmn`
   - `category = cmdengine.command.bpmn`
3. 同步到 local-retrieval
4. planner 按 `source` / `domain` 检索

因此，该服务应从一开始就是：

- 通用 command corpus retrieval service

## 14. 第一阶段实施建议

### Task 1

建立独立微服务骨架：

- FastAPI
- `/v2/documents/search/commands`
- `/v2/documents/commands/sync/batch`
- `/v2/documents/commands/delete`

### Task 2

实现 SQLite FTS5：

- metadata table
- FTS5 table

### Task 3

实现 Ollama embedding client：

- 默认模型：`qwen3-embedding:0.6b`

### Task 4

实现 FAISS 索引：

- upsert
- delete
- search

### Task 5

在 `mcp-router` 中新增 local retrieval client

### Task 6

完成三层 fallback：

- `docintel`
- `local_retrieval`
- `full_inventory`

## 15. 验收标准

### 15.1 功能

- 没有 `DocIntel` 时，本地检索可工作
- 可以按 query 返回合理 Top-N commands
- 支持 `sourceTypes/sourceNames`

### 15.2 可维护性

- `mcp-router` 不需要知道 SQLite/FAISS 实现细节
- 只把它视为一个 retrieval service

### 15.3 可扩展性

- membership 跑通后，可接入 BPMN 2.0 command sets

## 16. 结论

建议正式采用：

- 独立 `local-retrieval` 微服务
- 接口兼容 `DocIntel` command corpus 子集
- 内部使用：
  - SQLite FTS5
  - Ollama embedding
  - FAISS

这样既保留现有架构边界，又能为本地演示和本地安全部署提供完整的命令检索基础能力。
