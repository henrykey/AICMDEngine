# Membership DocIntel Command Corpus Review

## Scope

Review the Membership-side changes intended to adapt DocIntel for AICMDEngine command retrieval.

Review focus:

- command corpus isolation
- one-command-one-document retrieval behavior
- search API usability for AICMDEngine
- integration completeness for command sync and delete

Reviewed area:

- `membership-docs` backend
- `docintel-ui` filtering behavior

## Overall Assessment

The current implementation is directionally correct, but not yet complete enough for AICMDEngine integration.

What is already in place:

- dedicated command corpus constants
- dedicated `POST /v2/documents/search/commands`
- search response includes `metadata`
- command corpus documents use single-chunk indexing path
- normal docintel UI excludes command corpus in key places

What is still missing or incorrect:

- there is no command corpus ingest/sync API for AICMDEngine to actually write command documents
- normal semantic/hybrid search does not fully exclude command corpus
- command search filtering by multiple `sourceTypes` / `sourceNames` is not implemented correctly

## Findings

### 1. Missing command corpus ingest/sync API

Severity:

- High

Problem:

The current changes add:

- `POST /v2/documents/search/commands`
- `DELETE /v2/documents/command-corpus`

But there is still no dedicated backend path for AICMDEngine to sync command documents into DocIntel as canonical single-chunk documents with metadata.

Evidence:

- [DocumentController.java](/Users/kehongwei/workspace/membership/membership-docs/src/main/java/com/joinkey/membership/docs/controller/DocumentController.java#L242)
- [DocumentController.java](/Users/kehongwei/workspace/membership/membership-docs/src/main/java/com/joinkey/membership/docs/controller/DocumentController.java#L278)
- existing upload path is still file-oriented:
  [DocumentController.java](/Users/kehongwei/workspace/membership/membership-docs/src/main/java/com/joinkey/membership/docs/controller/DocumentController.java#L86)
- the upload controller builds `DocumentUploadRequest` without `metadata`:
  [DocumentController.java](/Users/kehongwei/workspace/membership/membership-docs/src/main/java/com/joinkey/membership/docs/controller/DocumentController.java#L111)

Impact:

- AICMDEngine cannot actually populate the command corpus
- command retrieval cannot be used end-to-end
- the current adaptation only supports search/delete semantics, not ingestion

Recommendation:

Add one dedicated command corpus sync API, for example:

- `POST /v2/documents/commands/sync/batch`

Recommended request shape:

```json
{
  "documents": [
    {
      "externalId": "command:1:abc123",
      "title": "COMMAND: POST /v2/members",
      "category": "cmdengine.command.membership",
      "content": "Command: POST /v2/members\nSummary: Create a member\n...",
      "classification": 3,
      "includeInKb": false,
      "metadata": {
        "entity_type": "command",
        "command_id": "abc123",
        "command": "POST /v2/members",
        "source_type": "command",
        "source_name": "membership-v2.4",
        "risk_level": "high"
      }
    }
  ]
}
```

Requirements for this API:

- idempotent upsert by `externalId`
- no file upload required
- directly creates metadata + stored text + single chunk
- triggers full-text and vector indexing

### 2. Command corpus is not fully excluded from normal semantic/hybrid search

Severity:

- High

Problem:

The current implementation excludes command corpus in keyword search using `mustNot prefix(category.keyword, "cmdengine.command")`, but semantic search does not apply an equivalent exclusion.

Evidence:

- exclusion decision is computed here:
  [DocumentSearchService.java](/Users/kehongwei/workspace/membership/membership-docs/src/main/java/com/joinkey/membership/docs/service/DocumentSearchService.java#L190)
- semantic path only passes positive filters into `vectorStore.search(...)`:
  [DocumentSearchService.java](/Users/kehongwei/workspace/membership/membership-docs/src/main/java/com/joinkey/membership/docs/service/DocumentSearchService.java#L220)
  [DocumentSearchService.java](/Users/kehongwei/workspace/membership/membership-docs/src/main/java/com/joinkey/membership/docs/service/DocumentSearchService.java#L251)
- `resolveCategories()` explicitly returns `null` in the default exclusion path:
  [DocumentSearchService.java](/Users/kehongwei/workspace/membership/membership-docs/src/main/java/com/joinkey/membership/docs/service/DocumentSearchService.java#L1179)
- `EsVectorStore` has no negative category exclusion logic:
  [EsVectorStore.java](/Users/kehongwei/workspace/membership/membership-docs/src/main/java/com/joinkey/membership/docs/service/EsVectorStore.java#L116)

Impact:

- normal DocIntel semantic search can still retrieve command corpus documents
- ordinary KB retrieval behavior is polluted
- hybrid/TWO_STAGE retrieval may mix command corpus into normal document results

Recommendation:

Add explicit negative exclusion support to the vector search path.

Two acceptable fixes:

1. Add `excludeCategoryPrefix` support into the vector search API and ES post-filter.
2. Add a dedicated boolean such as `excludeCommandCorpus` to the vector-side filter builder and apply:

```text
must_not prefix(category.keyword, "cmdengine.command")
```

This exclusion must be applied consistently in:

- `SEMANTIC`
- `HYBRID`
- `TWO_STAGE`

Expected behavior:

- normal search excludes command corpus by default
- only explicit command corpus queries opt in to those categories

### 3. Multi-value source filtering does not work in command search

Severity:

- Medium

Problem:

`CommandCorpusSearchRequest` only converts `sourceTypes` and `sourceNames` into metadata filters when the list size is exactly `1`.

Evidence:

- [CommandCorpusSearchRequest.java](/Users/kehongwei/workspace/membership/membership-docs/src/main/java/com/joinkey/membership/docs/model/dto/CommandCorpusSearchRequest.java#L96)

Current behavior:

- `sourceTypes=["command"]` works
- `sourceTypes=["command","mcp_tool"]` is silently ignored
- `sourceNames=["membership-v2.4","membership"]` is silently ignored

Impact:

- AICMDEngine cannot properly constrain retrieval across multiple allowed sources
- command search becomes broader than intended
- Top-N quality is worse

Recommendation:

Support list-based metadata filtering explicitly.

Two acceptable options:

1. Extend `DocumentSearchRequest` and ES query builder with:
   - `metadataTermsFilters: Map<String, List<String>>`
2. In the dedicated `/search/commands` path, build proper OR filters for:
   - `doc_metadata.source_type.keyword in (...)`
   - `doc_metadata.source_name.keyword in (...)`

Expected request support:

```json
{
  "query": "create member and assign roles",
  "sourceTypes": ["command", "mcp_tool"],
  "sourceNames": ["membership-v2.4", "membership"]
}
```

## Secondary Suggestions

These are not blockers, but should be considered while closing the gaps.

### 4. Align delete API with AICMDEngine usage

Current delete API:

- `DELETE /v2/documents/command-corpus?sourceName=...`

This is useful for source-level rebuilds, but AICMDEngine may also need precise delete-by-external-id.

Recommendation:

Add one of:

- `POST /v2/documents/commands/delete`
- or `DELETE /v2/documents/command-corpus/by-ids`

with payload:

```json
{
  "externalIds": ["command:1:abc123", "mcp:0:membership:list_members"]
}
```

### 5. Return metadata in OpenAPI contract

The runtime response includes `metadata`, but make sure the published OpenAPI is updated accordingly so generated clients remain correct.

### 6. Add dedicated tests

Recommended tests:

- command corpus document indexing creates exactly one chunk
- normal search excludes command corpus by default
- command search includes command corpus explicitly
- multi-source filters work for `sourceTypes` and `sourceNames`
- command search returns metadata fields needed by AICMDEngine

## Recommended Next Patch Set

Order:

1. Add command corpus sync/upsert API
2. Add precise delete-by-external-id or batch delete API
3. Fix vector-side exclusion of command corpus for normal search
4. Fix multi-value metadata filtering for command search
5. Update OpenAPI and tests

## Suggested Handoff To Claude Code

Use the summary below.

```text
The Membership DocIntel command corpus adaptation is partially complete but not yet integration-ready for AICMDEngine.

Please address these gaps:

1. Add a command corpus ingest/sync API.
   - Current implementation supports search and delete, but not write/upsert.
   - AICMDEngine needs a JSON-based batch sync endpoint, not file upload.
   - Required fields: externalId, title, category, content, classification, includeInKb, metadata.

2. Fully exclude command corpus from normal semantic/hybrid search.
   - Current keyword search excludes cmdengine.command.* by default.
   - Semantic/vector search does not.
   - This must be fixed for SEMANTIC, HYBRID, and TWO_STAGE modes.

3. Fix multi-value source filtering in /v2/documents/search/commands.
   - sourceTypes/sourceNames currently only work when exactly one value is provided.
   - Support multiple values properly using OR/terms filters.

4. Prefer adding a precise delete-by-external-id API in addition to delete-by-sourceName.

5. Update OpenAPI and add targeted tests for:
   - one command = one chunk
   - normal search exclusion
   - command search inclusion
   - multi-source filtering
   - metadata in command search results

Relevant reviewed files:
- membership-docs/src/main/java/com/joinkey/membership/docs/controller/DocumentController.java
- membership-docs/src/main/java/com/joinkey/membership/docs/model/dto/CommandCorpusSearchRequest.java
- membership-docs/src/main/java/com/joinkey/membership/docs/model/dto/DocumentSearchRequest.java
- membership-docs/src/main/java/com/joinkey/membership/docs/model/dto/DocumentSearchResponse.java
- membership-docs/src/main/java/com/joinkey/membership/docs/service/DocumentSearchService.java
- membership-docs/src/main/java/com/joinkey/membership/docs/service/DocumentStorageService.java
- membership-docs/src/main/java/com/joinkey/membership/docs/service/EsVectorStore.java
```

## Verification Performed

Module compile passed:

```text
./gradlew :membership-docs:compileJava
```

This review is therefore about behavioral and integration completeness, not Java compile breakage.

