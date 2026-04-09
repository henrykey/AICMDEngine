# Membership DocIntel Command Corpus UI Note

This note is for Claude Code working in the `membership` repository.

## Background

The command corpus integration is now working:

- `AICMDEngine` can sync command documents into Membership DocIntel
- command retrieval is now using DocIntel successfully

However, the current DocIntel UI still has a visibility gap:

- command corpus documents are intentionally excluded from ordinary document listing / normal KB search
- so there is currently no clear UI surface to inspect synced command sets or test command retrieval behavior directly

## Requested UI Additions

## 1. Add a dedicated `Command Sets` view in DocIntel UI

Please add a dedicated UI entry for command corpus documents instead of mixing them into normal document views.

Suggested label:

- `Command Sets`
- Chinese label acceptable: `命令集`

### Expected behavior

This view should show command corpus documents grouped in a way that is useful for operational inspection.

Recommended grouping / fields:

- `source_name`
- document count
- tenant id
- category
- source type (`command` / `mcp_tool`)
- last sync / last modified time

### Goal

This view is mainly for:

- verifying that command sets have been synced
- checking how many command documents were created
- detecting stale / duplicate / old command corpus data

It should not behave like ordinary business knowledge-base browsing.

## 2. Add a `Command Corpus` / `Command Sets` option in Search Tester

Please extend the existing Search Tester with a dedicated mode for command retrieval testing.

Suggested mode labels:

- `Command Sets`
- or `Command Corpus`

### Expected behavior

When this mode is selected, the tester should default to command-corpus search semantics rather than normal KB search.

Recommended behavior:

- target command corpus endpoints / filters
- restrict search to `cmdengine.command.*`
- set / expose `entity_type = command`
- allow filtering by:
  - `sourceTypes`
  - `sourceNames`
- expose top-k behavior clearly

### Result display should include

Please display command-specific fields, not just plain chunk text:

- score
- title
- command
- source_name
- source_type
- category
- documentId / externalId
- metadata

This is important because the purpose of this tester is to validate:

- command recall quality
- top-N relevance
- source filtering
- command vs mcp tool retrieval behavior

## Why this matters

Without these two UI additions:

- the command corpus works in the backend
- but operators cannot easily inspect it
- and command retrieval quality is hard to verify interactively

These UI additions are primarily for:

- debugging
- validation
- operations / inspection

not for ordinary end-user KB usage.

## Acceptance Criteria

1. DocIntel UI contains a dedicated `Command Sets` entry / page
2. Synced command corpus documents are visible there without mixing into normal document pages
3. Search Tester has a dedicated command corpus mode
4. Command retrieval results display command-specific metadata clearly
5. It is possible to verify top-N command recall from the UI without using raw API calls
