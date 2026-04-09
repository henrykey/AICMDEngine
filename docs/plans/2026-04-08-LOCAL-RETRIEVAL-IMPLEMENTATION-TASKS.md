# Local Retrieval 第一阶段实施任务

## 1. 目标

本阶段目标是交付一个最小可用的 `local-retrieval` 微服务，使其能够在没有 `DocIntel` 的情况下，为 `mcp-router` 提供本地命令检索能力。

本阶段只解决：

- 命令文档同步
- 本地全文检索
- 本地 embedding
- 本地向量检索
- `mcp-router` 三层 fallback 接入

不在本阶段解决：

- 完整 UI
- 全部领域优化
- planner 本地化

## 2. Phase 1 交付物

本阶段交付物：

1. `local-retrieval` 微服务骨架
2. `DocIntel-compatible` 三个核心接口
3. SQLite FTS5 本地索引
4. Ollama embedding client
5. FAISS 本地索引
6. `mcp-router` 接入 `local_retrieval` fallback

## 3. 服务目录建议

建议新增独立目录：

- `/Users/kehongwei/workspace/AICMDEngine/local-retrieval`

建议结构：

```text
local-retrieval/
  app/
    main.py
    config.py
    models.py
    routers/
      commands.py
      admin.py
    services/
      sqlite_store.py
      fts_service.py
      embedding_client.py
      faiss_store.py
      retrieval_service.py
    utils/
      hashing.py
  data/
  Dockerfile
  Dockerfile.cn
  requirements.txt
```

## 4. 任务拆解

## Task 1: 建立微服务骨架

### 目标

创建独立 FastAPI 服务，可本地启动、可 Docker 化。

### 需要新增

- `local-retrieval/app/main.py`
- `local-retrieval/app/config.py`
- `local-retrieval/app/models.py`
- `local-retrieval/requirements.txt`
- `local-retrieval/Dockerfile`
- `local-retrieval/Dockerfile.cn`

### 验收

- 服务可本地启动
- `/health` 返回正常
- Docker 可构建

## Task 2: 定义兼容 DocIntel 的请求/响应模型

### 目标

先把协议固定下来，避免后面反复改 client。

### 需要实现

- `POST /v2/documents/commands/sync/batch`
- `POST /v2/documents/commands/delete`
- `POST /v2/documents/search/commands`

### 需要新增

- `local-retrieval/app/models.py`
- `local-retrieval/app/routers/commands.py`

### 验收

- 三个接口可收发 JSON
- 响应结构与当前 `DocIntel` command corpus 子集兼容

## Task 3: 实现 SQLite metadata + FTS5 存储

### 目标

建立本地文档元数据表和全文检索表。

### 建议表

1. `command_documents`
- external_id
- tenant_id
- title
- category
- content
- classification
- include_in_kb
- metadata_json
- updated_at

2. `command_documents_fts`
- FTS5 虚表
- 索引 title/content/source/command/tags/parameter names 等

### 需要新增

- `local-retrieval/app/services/sqlite_store.py`
- `local-retrieval/app/services/fts_service.py`

### 验收

- sync 时可写入 SQLite
- delete 时可删除
- full text 查询可返回候选结果

## Task 4: 实现 Ollama embedding client

### 目标

本地生成命令文档向量。

### 默认模型

- `qwen3-embedding:0.6b`

### 建议接口

- `embed_text(text: str) -> list[float]`
- `embed_texts(texts: list[str]) -> list[list[float]]`

### 需要新增

- `local-retrieval/app/services/embedding_client.py`

### 配置项

- `OLLAMA_BASE_URL`
- `OLLAMA_EMBEDDING_MODEL`
- `OLLAMA_TIMEOUT_MS`

### 验收

- 能成功调用 Ollama embedding API
- 返回稳定维度向量

## Task 5: 实现 FAISS 索引与 docstore

### 目标

为命令文档建立本地向量检索能力。

### 建议文件

- `/data/faiss.index`
- `/data/docstore.json`

### 需要新增

- `local-retrieval/app/services/faiss_store.py`

### 功能

- upsert documents
- delete by external id
- search top-k
- load/save index

### 验收

- sync 后生成 FAISS 索引
- delete 能同步更新
- search 能返回 Top-N 向量结果

## Task 6: 实现 hybrid retrieval

### 目标

将 FTS 和 FAISS 结果融合，生成最终 Top-N。

### 需要新增

- `local-retrieval/app/services/retrieval_service.py`

### 推荐逻辑

1. FTS5 召回 Top-N1
2. FAISS 召回 Top-N2
3. 按 externalId 合并
4. 融合排序
5. 支持过滤：
   - tenantId
   - sourceTypes
   - sourceNames
   - category

### 验收

- `search/commands` 能返回结果
- 支持 metadata 回传
- 结果能用于 `CommandRetriever._to_planner_command_from_remote()`

## Task 7: Docker 化与本地数据卷

### 目标

让服务可通过 Docker 启动。

### 需要新增

- `local-retrieval/Dockerfile`
- `local-retrieval/Dockerfile.cn`

### compose 接入

后续可加入：

- `docker-compose.mcp-servers.yml`
- `docker-compose.mcp-servers-cn.yml`

### 验收

- `local-retrieval` 可单独容器启动
- 本地索引文件可持久化

## Task 8: 在 mcp-router 中新增 local retrieval client

### 目标

让 `mcp-router` 可把 local-retrieval 当作另一个 command corpus backend。

### 建议新增

- `src/services/local_retrieval_client.py`

### 建议抽象

- `CommandCorpusClient`
- `DocIntelCommandCorpusClient`
- `LocalRetrievalCommandCorpusClient`

如果第一阶段不做统一抽象，也至少先做独立 client。

### 验收

- client 可调：
  - `/v2/documents/search/commands`
  - `/v2/documents/commands/sync/batch`
  - `/v2/documents/commands/delete`

## Task 9: CommandRetriever 接入三层 fallback

### 目标

把命令检索优先级固定成：

1. `docintel`
2. `local_retrieval`
3. `full_inventory`

### 需要修改

- `src/services/command_retriever.py`
- `src/services/planning_engine.py`
- 必要时 `src/main.py`

### 验收

- `DocIntel` 不可用时自动回退 `local_retrieval`
- `local_retrieval` 再失败时退 `full_inventory`
- diagnostics 明确显示：
  - `docintel`
  - `local_retrieval`
  - `full_inventory`

## Task 10: 命令同步同时写入 local-retrieval

### 目标

当 command set 导入、命令新增、命令删除时，同步维护 local-retrieval。

### 需要修改

- `src/routers/command_sets.py`
- 必要时 `src/main.py`

### 同步范围

- commands
- MCP tools（如需要）

### 验收

- Smart Import 后 local-retrieval 可查询到新命令
- 删除 command set 后 local-retrieval 中相应文档被删除

## Task 11: 前端状态可见性

### 目标

避免前端把“Local ES disabled”误读成“系统不可用”。

### 需要修改

- `plan2/src/pages/CommandSets.tsx`
- `plan2/src/components/PlannerExecutorPanel.tsx`

### 需要显示

- `DocIntel: enabled/disabled`
- `Local Retrieval: enabled/disabled`
- `Full Inventory Fallback: enabled/disabled`
- 当前实际 backend

### 验收

- 前端能清楚区分三层状态

## 5. 配置项建议

## local-retrieval 服务配置

- `PORT`
- `DATA_DIR`
- `SQLITE_DB_PATH`
- `FAISS_INDEX_PATH`
- `DOCSTORE_PATH`
- `OLLAMA_BASE_URL`
- `OLLAMA_EMBEDDING_MODEL`
- `OLLAMA_TIMEOUT_MS`

## mcp-router 配置

- `LOCAL_RETRIEVAL_ENABLED`
- `LOCAL_RETRIEVAL_BASE_URL`
- `LOCAL_RETRIEVAL_PREFER_REMOTE`
- `COMMAND_RETRIEVAL_MODE=docintel|local_retrieval|full_inventory|auto`

## 6. 第一阶段推荐顺序

推荐按下面顺序推进：

1. Task 1 + Task 2
2. Task 3
3. Task 4
4. Task 5
5. Task 6
6. Task 7
7. Task 8
8. Task 9
9. Task 10
10. Task 11

## 7. 第一阶段验收标准

### 验收 A

单独启动 `local-retrieval` 后：

- 可以同步命令文档
- 可以删除命令文档
- 可以返回 Top-N 检索结果

### 验收 B

关闭 `DocIntel` 后：

- `mcp-router` 仍能完成命令召回
- diagnostics 显示 `local_retrieval`

### 验收 C

关闭 `DocIntel` 和 `local-retrieval` 后：

- 系统仍回退到 `full_inventory`

## 8. 后续阶段

第一阶段完成后，再进入：

- BPMN 2.0 command set 接入
- 本地 planner 模式
- Secure Local 完整模式
