# Membership DocIntel `500` Sync Fix Note

This note is for Claude Code working in the `membership` repository.

## Current Symptom

`AICMDEngine` now reaches the Membership DocIntel command sync endpoint successfully:

- `POST /v2/documents/commands/sync/batch`

Authentication is already working again after token refresh fixes. The current failure is:

- Membership returns `500`
- No command corpus documents are persisted into `docs.documents`

`AICMDEngine` log example:

```text
Failed to sync imported commands for set ... to DocIntel:
Server error '500' for url 'http://host.docker.internal:8080/v2/documents/commands/sync/batch'
```

## High-Probability Root Cause

The most likely failure is a Mongo unique-index conflict in Membership Docs.

### Relevant code

- Command corpus sync path:
  - `/Users/kehongwei/workspace/membership/membership-docs/src/main/java/com/joinkey/membership/docs/service/DocumentStorageService.java`
  - method: `syncCommandCorpusDocument(...)`

- `DocumentMetadata` unique compound index:
  - `/Users/kehongwei/workspace/membership/membership-docs/src/main/java/com/joinkey/membership/docs/model/entity/DocumentMetadata.java`

### Why this is likely

`DocumentMetadata` defines this unique index:

```java
@CompoundIndex(name = "tenant_user_md5_unique", def = "{'tenant_id': 1, 'uploader_id': 1, 'md5_hash': 1}", unique = true)
```

But the command corpus write path appears to create `DocumentMetadata` without setting `md5Hash`.

So multiple synced command documents may end up with the same effective uniqueness tuple:

- same `tenant_id`
- same `uploader_id`
- same `md5_hash = null`

This can trigger duplicate key errors during batch sync and surface as HTTP `500`.

## What To Check First

Please verify Membership logs / stack trace for:

- `DuplicateKeyException`
- Mongo duplicate key on `tenant_user_md5_unique`
- duplicate key involving `md5_hash`

If confirmed, this is the fix path.

## Recommended Fix

For command corpus documents, assign a stable non-null `md5Hash` before saving `DocumentMetadata`.

### Good choices

Use one of these as the hash source:

1. `externalId`
2. `content`
3. `externalId + content`

Recommendation:

- Generate a deterministic hash from `externalId + "\n" + content`
- Store it in `docMetadata.setMd5Hash(...)`

This keeps:

- idempotent upsert behavior
- uniqueness safety
- compatibility with the existing unique index

## Suggested Implementation Point

In:

- `/Users/kehongwei/workspace/membership/membership-docs/src/main/java/com/joinkey/membership/docs/service/DocumentStorageService.java`

Inside:

- `syncCommandCorpusDocument(...)`

Before `mongoTemplate.save(docMetadata, "documents");`

Add logic similar to:

```java
String md5Hash = ...; // deterministic hash of externalId + content
...
.md5Hash(md5Hash)
```

## Alternative Fixes

These are less preferred:

1. Special-case command corpus to bypass the `tenant_user_md5_unique` constraint
2. Use a different uploader id per command document

Both are weaker than simply assigning a stable `md5Hash`.

## Acceptance Criteria

After the fix:

1. `POST /v2/documents/commands/sync/batch` returns `200`
2. `docs.documents` increases as commands are synced
3. Re-sync of the same command set remains idempotent
4. No duplicate key error appears in Membership logs

## Nice-to-Have

Please also improve Membership error logging for this endpoint:

- log the root exception class
- log whether the failure happened during:
  - Mongo save
  - full-text indexing
  - vector indexing

That will make the next integration round much faster to debug.
