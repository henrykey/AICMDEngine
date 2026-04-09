# AICMDEngine DocIntel Retrieval Integration Plan

## Goal

Use Membership DocIntel as the primary Top-N command retrieval backend for AICMDEngine, while preserving the current local retrieval implementation as fallback.

This plan assumes DocIntel will be adapted to support command corpus behavior.

## Architectural Decision

Primary path:

- AICMDEngine syncs command knowledge into DocIntel
- AICMDEngine calls DocIntel search to retrieve Top-N candidate commands
- AICMDEngine planner consumes those candidates

Fallback path:

- if DocIntel is unavailable
- or returns invalid/insufficient results
- or is disabled by config

then AICMDEngine uses the existing local ES-based `CommandRetriever`.

This keeps current work useful instead of throwing it away.

## Target Retrieval Flow

```text
User goal
-> Task mode resolution
-> Command retrieval
   -> try DocIntel command search
   -> if failed or low-quality, fallback to local CommandRetriever
-> Top-N candidate commands
-> planner or direct MCP path
```

## Responsibilities Split

### Membership DocIntel

Responsible for:

- command corpus storage
- semantic retrieval
- tenant-scoped retrieval filtering
- retrieval scoring
- command corpus metadata return

### AICMDEngine

Responsible for:

- converting commands and MCP tools into command documents
- syncing documents to DocIntel
- deciding retrieval source
- applying command supplement rules
- planner prompt building
- fallback behavior
- diagnostics visibility

## New AICMDEngine Components

### 1. DocIntel client

Add a dedicated service:

- `src/services/docintel_client.py`

Responsibilities:

- upload/update command documents into DocIntel
- search command corpus in DocIntel
- delete command documents from DocIntel
- trigger reindex if needed

### 2. DocIntel command synchronizer

Add:

- `src/services/docintel_command_sync.py`

Responsibilities:

- convert Mongo commands and MCP tools into DocIntel upload payloads
- manage category naming
- manage metadata payload
- batch sync on rebuild

### 3. Hybrid retriever coordinator

Extend or wrap current retrieval path:

- `src/services/command_retriever.py`

New behavior:

1. try DocIntel retrieval first
2. validate result quality
3. fallback to current local ES retrieval if necessary

## Proposed Config

Add config fields:

- `docintel_enabled`
- `docintel_base_url`
- `docintel_timeout_ms`
- `docintel_command_category_prefix`
- `docintel_prefer_remote_retrieval`
- `docintel_remote_min_results`
- `docintel_remote_min_top_score`
- `docintel_sync_enabled`

Fallback controls:

- `command_retrieval_fallback_to_local=true`

## Command Document Mapping

Each command/tool becomes one DocIntel document.

### Title

Recommended:

- `COMMAND: POST /v2/members`
- `MCP: membership.create_member`

### Category

Recommended:

- `cmdengine.command.membership`
- `cmdengine.command.mcp`

### Body

Use canonical English retrieval text.

### Metadata

Required:

- `entity_type=command`
- `command_id`
- `command`
- `source_type`
- `source_name`
- `tenant_id`
- `risk_level`
- `tags`
- `http_method`
- `path`
- `mcp_server`
- `mcp_tool_name`

## Sync Triggers

### Commands

Sync when:

- command created
- command updated
- command deleted
- command set imported
- command set rebuilt

### MCP tools

Sync when:

- MCP refresh runs
- startup refresh runs
- admin requests refresh

## Retrieval Logic

### Remote-first

When enabled, `CommandRetriever` should:

1. build query payload for DocIntel
2. restrict category to command corpus
3. ask for document-level results
4. parse returned metadata into `RetrievedCommandCandidate`
5. run existing supplement logic
6. if remote results are weak, fallback to local ES retriever

### Result quality gates

Fallback to local retriever when any of these happen:

- DocIntel request fails
- timeout
- zero results
- result count below threshold
- metadata missing required command fields
- top result score below threshold

### Supplement logic remains local

AICMDEngine should still keep:

- helper command supplementation
- source-type filtering
- planner candidate trimming
- mode-aware candidate selection

That logic is product-specific and should remain in AICMDEngine.

## Fallback Strategy

Do not remove current local retrieval implementation yet.

Use these phases:

### Phase 1

- DocIntel retrieval optional
- local ES retriever remains default-safe fallback

### Phase 2

- DocIntel retrieval becomes default primary
- local ES fallback remains enabled

### Phase 3

- evaluate whether local ES indexing is still needed for long-term resiliency

## API Contract Assumption

Preferred remote request shape:

```json
{
  "query": "create member and assign roles",
  "searchMode": "TWO_STAGE",
  "topK": 20,
  "searchChunks": false,
  "categories": ["cmdengine.command.membership", "cmdengine.command.mcp"],
  "entityType": "command"
}
```

Preferred response requirement:

```json
{
  "results": [
    {
      "documentId": "cmd_123",
      "title": "COMMAND: POST /v2/members",
      "category": "cmdengine.command.membership",
      "totalScore": 0.91,
      "metadata": {
        "entity_type": "command",
        "command_id": "mongo_command_id",
        "command": "POST /v2/members",
        "source_type": "command",
        "source_name": "membership-v2.4",
        "risk_level": "high"
      }
    }
  ]
}
```

If DocIntel cannot return metadata inline, AICMDEngine can temporarily fetch document detail by `documentId`, but that should be treated as a transition path, not the ideal steady state.

## Implementation Tasks In AICMDEngine

### 1. Add DocIntel client

New file:

- `src/services/docintel_client.py`

Methods:

- `search_commands(...)`
- `upsert_command_document(...)`
- `bulk_upsert_command_documents(...)`
- `delete_command_documents(...)`

### 2. Add DocIntel sync service

New file:

- `src/services/docintel_command_sync.py`

Methods:

- `build_docintel_document_for_command(...)`
- `build_docintel_document_for_mcp_tool(...)`
- `sync_command(...)`
- `sync_commands(...)`
- `sync_mcp_tools(...)`

### 3. Integrate sync into existing routes

Update:

- `src/routers/command_sets.py`
- `src/routers/command_index.py`
- startup initialization in `src/main.py`

### 4. Integrate remote retrieval into current retriever

Update:

- `src/services/command_retriever.py`

Behavior:

- remote-first
- local fallback
- diagnostics include retrieval source

### 5. Extend diagnostics

Update models and UI to show:

- retrieval source: `docintel` or `local_es`
- remote result count
- remote fallback reason

## Frontend Impact

### Task Playground

Display in retrieval diagnostics:

- retrieval backend
- fallback reason
- remote candidate count

### Command Sets / Index Admin

Extend admin view later to show:

- DocIntel sync status
- remote re-sync action
- remote corpus health

Not required for phase 1 if backend logs are sufficient.

## Acceptance Criteria

The integration is complete when:

1. A new command import syncs command documents into DocIntel.
2. A planning request can retrieve candidates from DocIntel.
3. Retrieval diagnostics show whether results came from DocIntel or local ES.
4. If DocIntel fails, planning still succeeds through local fallback.
5. Direct MCP and CmdEngine behavior remain unchanged apart from candidate source.

## Rollout Plan

### Milestone 1

- add DocIntel client
- add command sync payload builder
- manual sync test

### Milestone 2

- integrate remote retrieval into `CommandRetriever`
- add diagnostics and fallback

### Milestone 3

- remote sync triggers on command and MCP updates
- admin controls and operational hardening

## Operational Notes

- Keep local ES retriever for resilience during transition.
- Do not delete current indexing code until DocIntel retrieval proves stable.
- Log remote latency and fallback causes.
- Add circuit-breaker style behavior if DocIntel repeatedly times out.

