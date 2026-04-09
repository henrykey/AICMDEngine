# CmdEngine Retrieval Optimization Plan

## 1. Background

Current `cmdengine` planning is flexible but inefficient for many real tasks:

- It loads a large portion of tenant commands from MongoDB into the prompt.
- It appends all available MCP tools into the same prompt context.
- It often injects system state eagerly, even when the request does not need it.
- It uses an LLM planning pass even for requests that could be handled by direct MCP execution.

This causes:

- Higher planning latency
- Higher token usage and LLM cost
- Lower planning stability as command/tool inventory grows
- Poor scalability when integrating more third-party MCP servers

The repository already contains:

- command-set and command management in MongoDB
- MCP registry and execution support
- LLM provider/capability management
- a UI playground for task planning

This plan introduces an Elasticsearch-backed command retrieval layer and dual-path execution strategy so that:

- `cmdengine` keeps its value for multi-step business orchestration
- direct MCP execution remains available for simple or explicit tool requests
- planning context is reduced from full inventory to a relevant candidate subset

## 2. Goals

### 2.1 Primary goals

1. Replace full command-set prompt injection with retrieval-based candidate selection.
2. Reuse the existing LLM provider management for embedding generation.
3. Support execution modes:
   - `auto`
   - `cmdengine`
   - `mcp`
4. Add front-end controls and visibility for mode selection and retrieval diagnostics.
5. Keep MongoDB as the source of truth and Elasticsearch as a derived retrieval index.

### 2.2 Non-goals for phase 1

- Replacing the existing execution engine
- Building a full autonomous routing framework for every MCP server
- Adding a general-purpose workflow DSL
- Replacing all planner logic with deterministic templates

## 3. Target Architecture

### 3.1 Request flow

#### Mode: `cmdengine`

`goal` -> `CommandRetriever` -> `Top-N candidate commands/tools` -> optional domain-specific system-state loading -> `PlanningEngine` prompt build -> `LLM planner` -> structured plan -> `ExecutionEngine`

#### Mode: `mcp`

`goal` or explicit tool intent -> `MCP direct router` -> target MCP tool -> result

#### Mode: `auto`

`goal` -> `Task mode selector` -> choose `mcp` or `cmdengine`

### 3.2 Retrieval architecture

All commands and MCP tools are normalized into a common retrieval document and indexed into Elasticsearch.

Retrieval uses:

- keyword search on normalized text fields
- vector similarity search on embeddings
- score fusion and lightweight rule-based supplementation

The planner receives only the final candidate subset, not the full inventory.

## 4. Current-State Problems

## 4.1 Prompt inflation

Today `PlanningEngine`:

- loads up to many commands for a tenant
- converts all MCP tools into command-like objects
- serializes the entire command list into prompt JSON
- appends current system state

This is the main cost center.

## 4.2 Mixed responsibility in planner

The planner currently performs:

- command loading
- MCP tool expansion
- system-state loading
- prompt construction
- JSON repair
- plan post-processing

It lacks a retrieval stage to constrain context before prompt assembly.

## 4.3 No direct mode control in UI/API

Users currently cannot explicitly choose:

- force planner
- force direct MCP
- inspect retrieval candidates

## 4.4 LLM provider reuse is incomplete

The project already has capability-aware provider management, but the planning path still relies on a legacy chat client pattern, and there is no dedicated embedding service using the provider manager.

## 5. Proposed Solution

## 5.1 Standardized retrieval document

Every Mongo command and every MCP tool will be represented as a normalized retrieval document.

### 5.1.1 Required fields

- `doc_id`
- `tenant_id`
- `source_type`
  - `command`
  - `mcp_tool`
- `source_name`
  - command set name or MCP server name
- `command`
- `summary`
- `description`
- `tags`
- `examples`
- `parameter_names`
- `parameter_descriptions`
- `risk_level`
- `retrieval_text`
- `embedding`
- `updated_at`
- `embedding_provider`
- `embedding_model`
- `embedding_dimensions`
- `index_version`

### 5.1.2 Retrieval text format

The retrieval text should be synthesized from all meaningful semantic fields instead of relying only on `description`.

Recommended template:

```text
Command: MCP.membership.create_member
Source Type: mcp_tool
Source Name: membership
Summary: Create a new member
Description: Create a tenant member account and set profile fields
Tags: membership, member, user, account
Examples: add employee, create user, onboard member
Parameter Names: username, full_name, email, org_id, role_ids
Parameter Descriptions: username for login, member full name, email address, organization id, role ids
Risk Level: high
```

## 5.2 Elasticsearch index

### 5.2.1 New index

Suggested index name:

- `cmdengine_commands_v1`

### 5.2.2 Mapping

Suggested mapping:

```json
{
  "mappings": {
    "properties": {
      "doc_id": { "type": "keyword" },
      "tenant_id": { "type": "integer" },
      "source_type": { "type": "keyword" },
      "source_name": { "type": "keyword" },
      "command": { "type": "keyword" },
      "summary": { "type": "text" },
      "description": { "type": "text" },
      "tags": { "type": "keyword" },
      "examples": { "type": "text" },
      "parameter_names": { "type": "keyword" },
      "parameter_descriptions": { "type": "text" },
      "risk_level": { "type": "keyword" },
      "retrieval_text": { "type": "text" },
      "embedding": {
        "type": "dense_vector",
        "dims": 1536,
        "index": true,
        "similarity": "cosine"
      },
      "embedding_provider": { "type": "keyword" },
      "embedding_model": { "type": "keyword" },
      "embedding_dimensions": { "type": "integer" },
      "index_version": { "type": "keyword" },
      "updated_at": { "type": "date" }
    }
  }
}
```

If ES vector indexing constraints exist in the target environment, phase 1 can ship with BM25 plus stored embeddings, then enable vector search in phase 2.

## 5.3 Embedding via existing LLM provider management

This is a hard requirement.

### 5.3.1 Design rule

No code path should hardcode a specific embedding model directly in business logic.

Instead:

- retrieval indexing requests capability `embedding`
- query embedding requests capability `embedding`
- planner requests capability `chat` or `reasoning`

### 5.3.2 New service

Add `EmbeddingService` which:

- asks provider manager for an embedding-capable provider
- validates expected dimensions
- generates embeddings for single or batch texts

Suggested interface:

```python
class EmbeddingService:
    async def embed_text(self, text: str) -> list[float]:
        ...

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...
```

### 5.3.3 Index compatibility rule

Embedding provider and model changes must be versioned.

If embedding model, provider, or dimensions change:

- either reindex the command retrieval index
- or create a new index version and switch alias after rebuild

This avoids incompatible query/index vector spaces.

## 5.4 Retrieval pipeline

### 5.4.1 Candidate selection stages

1. Keyword retrieval from ES
2. Vector retrieval from ES
3. Score fusion
4. Rule-based supplementation
5. Candidate trimming for prompt assembly

### 5.4.2 Initial scoring strategy

Phase 1 can use a simple fusion strategy:

- `final_score = 0.65 * vector_score + 0.35 * keyword_score`

Optional boosts:

- boost write actions if user goal contains create/update/delete verbs
- boost membership-related candidates if goal mentions member/org/role
- boost explicit MCP server mentions

### 5.4.3 Supplementation rules

Retrieval cannot rely on nearest-neighbor only because planning often needs helper commands.

Examples:

- if `create_member` is selected, supplement `list_orgs` and `list_roles`
- if `assign_role` is selected, supplement `list_members` or `get_member`
- if `create_org` is selected, supplement `list_orgs`

Phase 1 should implement minimal supplementation for the membership domain only.

### 5.4.4 Candidate sizes

Recommended defaults:

- retrieval top-k raw: 30 to 50
- prompt candidate size: 12 to 20

## 5.5 Planner integration

### 5.5.1 PlanningEngine change

Current behavior:

- load full tenant commands
- append all MCP tools
- build prompt with full inventory

Target behavior:

- call `CommandRetriever.retrieve()`
- receive candidate commands/tools only
- build prompt from that subset

### 5.5.2 System-state loading optimization

System-state loading should become conditional.

Examples:

- if the retrieved domain is membership, load org/role/member state
- if the retrieved domain is OCR/PDF/KB only, skip membership state

This reduces unnecessary context and remote calls.

## 5.6 Execution mode support

### 5.6.1 Modes

- `auto`
- `cmdengine`
- `mcp`

### 5.6.2 Behavior

#### `cmdengine`

Always run retrieval-backed planning and then execute the generated plan.

#### `mcp`

Bypass planner when possible and execute a directly selected tool or small MCP intent path.

#### `auto`

Use a lightweight routing step:

- explicit MCP/tool/server mention -> prefer direct MCP
- single-step high-confidence request -> prefer direct MCP
- multi-entity or dependency-heavy request -> prefer cmdengine

Phase 1 can support `auto` with simple heuristics rather than an additional LLM classifier.

## 6. Backend Implementation Plan

## 6.1 New files

### 6.1.1 `src/services/command_document_builder.py`

Responsibility:

- convert Mongo command to retrieval document
- convert MCP tool definition to retrieval document
- generate normalized `retrieval_text`

### 6.1.2 `src/services/embedding_service.py`

Responsibility:

- request embedding-capable provider from provider manager
- generate embeddings
- expose embedding provider metadata

### 6.1.3 `src/services/command_indexer.py`

Responsibility:

- create index if needed
- upsert one command
- bulk upsert commands
- upsert MCP tools
- delete stale docs
- rebuild index

### 6.1.4 `src/services/command_retriever.py`

Responsibility:

- query ES with keyword and vector search
- fuse scores
- supplement helper commands
- return candidate list for planner

### 6.1.5 `src/services/task_mode_selector.py`

Responsibility:

- decide `mcp` vs `cmdengine` in `auto` mode
- use simple heuristics in phase 1

## 6.2 Existing files to update

### 6.2.1 `src/core/config.py`

Add settings for:

- ES URL
- ES auth
- command retrieval index name
- retrieval top-k
- prompt top-k
- optional command index alias

### 6.2.2 `src/models/models.py`

Extend `TaskRequestContext` with optional fields:

- `planningMode`
- `candidateLimit`
- `includeSystemState`
- `preferredSources`
- `preferredMcpServers`

Keep backward compatibility for existing callers.

### 6.2.3 `src/routers/command_sets.py`

After command creation/import:

- asynchronously index created commands into ES

For bulk import:

- perform bulk indexing
- return indexing summary

### 6.2.4 `src/services/planning_engine.py`

Refactor:

- replace full command loading for prompt construction with `CommandRetriever`
- keep Mongo full-load path only as fallback
- make system-state loading conditional
- optionally log retrieval diagnostics

### 6.2.5 App startup path

At application startup:

- initialize ES-backed command indexer/retriever services
- optionally refresh MCP tool snapshots into the index

## 6.3 API additions

### 6.3.1 Task API

Update `POST /tasks` request schema via `context` extension.

### 6.3.2 Admin/maintenance endpoints

Suggested endpoints:

- `POST /v1/command-index/rebuild`
- `POST /v1/command-index/refresh-mcp`
- `GET /v1/command-index/status`

Phase 1 can keep these as internal/admin endpoints only.

### 6.3.3 Retrieval diagnostics

Optional endpoint:

- `POST /v1/tasks/retrieve-preview`

This helps UI and debugging without executing planning.

## 7. Frontend Implementation Plan

## 7.1 Task Playground changes

Update [ui/src/pages/TaskPlayground.tsx](/Users/kehongwei/workspace/AICMDEngine/ui/src/pages/TaskPlayground.tsx) to add:

- execution mode selector
  - `Auto`
  - `CmdEngine`
  - `MCP Direct`
- optional retrieval preview toggle
- optional system-state inclusion toggle for debugging

The page should send these options through `context`.

## 7.2 Retrieval diagnostics UI

Add a panel showing:

- selected mode
- resolved mode in `auto`
- retrieved candidates
- final candidates passed into prompt
- whether system state was loaded
- planning provider/model
- embedding provider/model

This is critical for tuning and validation.

## 7.3 Command set management UI

Current command set UI should eventually support:

- manual reindex trigger for a command set
- MCP tool refresh trigger
- index health/status display

This can be phase 2 if necessary.

## 8. Phased Delivery

## 8.1 Phase 1: Retrieval-backed planner

Deliverables:

- ES config wired from `.env`
- retrieval document builder
- embedding service using provider manager
- command indexer
- command retriever
- planner uses candidate subset instead of full inventory
- logs include retrieval diagnostics

No front-end dependency required for this phase.

Success criteria:

- prompt command count reduced significantly
- planning latency reduced
- plan quality does not regress on baseline membership tasks

## 8.2 Phase 2: UI controls and diagnostics

Deliverables:

- mode selector in playground
- retrieval preview / candidate display
- planning and embedding model visibility

Success criteria:

- team can compare `auto`, `cmdengine`, and `mcp`
- candidate quality is inspectable without backend log digging

## 8.3 Phase 3: Direct MCP routing and admin controls

Deliverables:

- lightweight `auto` mode selector
- admin endpoints for rebuild/refresh/status
- optional command-set-level reindex in UI

Success criteria:

- simple requests bypass planner
- index maintenance becomes operationally manageable

## 9. Metrics and Acceptance Criteria

## 9.1 Core metrics

- planning request total latency
- retrieval latency
- embedding latency
- ES query latency
- prompt token size
- candidate count before prompt
- plan success rate
- clarification rate
- execution success rate
- mode distribution: `auto` / `cmdengine` / `mcp`

## 9.2 Baseline comparisons

Measure before and after on representative tasks:

- create member and assign org
- create org and role
- role assignment
- knowledge query task
- single direct MCP tool task

Expected outcomes:

- lower planning latency
- lower prompt size
- lower token usage
- no significant regression in plan correctness

## 10. Risks

## 10.1 Retrieval misses helper commands

Mitigation:

- add domain-specific supplementation rules
- keep Mongo full-load fallback under feature flag initially

## 10.2 MCP tool index drift

Mitigation:

- startup refresh
- manual refresh endpoint
- later add periodic sync if needed

## 10.3 Embedding provider changes break compatibility

Mitigation:

- store provider/model/dimensions in indexed docs
- version index and reindex when embedding configuration changes

## 10.4 ES unavailability

Mitigation:

- fallback to current Mongo full-load planner path under degraded mode
- log degraded mode explicitly

## 11. Recommended Implementation Order

1. Add ES and retrieval config to backend settings.
2. Implement `EmbeddingService` using existing provider capability management.
3. Implement `CommandDocumentBuilder`.
4. Implement `CommandIndexer`.
5. Wire indexing into command creation/import flows.
6. Add MCP snapshot indexing.
7. Implement `CommandRetriever`.
8. Refactor `PlanningEngine` to use retrieval candidates.
9. Add retrieval diagnostics logs.
10. Update `TaskPlayground` with mode selector and diagnostics panel.
11. Add admin endpoints for rebuild and MCP refresh.
12. Add lightweight `auto` routing.

## 12. Final Recommendation

The first production objective should not be full dual-mode intelligence. It should be a narrower, safer improvement:

- keep current cmdengine behavior as fallback
- insert ES retrieval in front of planning
- reduce prompt scope from full inventory to candidate subset
- reuse existing provider management for embeddings
- expose enough front-end diagnostics to tune and validate

This gives immediate performance and cost improvements without removing the flexibility that made `cmdengine` valuable in the first place.
