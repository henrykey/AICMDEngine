# CmdEngine Retrieval Development Tasks

## 1. Task List Overview

This task list is intended for implementation tracking. It breaks the retrieval-backed cmdengine plan into concrete development tasks with suggested order, ownership boundaries, and acceptance checks.

Recommended execution order:

1. backend foundation
2. retrieval indexing
3. planner integration
4. mode selection
5. frontend controls
6. admin and rollout support

## 2. Phase 1: Backend Foundation

## Task 1.1: Add Elasticsearch and retrieval config

Scope:

- add ES-related settings to backend config
- add retrieval feature flags
- add retrieval sizing config

Files:

- [src/core/config.py](/Users/kehongwei/workspace/AICMDEngine/src/core/config.py)

Details:

- add:
  - `elasticsearch_url`
  - `elasticsearch_api_key`
  - `command_search_index`
  - `command_search_index_alias`
  - `command_retrieval_enabled`
  - `command_retrieval_fallback_to_full_inventory`
  - `command_retrieval_top_k`
  - `command_prompt_top_k`

Acceptance:

- app starts with new config fields
- missing values do not break startup when retrieval is disabled

## Task 1.2: Review and expose embedding-capable provider selection

Scope:

- verify current provider manager can select `embedding`
- fill any gaps in capability-driven provider selection

Files:

- [src/llm/provider_manager.py](/Users/kehongwei/workspace/AICMDEngine/src/llm/provider_manager.py)
- [src/llm/config_loader.py](/Users/kehongwei/workspace/AICMDEngine/src/llm/config_loader.py)
- [src/llm/model_capabilities.py](/Users/kehongwei/workspace/AICMDEngine/src/llm/model_capabilities.py)

Details:

- ensure embedding-capable providers can be discovered reliably
- ensure dimensions can be surfaced to callers

Acceptance:

- provider manager can resolve one embedding-capable model
- dimensions and provider metadata are accessible

## Task 1.3: Implement EmbeddingService

Scope:

- add a dedicated service for embedding generation using provider manager

Files:

- add [src/services/embedding_service.py](/Users/kehongwei/workspace/AICMDEngine/src/services/embedding_service.py)

Details:

- implement:
  - `embed_text(text)`
  - `embed_texts(texts)`
  - `get_embedding_metadata()`
- no hardcoded embedding model in business logic

Acceptance:

- service can generate embeddings for one text and batch texts
- metadata includes provider, model, and dimensions

## 3. Phase 2: Retrieval Document and Indexing

## Task 2.1: Implement CommandDocumentBuilder

Scope:

- normalize Mongo commands and MCP tools into common retrieval documents

Files:

- add [src/services/command_document_builder.py](/Users/kehongwei/workspace/AICMDEngine/src/services/command_document_builder.py)

Details:

- build `retrieval_text`
- map all useful fields:
  - summary
  - description
  - tags
  - examples
  - parameter names/descriptions
  - risk level

Acceptance:

- builder produces valid retrieval documents for:
  - a Mongo command
  - an MCP tool
  - commands with sparse metadata

## Task 2.2: Implement CommandIndexer

Scope:

- create and maintain ES retrieval index

Files:

- add [src/services/command_indexer.py](/Users/kehongwei/workspace/AICMDEngine/src/services/command_indexer.py)

Details:

- implement:
  - `ensure_index()`
  - `upsert_command()`
  - `bulk_upsert_commands()`
  - `upsert_mcp_tools()`
  - `rebuild_from_mongo()`
  - `delete_docs()`
- generate embeddings using `EmbeddingService`
- include embedding metadata and index version in stored docs

Acceptance:

- index can be created from scratch
- one command can be upserted
- bulk import can be indexed

## Task 2.3: Define ES mapping and index creation behavior

Scope:

- finalize ES mapping for retrieval docs
- ensure index creation is deterministic

Files:

- `command_indexer.py`
- optionally docs or embedded mapping constant

Details:

- implement dense vector mapping
- validate dimensions against selected embedding provider

Acceptance:

- mapping is applied automatically when index is missing
- embedding dimensions match mapping

## Task 2.4: Sync command indexing on Mongo writes

Scope:

- hook ES indexing into command create/import flows

Files:

- [src/routers/command_sets.py](/Users/kehongwei/workspace/AICMDEngine/src/routers/command_sets.py)

Details:

- after single command create: upsert into ES
- after smart import: bulk upsert into ES
- Mongo write must remain source of truth if ES indexing fails

Acceptance:

- newly created commands are retrievable
- import flow indexes imported commands
- write failure handling is explicit

## Task 2.5: Add MCP tool snapshot indexing

Scope:

- index runtime MCP tools into ES

Files:

- [src/main.py](/Users/kehongwei/workspace/AICMDEngine/src/main.py)
- optionally helper module under `src/services/`

Details:

- enumerate MCP registry at startup
- convert tools into retrieval docs
- index them

Acceptance:

- MCP tools appear in retrieval results
- startup refresh is logged

## 4. Phase 3: Retrieval Query Path

## Task 3.1: Implement CommandRetriever

Scope:

- query ES using keyword and vector retrieval

Files:

- add [src/services/command_retriever.py](/Users/kehongwei/workspace/AICMDEngine/src/services/command_retriever.py)

Details:

- generate query embedding via `EmbeddingService`
- run keyword retrieval
- run vector retrieval
- fuse scores
- trim to raw top-k

Acceptance:

- returns stable candidates for representative goals
- tenant filtering is always applied

## Task 3.2: Add membership supplementation rules

Scope:

- ensure multi-step membership tasks get helper commands

Files:

- `command_retriever.py`

Details:

- if primary candidate is write-oriented:
  - supplement list/get helper commands for org/member/role workflows

Acceptance:

- create-member workflow includes helper commands like `list_orgs` or equivalent

## Task 3.3: Return retrieval diagnostics

Scope:

- expose enough metadata for tuning

Files:

- `command_retriever.py`

Details:

- include:
  - raw candidate count
  - prompt candidate count
  - score fusion stats
  - supplementation info
  - embedding provider/model

Acceptance:

- diagnostics are available to planner logs and optionally API response

## 5. Phase 4: Planner Integration

## Task 4.1: Refactor PlanningEngine to use CommandRetriever

Scope:

- switch planner prompt input from full inventory to retrieved candidates

Files:

- [src/services/planning_engine.py](/Users/kehongwei/workspace/AICMDEngine/src/services/planning_engine.py)

Details:

- integrate `CommandRetriever`
- use retrieval-backed candidate list when feature flag enabled
- keep old full-inventory path as fallback

Acceptance:

- planner works with candidate subset
- fallback path still works if retrieval fails

## Task 4.2: Make system-state loading conditional

Scope:

- avoid eager membership state loading for unrelated tasks

Files:

- [src/services/planning_engine.py](/Users/kehongwei/workspace/AICMDEngine/src/services/planning_engine.py)

Details:

- load org/role/member state only if retrieved candidates indicate membership domain

Acceptance:

- OCR/PDF/KB tasks skip membership state loading
- membership tasks still get helpful state context

## Task 4.3: Add retrieval-aware logging

Scope:

- improve observability of new planner path

Files:

- [src/services/planning_engine.py](/Users/kehongwei/workspace/AICMDEngine/src/services/planning_engine.py)
- `command_retriever.py`
- `embedding_service.py`

Details:

- log:
  - resolved mode
  - retrieval latency
  - candidate counts
  - fallback usage
  - prompt candidate commands

Acceptance:

- logs make it obvious whether request used retrieval or full inventory

## 6. Phase 5: Mode Selection

## Task 5.1: Extend TaskRequestContext

Scope:

- add mode and retrieval-control fields to task request

Files:

- [src/models/models.py](/Users/kehongwei/workspace/AICMDEngine/src/models/models.py)

Details:

- add:
  - `planningMode`
  - `candidateLimit`
  - `includeSystemState`
  - `preferredSources`
  - `preferredMcpServers`

Acceptance:

- new fields are optional and backward compatible

## Task 5.2: Implement TaskModeSelector

Scope:

- choose `auto`, `cmdengine`, or `mcp`

Files:

- add [src/services/task_mode_selector.py](/Users/kehongwei/workspace/AICMDEngine/src/services/task_mode_selector.py)

Details:

- implement phase-1 heuristics:
  - explicit tool/server mention -> `mcp`
  - simple request -> `mcp`
  - multi-step business request -> `cmdengine`

Acceptance:

- explicit mode overrides heuristics
- `auto` produces predictable results for test cases

## Task 5.3: Wire mode selection into task route

Scope:

- pass selected mode through task API to planner/executor path

Files:

- [src/routers/tasks.py](/Users/kehongwei/workspace/AICMDEngine/src/routers/tasks.py)
- possibly planner service wiring

Acceptance:

- backend receives and logs selected/resolved mode

## Task 5.4: Implement direct MCP shortcut path

Status:

- Completed (minimum viable version)

Scope:

- add a true direct-execution fast path for MCP mode

Files:

- [src/routers/tasks.py](/Users/kehongwei/workspace/AICMDEngine/src/routers/tasks.py)
- [src/services/task_mode_selector.py](/Users/kehongwei/workspace/AICMDEngine/src/services/task_mode_selector.py)
- add suggested service:
  [src/services/direct_mcp_executor.py](/Users/kehongwei/workspace/AICMDEngine/src/services/direct_mcp_executor.py)
- [src/models/models.py](/Users/kehongwei/workspace/AICMDEngine/src/models/models.py)

Details:

- when `planningMode=mcp` or `auto` resolves to `mcp`
- and the request is suitable for a single-tool execution
- bypass planner
- directly execute selected MCP tool
- return a direct-result response instead of `plan_ready`
- fallback to planner if direct execution is unsafe or ambiguous

Acceptance:

- simple MCP requests do not generate a plan
- direct MCP result is returned from task entry
- ambiguous requests fall back safely to planner

Follow-up enhancements:

- strengthen parameter extraction and ambiguity detection
- add domain-specific safety rules for direct execution
- support richer direct-execution heuristics in `auto` mode

## 7. Phase 6: Frontend

## Task 6.1: Update task request payload typing

Scope:

- support new task context fields in frontend API usage

Files:

- [ui/src/lib/api.ts](/Users/kehongwei/workspace/AICMDEngine/ui/src/lib/api.ts)
- [ui/src/pages/TaskPlayground.tsx](/Users/kehongwei/workspace/AICMDEngine/ui/src/pages/TaskPlayground.tsx)

Acceptance:

- frontend can send `planningMode` and related options

## Task 6.2: Add mode selector to TaskPlayground

Scope:

- expose mode choice to user

Files:

- [ui/src/pages/TaskPlayground.tsx](/Users/kehongwei/workspace/AICMDEngine/ui/src/pages/TaskPlayground.tsx)

Details:

- add selector:
  - `Auto`
  - `CmdEngine`
  - `MCP Direct`

Acceptance:

- selected mode is visible in UI
- selected mode is sent to backend

## Task 6.3: Add retrieval diagnostics panel

Scope:

- show how the planner chose candidate commands

Files:

- [ui/src/pages/TaskPlayground.tsx](/Users/kehongwei/workspace/AICMDEngine/ui/src/pages/TaskPlayground.tsx)

Details:

- show:
  - resolved mode
  - raw retrieval candidates
  - prompt candidates
  - system-state inclusion
  - planning provider/model
  - embedding provider/model

Acceptance:

- tuning and debugging can be done from UI

## Task 6.4: Add direct MCP result rendering

Status:

- Completed (minimum viable version)

Scope:

- support task responses that return direct MCP execution results instead of plans

Files:

- [ui/src/pages/TaskPlayground.tsx](/Users/kehongwei/workspace/AICMDEngine/ui/src/pages/TaskPlayground.tsx)

Details:

- detect direct MCP response type
- render tool execution output clearly
- distinguish direct execution from plan-based execution in UI

Acceptance:

- user can see when MCP direct mode bypassed planning
- direct tool results render without plan-step UI assumptions

Follow-up enhancements:

- improve direct-result presentation for structured payloads
- add clearer distinctions between planner fallback and true direct execution

## 8. Phase 7: Admin and Operations

## Task 7.1: Add command index admin router

Scope:

- add maintenance endpoints for index lifecycle

Files:

- add [src/routers/command_index.py](/Users/kehongwei/workspace/AICMDEngine/src/routers/command_index.py)
- register router in app startup/router assembly

Details:

- add endpoints:
  - rebuild index
  - refresh MCP tools
  - get index status

Acceptance:

- operators can rebuild and inspect retrieval index

## Task 7.2: Optional CommandSets UI maintenance controls

Scope:

- expose index maintenance operations in frontend if needed

Files:

- [ui/src/pages/CommandSets.tsx](/Users/kehongwei/workspace/AICMDEngine/ui/src/pages/CommandSets.tsx)

Acceptance:

- rebuild/refresh actions can be triggered from UI if enabled

## 9. Testing Tasks

## Task 8.1: Unit tests for retrieval document generation

Scope:

- validate normalized doc generation

Targets:

- `command_document_builder.py`

## Task 8.2: Unit tests for embedding service

Scope:

- validate provider selection and metadata reporting

Targets:

- `embedding_service.py`

## Task 8.3: Unit tests for retriever fusion and supplementation

Scope:

- validate score fusion and helper command supplementation

Targets:

- `command_retriever.py`

## Task 8.4: Integration tests for retrieval-backed planner

Scope:

- validate planner uses candidates and fallback path

Targets:

- `planning_engine.py`
- `tasks` route

## Task 8.5: Manual performance comparison

Scope:

- compare before/after latency and prompt size on representative tasks

Scenarios:

- create member and assign org
- assign role
- create org
- direct MCP-style request

## 10. Suggested Ownership Split

If multiple developers are involved:

- Backend A:
  - config
  - embedding service
  - provider integration
- Backend B:
  - document builder
  - indexer
  - write-sync hooks
- Backend C:
  - retriever
  - planner integration
  - mode selector
- Frontend:
  - task playground mode selector
  - diagnostics UI
  - optional admin controls

## 11. Recommended First Sprint

The highest-value first sprint should cover:

1. Task 1.1
2. Task 1.2
3. Task 1.3
4. Task 2.1
5. Task 2.2
6. Task 2.4
7. Task 3.1
8. Task 4.1

This gets the core retrieval-backed planner running before UI enhancements.

## 12. Done Definition

The implementation is meaningfully usable when:

- commands and MCP tools are indexed in ES
- embeddings are produced through provider-capability selection
- planner consumes retrieved candidate commands
- existing planner path still works as fallback
- UI can at least choose mode and display retrieval diagnostics
