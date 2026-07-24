# K-Graph MCP Server

This directory is the canonical source location for the BasinComparator-specific
knowledge-graph MCP server. It contains the build lifecycle, extraction,
immutable Mongo publication/query path, process entrypoint, and AIPlanner
container packaging.

## Ownership

- Canonical repository: `AICMDEngine`
- Canonical directory: `mcp/servers/k-graph-mcp`
- Product plan:
  `membership/basin-comparator/docs/goals/G29-basin-knowledge-graph-prebuild.md`
- Membership owns authentication, authorization, tenant context, selected
  document scope, and request coordination.
- DocIntel owns normalized source content and evidence locations.
- This server owns asynchronous extraction and BasinComparator graph data.

Membership or BasinComparator may add only a lightweight integration reference
or symlink. They must not contain a copied implementation. The Membership
worktree symlink `AIPlanner -> ../AICMDEngine` is a repository navigation
convention, not a second source location.

## Start

Required environment:

```text
K_GRAPH_MCP_MONGODB_URI
MEMBERSHIP_API_URL
OPENAI_API_KEY
K_GRAPH_MCP_LLM_MODEL
```

Optional environment:

```text
OPENAI_BASE_URL
K_GRAPH_MCP_MAX_WORKERS=2
MCP_TRANSPORT=streamable-http
MCP_HOST=127.0.0.1
MCP_PORT=9013
```

Start from this canonical directory:

```bash
python -m k_graph_mcp
```

The AIPlanner router registers the server as `k-graph-mcp`. The
deployment scope has the same name:

```bash
bash AIPlanner/deploy/deploy-remote-build.sh \
  --scope k-graph-mcp build-src
```

The build/status calls receive a short-lived Membership service credential,
which remains in process memory only. Query does not receive that credential.
Membership issues it through the existing service-account mechanism; G29 adds
no new shared credential or user interaction. Do not put user bearer or
refresh tokens in the service environment.

## G29.0 Frozen Decisions

### User access and selected-document scope

Membership already provides service-account JWTs through
`ServiceAccountTokenProvider` and `JwtService.generateServiceAccountToken`.
The future MCP-to-DocIntel call reuses this mechanism. A user bearer or refresh
token is not persisted in a graph job.

Membership authenticates the BasinComparator user and resolves the documents
selected by the workflow from that user's visible documents. It then passes
the exact document IDs, versions, and normalized-content hashes to the MCP
server. There is no second document authorization layer and no shared scope
signing key. A visible selected document does not need a separate
`includeInKb` flag; it only needs the normalized version content required by
the build.

The scope fingerprint is only a deterministic snapshot/version identity for
idempotency, rebuilds, and stale detection. It is not an authorization token.
The MCP rejects empty/duplicate selections and makes only the scoped DocIntel
request. DocIntel owns correctness and filtering of its returned pages and
chunks; the MCP does not duplicate that validation.

### DocIntel content contract

Repository audit found no existing endpoint that simultaneously provides:

- business-authorized access;
- an exact document-version filter;
- all normalized page text;
- chunk IDs and source locations.

The existing endpoints are deliberately not reused:

- `/v2/documents/{id}/chunks` is administrator-only and does not accept a
  document version.
- `/v2/documents/{id}/versions/{version}/review-context` is a review workflow
  endpoint.
- `/v2/documents/{id}/versions/{version}/source-preview/context` is page-at-a-
  time and does not expose the complete normalized-page/chunk contract.
- `/v2/documents/ask` is retrieval-oriented and does not enumerate the frozen
  normalized source snapshot.

G29.3 therefore adds one read-only internal DocIntel contract:

```text
POST /v2/documents/scoped-content:read
```

It accepts a non-empty `AuthorizedScopeEnvelope`, requires the established
Membership service-account authentication, paginates deterministically, and
returns normalized page units plus matching indexed chunk locations. Every
returned unit repeats tenant, document ID, version, content hash, page number,
and chunk ID when available. DocIntel performs no tenant-wide fallback and
returns a conflict when the requested content hash no longer matches.

The endpoint does not change Stage 1, Stage 2, GraphRAG, GraphMap, parsing,
chunking, embedding, table, formula, or source-preview behavior.

### MongoDB namespace

The phase-1 collections are new and separate from DocIntel
`doc_semantic_relation_*` collections:

```text
basin_kg_builds
basin_kg_versions
basin_kg_nodes
basin_kg_edges
basin_kg_evidence
basin_kg_gaps
```

Build checkpoints and leases are embedded in `basin_kg_builds` until measured
size or contention requires separation. Every query includes `tenant_id` plus
the relevant build or graph version.

### Minimum graph

```text
BASIN --HAS_PART--> SAG|DEPRESSION
```

Entities and relations require one or more validated evidence records. A
co-occurrence is not relationship evidence. Unsupported or ambiguous cases
become explicit semantic gaps and are not published as graph facts.

### Minimum MCP tools

```text
start_basin_graph_build
get_basin_graph_build_status
query_basin_graph
```

No generic graph query, mutation, administration, UI, or cancellation tool is
part of phase 1.

## G29.2 Durable Build Runtime

`BuildCoordinator` persists a request before returning, then dispatches it to a
bounded in-process worker pool. `MongoBuildRepository` stores idempotency,
attempt lineage, checkpoints, retries, cancellation, authorization pauses, and
lease/heartbeat state in `basin_kg_builds`.

- The unique partial Mongo index permits only one reusable
  active/completed build for a tenant and scope fingerprint.
- Worker claims and all subsequent build reads/writes include `tenant_id` and
  `build_id`.
- A heartbeat keeps long work units leased. A stale lease can be reclaimed
  once; a second stale lease fails deterministically.
- Retryable failures use a capped delay with jitter and a retry ceiling.
  Authorization failures pause, while validation/invariant failures fail
  without retry.
- Durable source scope contains only the selected document snapshot and build
  version metadata; it excludes all user bearer/refresh credentials.
- The query backend intentionally remains unavailable until G29.4, and G29.2
  publishes no graph version.

Tests inject fake runners so the lifecycle is verified without DocIntel, an
LLM, or a live Mongo instance.

## G29.3 Scoped Extraction

Membership exposes one read-only service-account endpoint:

```text
POST /v2/documents/scoped-content:read
```

It derives tenant/member from the authenticated service JWT, recomputes the
scope fingerprint, rechecks the exact normalized document hashes, and returns
deterministically paginated pages with matching indexed chunk locations.
Cross-tenant, wrong-version, wrong-page, or wrong-hash results fail instead of
being silently filtered.

Membership passes a fresh tenant service JWT to `start` and `status`. The MCP
keeps it only in `VolatileServiceTokenRegistry`; Mongo build records and
checkpoints never contain it. A process restart or 401/403 pauses the build
until a newly authorized status/start call refreshes that in-memory token.

`ScopedExtractionRunner` then:

- reads only this endpoint, with no search/Ask/GraphRAG fallback;
- batches by indexed chunk (or bounded overlapping page segments);
- requests strict JSON-schema output containing only Basin, Sag/Depression,
  and directed `HAS_PART`;
- validates exact mentions, display names, aliases, bounded quotes, direction,
  and entity/relation types;
- permits one structured-output repair attempt;
- checkpoints validated candidate facts and provenance inside
  `basin_kg_builds`, so compatible restarts do not repeat completed LLM units;
- records no-supported/ambiguous outcomes as gaps rather than false facts.

## G29.4 Immutable Publication and Query

Validated checkpoints are consolidated into tenant-scoped immutable records in:

```text
basin_kg_versions
basin_kg_nodes
basin_kg_edges
basin_kg_evidence
basin_kg_gaps
```

Nodes, edges, evidence, and gaps are first written under a `STAGING` version.
The version metadata becomes `COMPLETED` or `COMPLETED_WITH_GAPS` only after all
writes and contract validation succeed. Query resolution starts from completed
version metadata, so partial multi-collection writes are never visible. A
failed staging attempt does not replace a prior completed version.

`query_basin_graph` supports only exact basin/target name or validated alias
lookup. It returns the connected Basin `HAS_PART` child/parent, bounded
evidence, gaps, graph version, scope fingerprint, and explicit staleness. An
explicit historical version must still match the currently authorized exact
scope. There is no arbitrary traversal language and no Neo4j dependency.

## Contract Tests

From this directory:

```bash
python -m pytest
```

The acceptance corpus in `tests/fixtures/acceptance_corpus.json` is the shared
baseline for later extraction, persistence, security, and end-to-end tests.

G29.1 also freezes a shared Java/Python fingerprint test vector. This prevents
the Membership coordinator and Python MCP server from interpreting the same
selected document snapshot differently.

## Packaging Boundary

- Docker build context:
  `AIPlanner/mcp/servers/k-graph-mcp`
- Image: `aiplanner-k-graph-mcp:latest`
- HTTP port/path: `9013` and `/mcp`
- Compose service and router name: `k-graph-mcp`

Source archives explicitly include this real directory, `pyproject.toml`,
`Dockerfile`, and `k_graph_mcp/__main__.py`. Run staging and commits
from the real AICMDEngine repository so a Membership-side symlink can never
absorb or duplicate the implementation.
