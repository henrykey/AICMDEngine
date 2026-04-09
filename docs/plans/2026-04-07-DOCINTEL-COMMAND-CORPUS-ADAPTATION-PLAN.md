# DocIntel Command Corpus Adaptation Plan

## Goal

Adapt Membership DocIntel so it can serve as the primary semantic retrieval service for AICMDEngine command discovery.

This plan covers only one responsibility:

- retrieve Top-N relevant commands/tools for a user goal

It does not replace:

- CmdEngine planning
- CmdEngine execution
- Direct MCP shortcut execution

Those remain in AICMDEngine.

## Why This Direction

Membership DocIntel already provides:

- multi-tenant isolation
- Elasticsearch-backed full-text + vector retrieval
- persisted embeddings
- `POST /v2/documents/search`
- configurable retrieval modes such as `SEMANTIC`, `HYBRID`, `TWO_STAGE`

The missing part is not core retrieval infrastructure. The missing part is adaptation so DocIntel can index and search command knowledge cleanly without polluting normal knowledge-base behavior.

## Target Model

Treat command knowledge as a special DocIntel corpus.

Core modeling rules:

- one command = one document
- one command document = one chunk
- command documents use a dedicated category namespace
- command documents are hidden from ordinary KB search and ordinary document listing by default
- command documents carry strong metadata so AICMDEngine can map retrieval hits back to real commands/tools
- command text should use a canonical English representation for stable semantic retrieval

## Command Document Shape

Each command or MCP tool is stored in DocIntel as one document with one chunk.

Recommended canonical text:

```text
Command: POST /v2/members
Source Type: command
Source Name: membership-v2.4
Summary: Create a member
Description: Create a tenant member account and set profile fields.
Tags: membership, member, user, account
Examples: add employee, create user, onboard member
Parameters:
- username: unique login name
- full_name: member full name
- email: email address
- org_id: target organization id
- role_ids: assigned role ids
Risk Level: high
```

Required metadata:

- `entity_type=command`
- `command_id`
- `command`
- `source_type`
  - `command`
  - `mcp_tool`
- `source_name`
- `tenant_id`
- `risk_level`
- `tags`
- `http_method`
- `path`
- `mcp_server`
- `mcp_tool_name`
- `include_in_cmdengine=true`

Recommended optional metadata:

- `command_set_id`
- `examples`
- `parameter_names`
- `parameter_hash`
- `command_version`

## Corpus Isolation Rules

Command documents must not behave like ordinary business documents.

Required isolation strategy:

1. Dedicated category

Recommended values:

- `cmdengine.command`
- `cmdengine.command.membership`
- `cmdengine.command.mcp`

2. Dedicated visibility behavior

Ordinary DocIntel search and document list should not include command documents unless explicitly requested.

3. Dedicated permissions or filtering

At least one of these must be true:

- command categories are excluded from normal UI
- command categories require a dedicated permission
- internal API path explicitly filters command documents in or out

4. Dedicated indexing behavior

Command documents skip normal long-document chunking.

## Required DocIntel Enhancements

### 1. Single-chunk indexing path for command documents

Add a special ingestion branch:

- if category indicates command corpus
- do not run LangChain sentence/document splitting
- create exactly one chunk
- chunk text is the canonical command text

This should preserve command atomicity.

### 2. Search response must expose retrieval metadata

Current `DocumentSearchResponse` is document-oriented. For command retrieval, AICMDEngine needs stable identifiers.

At minimum, search results must include:

- `documentId`
- `title`
- `category`
- `totalScore`
- `metadata`

Required metadata fields in search response:

- `entity_type`
- `command_id`
- `command`
- `source_type`
- `source_name`
- `risk_level`

If returning `metadata` inline is too broad, add a dedicated search response variant for command corpus search.

### 3. Filterable search by category and entity type

`POST /v2/documents/search` should support filters such as:

- `category`
- `categories`
- `entityType`
- `metadataFilters`

This lets AICMDEngine request only command corpus results.

### 4. Optional dedicated command search API

Preferred minimal path:

- enhance existing `POST /v2/documents/search`

Optional cleaner path:

- add `POST /v2/documents/search/commands`

If a dedicated endpoint is added, it should still reuse existing search services internally.

### 5. Default UI exclusion

In docintel-ui:

- ordinary lists should exclude `cmdengine.command.*`
- ordinary KB chat should exclude command corpus by default
- command corpus should only appear in dedicated admin/debug views

### 6. Reindex and delete behavior

Command corpus must support:

- single command reindex
- batch command reindex
- delete by command metadata
- delete by command set / source

## API Recommendation

Two acceptable shapes.

### Option A: Extend existing search request

Add request fields:

- `categories`
- `entityType`
- `metadataFilters`
- `searchChunks`

Example:

```json
{
  "query": "create a new member and assign roles",
  "searchMode": "TWO_STAGE",
  "categories": ["cmdengine.command.membership", "cmdengine.command.mcp"],
  "entityType": "command",
  "topK": 20,
  "searchChunks": false
}
```

### Option B: Add dedicated command retrieval endpoint

Example:

```json
POST /v2/documents/search/commands
{
  "query": "create a new member and assign roles",
  "topK": 20,
  "tenantId": "1",
  "sourceTypes": ["command", "mcp_tool"],
  "sourceNames": ["membership-v2.4", "membership"],
  "searchMode": "TWO_STAGE"
}
```

I recommend Option A first if the response can expose metadata cleanly.

## English Canonicalization

Use English as the canonical retrieval text for command documents.

Reasons:

- API names and parameters are already English-heavy
- technical embeddings are more stable with English API terminology
- it reduces mixed-language retrieval noise

Recommended approach:

- preserve original summary/description in metadata if needed
- generate one canonical English retrieval text for indexing

## Acceptance Criteria

DocIntel adaptation is considered complete when all of the following are true:

1. A command can be ingested as one document and one chunk.
2. Normal document search UI does not accidentally show command corpus.
3. A query like `create member and assign role` returns command-level hits, not fragmented text chunks.
4. Search results include enough metadata to map each hit to a real command/tool.
5. Reindex and delete operations can target command corpus safely.
6. Retrieval remains tenant-scoped.

## Suggested Implementation Order

1. Add command corpus category rules.
2. Add single-chunk ingestion branch.
3. Expose metadata in search response.
4. Add category/entity filters to search.
5. Exclude command corpus from ordinary UI by default.
6. Add reindex/delete helpers for command corpus.

## Claude Code Prompt

Use the prompt below in the Membership repository.

```text
You are working in the Membership repository.

Task:
Adapt DocIntel so it can serve as the semantic retrieval backend for AICMDEngine command discovery.

Scope:
- This is only for Top-N command retrieval.
- Do not redesign CmdEngine.
- Do not change ordinary business document behavior unless required for safe isolation.

Requirements:
1. Treat command knowledge as a special DocIntel corpus.
2. One command = one document = one chunk.
3. Command documents must use a dedicated category namespace such as cmdengine.command.*.
4. Command documents must not appear in ordinary DocIntel search/list views by default.
5. Command indexing must skip the normal LangChain splitting step and store a single canonical chunk.
6. Search results must expose enough metadata for AICMDEngine to map hits back to commands:
   - entity_type
   - command_id
   - command
   - source_type
   - source_name
   - risk_level
7. Existing `/v2/documents/search` should be enhanced if possible; a dedicated command-search endpoint is acceptable if cleaner.
8. Retrieval must stay tenant-scoped.
9. Canonical retrieval text should be English-focused even if original descriptions are mixed-language.

Please do the following:
1. Inspect the current DocIntel OpenAPI, controller, DTO, search service, storage/index pipeline, and UI filtering behavior.
2. Implement the minimum backend changes needed for command corpus ingestion and retrieval.
3. Add request/response model changes needed to filter by category/entity and return metadata.
4. Add any UI filtering or admin affordances necessary so command corpus does not pollute normal user flows.
5. Keep the design incremental and compatible with existing document search behavior.
6. Add or update tests if the repo already has the relevant test scaffolding.

Expected output:
- code changes
- brief design summary
- API examples for command corpus ingestion and retrieval
- any migration/reindex notes
```

