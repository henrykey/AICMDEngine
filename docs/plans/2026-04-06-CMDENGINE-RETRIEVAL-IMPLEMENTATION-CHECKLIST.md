# CmdEngine Retrieval Implementation Checklist

## 1. Scope

This checklist turns the design in [2026-04-06-CMDENGINE-RETRIEVAL-OPTIMIZATION-PLAN.md](/Users/kehongwei/workspace/AICMDEngine/docs/plans/2026-04-06-CMDENGINE-RETRIEVAL-OPTIMIZATION-PLAN.md) into execution steps.

Target outcome of phase 1:

- commands and MCP tools are indexed into Elasticsearch as normalized retrieval documents
- embeddings are generated via the existing LLM provider management path
- planner uses retrieved candidate commands instead of the full command inventory
- UI can choose `auto` / `cmdengine` / `mcp`
- UI can inspect retrieval and planning diagnostics

## 2. Delivery Strategy

Recommended sequence:

1. Backend retrieval infrastructure
2. Planner integration
3. Admin and maintenance APIs
4. Frontend mode selection and diagnostics
5. Auto-routing improvements

Keep the current full-inventory planner path as fallback until retrieval-backed planning is validated.

## 3. Backend Checklist

## 3.1 Configuration

Files:

- [src/core/config.py](/Users/kehongwei/workspace/AICMDEngine/src/core/config.py)

Tasks:

- Add Elasticsearch settings
  - `elasticsearch_url`
  - `elasticsearch_api_key` or username/password fields
  - `command_search_index`
  - `command_search_index_alias`
  - `command_retrieval_top_k`
  - `command_prompt_top_k`
- Add retrieval feature flags
  - `command_retrieval_enabled`
  - `command_retrieval_fallback_to_full_inventory`
- Add embedding-related settings only if provider manager requires explicit hints
  - `command_embedding_dimensions`
  - `command_embedding_capability_name` if needed

Acceptance:

- app boots with ES config from `.env`
- missing ES config degrades cleanly when retrieval is disabled

## 3.2 Embedding Service

Files:

- add [src/services/embedding_service.py](/Users/kehongwei/workspace/AICMDEngine/src/services/embedding_service.py)
- inspect/update [src/llm/provider_manager.py](/Users/kehongwei/workspace/AICMDEngine/src/llm/provider_manager.py)
- inspect/update [src/llm/config_loader.py](/Users/kehongwei/workspace/AICMDEngine/src/llm/config_loader.py)

Tasks:

- Implement `EmbeddingService`
- Reuse provider capability selection for `embedding`
- Expose:
  - `embed_text(text)`
  - `embed_texts(texts)`
  - `get_embedding_metadata()`
- Ensure returned metadata includes:
  - provider name
  - model name
  - vector dimensions

Acceptance:

- can generate embeddings from configured embedding-capable provider
- returns dimensions consistent with index mapping
- no business code hardcodes embedding model selection

## 3.3 Retrieval Document Builder

Files:

- add [src/services/command_document_builder.py](/Users/kehongwei/workspace/AICMDEngine/src/services/command_document_builder.py)

Tasks:

- Implement builder for Mongo commands
- Implement builder for MCP tools
- Normalize fields:
  - summary
  - description
  - tags
  - examples
  - parameter names
  - parameter descriptions
  - risk level
- Build `retrieval_text`
- Add metadata:
  - `source_type`
  - `source_name`
  - `tenant_id`
  - `doc_id`
  - `updated_at`

Acceptance:

- one Mongo command maps to one normalized retrieval document
- one MCP tool maps to one normalized retrieval document
- empty optional fields do not break document generation

## 3.4 Command Indexer

Files:

- add [src/services/command_indexer.py](/Users/kehongwei/workspace/AICMDEngine/src/services/command_indexer.py)

Tasks:

- Implement ES index creation
- Implement:
  - `ensure_index()`
  - `upsert_command()`
  - `bulk_upsert_commands()`
  - `upsert_mcp_tools()`
  - `delete_docs()`
  - `rebuild_from_mongo()`
- Generate embeddings using `EmbeddingService`
- Store embedding metadata in documents
- Add index version field

Acceptance:

- can create index from empty state
- can upsert one command
- can bulk upsert imported commands
- can index MCP tool snapshots

## 3.5 Command Retriever

Files:

- add [src/services/command_retriever.py](/Users/kehongwei/workspace/AICMDEngine/src/services/command_retriever.py)

Tasks:

- Generate query embedding via `EmbeddingService`
- Query ES with:
  - BM25 query on `retrieval_text`
  - vector similarity on `embedding`
- Fuse scores
- Implement lightweight supplementation rules for membership domain
- Return:
  - raw candidates
  - final prompt candidates
  - retrieval diagnostics

Suggested response structure:

```python
{
  "resolved_mode": "cmdengine",
  "raw_candidates": [...],
  "prompt_candidates": [...],
  "diagnostics": {
    "keyword_hits": 20,
    "vector_hits": 20,
    "fusion_count": 28,
    "supplemented": ["MCP.membership.list_orgs"]
  }
}
```

Acceptance:

- query returns candidate subset filtered by tenant
- same query returns stable results across repeated runs
- helper commands are supplemented for membership tasks

## 3.6 Task Mode Selector

Files:

- add [src/services/task_mode_selector.py](/Users/kehongwei/workspace/AICMDEngine/src/services/task_mode_selector.py)

Tasks:

- Implement phase-1 heuristics for `auto`
- Rules:
  - explicit MCP/server/tool mention -> prefer `mcp`
  - simple single-step request -> prefer `mcp`
  - multi-entity business request -> prefer `cmdengine`
- Allow override when `planningMode` is explicitly provided

Acceptance:

- `auto` resolves deterministically for representative test prompts
- explicit user mode always wins over heuristic resolution

## 3.7 Planner Integration

Files:

- update [src/services/planning_engine.py](/Users/kehongwei/workspace/AICMDEngine/src/services/planning_engine.py)

Tasks:

- Inject/use `CommandRetriever`
- Replace full prompt inventory loading with retrieved candidate subset when enabled
- Keep old full-load path as fallback
- Make system-state loading conditional based on retrieved domain
- Add retrieval diagnostics to logs
- Optionally include diagnostics in response under debug mode

Acceptance:

- planner can run on retrieved candidate subset
- fallback works if ES retrieval fails
- prompt candidate count is significantly lower than full inventory count

## 3.8 Task API Model Changes

Files:

- update [src/models/models.py](/Users/kehongwei/workspace/AICMDEngine/src/models/models.py)
- update [src/routers/tasks.py](/Users/kehongwei/workspace/AICMDEngine/src/routers/tasks.py)

Tasks:

- Extend `TaskRequestContext` with optional fields:
  - `planningMode`
  - `candidateLimit`
  - `includeSystemState`
  - `preferredSources`
  - `preferredMcpServers`
- Pass new context fields into planner

Acceptance:

- old requests remain valid
- new fields can be sent from UI without breaking old flows

## 3.9 Command Index Sync on Write

Files:

- update [src/routers/command_sets.py](/Users/kehongwei/workspace/AICMDEngine/src/routers/command_sets.py)

Tasks:

- After `create_command`, call indexer upsert
- After `import/smart`, bulk index imported commands
- Return index sync summary in import response if practical
- Decide whether indexing is synchronous or background

Recommended phase-1 choice:

- synchronous for single command create
- background or bulk synchronous for import

Acceptance:

- new commands become retrievable after creation/import
- failed ES sync does not corrupt Mongo writes

## 3.10 MCP Tool Snapshot Indexing

Files:

- update startup/bootstrap path in [src/main.py](/Users/kehongwei/workspace/AICMDEngine/src/main.py)
- optionally add helper in a new MCP indexing service

Tasks:

- At startup, enumerate MCP registry tools
- Normalize and index them
- Add manual refresh support

Acceptance:

- registered MCP tools appear in command retrieval index
- refresh can be triggered without restarting if admin endpoint is added

## 3.11 Admin / Maintenance APIs

Files:

- add new router, suggested:
  [src/routers/command_index.py](/Users/kehongwei/workspace/AICMDEngine/src/routers/command_index.py)

Tasks:

- Add endpoints:
  - `POST /v1/command-index/rebuild`
  - `POST /v1/command-index/refresh-mcp`
  - `GET /v1/command-index/status`
- Restrict to internal/admin use as needed

Acceptance:

- can rebuild from Mongo
- can refresh MCP tools
- can inspect index health and metadata

## 3.12 Logging and Metrics

Files:

- update relevant services:
  - [src/services/planning_engine.py](/Users/kehongwei/workspace/AICMDEngine/src/services/planning_engine.py)
  - `command_retriever.py`
  - `command_indexer.py`
  - `embedding_service.py`

Tasks:

- Log:
  - retrieval latency
  - embedding latency
  - ES latency
  - raw candidate count
  - prompt candidate count
  - resolved mode
  - fallback usage
- If metric framework exists, add counters/histograms

Acceptance:

- logs are sufficient to compare old and new planning behavior

## 4. Frontend Checklist

## 4.1 API Client Updates

Files:

- update [ui/src/lib/api.ts](/Users/kehongwei/workspace/AICMDEngine/ui/src/lib/api.ts)

Tasks:

- Ensure task request payload can carry new context fields
- Add admin API calls if phase 2 UI includes reindex controls

Acceptance:

- new task payload fields reach backend correctly

## 4.2 Task Playground Mode Selector

Files:

- update [ui/src/pages/TaskPlayground.tsx](/Users/kehongwei/workspace/AICMDEngine/ui/src/pages/TaskPlayground.tsx)

Tasks:

- Add selector:
  - `Auto`
  - `CmdEngine`
  - `MCP Direct`
- Send chosen mode via `context.planningMode`
- Add optional candidate limit input in debug mode

Acceptance:

- user can explicitly choose mode
- request payload reflects selected mode

## 4.3 Retrieval Diagnostics Panel

Files:

- update [ui/src/pages/TaskPlayground.tsx](/Users/kehongwei/workspace/AICMDEngine/ui/src/pages/TaskPlayground.tsx)

Tasks:

- Show:
  - resolved mode
  - raw retrieval candidates
  - prompt candidates
  - whether system state was loaded
  - planning provider/model
  - embedding provider/model
- Gate extended diagnostics behind a collapsible section if needed

Acceptance:

- team can inspect retrieval behavior from UI without backend log access

## 4.4 Command Index Admin UI

Files:

- update command set page if desired:
  [ui/src/pages/CommandSets.tsx](/Users/kehongwei/workspace/AICMDEngine/ui/src/pages/CommandSets.tsx)

Tasks:

- Add optional actions:
  - rebuild index
  - refresh MCP tools
  - show index status

This can be phase 2.

Acceptance:

- operators can trigger index maintenance from UI if enabled

## 5. Suggested Git / Delivery Breakdown

Recommended PR split:

### PR 1: Config and embedding foundation

- config fields
- `EmbeddingService`
- provider manager integration for embedding

### PR 2: Retrieval document and indexing

- `CommandDocumentBuilder`
- `CommandIndexer`
- ES mapping creation
- command write sync hooks

### PR 3: Retrieval-backed planner

- `CommandRetriever`
- planner integration
- fallback behavior
- diagnostics logs

### PR 4: Task mode selection

- task request model extensions
- `TaskModeSelector`
- initial `auto` heuristics

### PR 5: Frontend controls

- mode selector
- retrieval diagnostics panel

### PR 6: Admin tooling

- rebuild/refresh/status endpoints
- optional UI maintenance controls

## 6. Test Checklist

## 6.1 Backend tests

- unit test retrieval document building
- unit test embedding service provider selection
- unit test retriever score fusion
- unit test membership supplementation rules
- integration test planner using retrieved candidates
- degraded-mode test when ES is unavailable

## 6.2 Manual scenario tests

Representative scenarios:

1. Create member and assign to org
2. Create org if missing
3. Assign role to existing member
4. OCR/PDF request that should avoid membership system-state loading
5. Explicit MCP request that should resolve to direct MCP mode

## 6.3 Performance checks

For each representative task compare before/after:

- planning latency
- prompt candidate count
- prompt size
- overall token usage

## 7. Rollout Checklist

1. Deploy with retrieval feature flag off.
2. Build and validate ES index in environment.
3. Enable retrieval for internal testing only.
4. Compare plan quality and latency against current path.
5. Enable retrieval-backed planning for selected users or tenants.
6. Enable UI mode selection and diagnostics.
7. Enable `auto` mode by default only after validation.

## 8. Completion Criteria

Phase 1 is complete when:

- ES-backed retrieval is functioning
- planner uses candidate subset instead of full inventory
- embeddings are generated through provider-capability selection
- fallback to current planner path works
- UI can choose mode and inspect retrieval diagnostics

Phase 2 is complete when:

- direct MCP path is reliable for simple requests
- index rebuild and MCP refresh are operationally manageable
- baseline latency and token costs are measurably reduced
