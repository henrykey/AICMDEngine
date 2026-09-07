# Single-table query enhancement, contract 1

`extract_page_tables` accepts optional `query_enhancement`. Omit it to retain the
existing extraction behavior and response. The new branch operates on exactly one
supplied table; it does not OCR a page or discover adjacent objects. JSON output is
required. The shared grid parser uses pandas and lxml from this service's requirements.txt.

## Request

Synthetic Python example (use the existing registered MCP tool):

```python
import hashlib
html = '<table><tr><th>Material</th><th>Limit</th></tr><tr><td>Z</td><td>9</td></tr></table>'
identity = dict(tenant_id='tenant', doc_id='doc', version=1,
                table_id='table', table_pk='pk')
arguments = {
    'description_language': 'zh',
    'query_enhancement': {
        'request_id': 'request-1',
        'target': identity,
        'table': {**identity, 'render_html': html},
        'source_html_sha256': hashlib.sha256(html.encode('utf-8')).hexdigest(),
        'max_model_calls': 0,
    },
}
```

The target must match all five identity fields in `table`. If the table has
`page_no` or `override_revision`, the target must also match these fields. The
caller owns authorization, current-version/revision checks, and table selection;
MCP equality checks cannot establish tenant authorization or freshness in storage.
The hash covers exact UTF-8 `render_html` bytes, without normalization.

Optional fields inside `query_enhancement`:

| Field | Meaning |
| --- | --- |
| `annotations` | Explicitly attached `{text, kind}` notes, units or titles; references `a0`, `a1`, etc. No implicit page context. |
| `max_model_calls` | 0 (default), 1 or 2 logical semantic calls. This is a cap, not a requirement. Calls occur only when `query_strategy` is `semantic_review` or `model_required`; deterministic complete projections therefore remain zero-call. |
| `query_strategy` | Optional explicit model policy: `semantic_review` or `model_required` enables bounded semantic calls; omitted means deterministic source projection only. |
| `object_image_path` | Explicit local crop of this object, sent only in an enabled semantic call. Never inferred from page/file arguments. |
| `object_image_data` | Explicit PNG/JPEG data URI or base64 for one table crop from another service. The bytes must decode through the existing image library, match the declared MIME, and remain within byte/pixel limits. The validated file is temporary and deleted after all retries; it never grants arbitrary local-file access. |
| `source_assertions` | Independent observations `{source: 'r2c0', text: 'expected source text'}`; exact mismatch blocks the projection. Positions resolve to merged origins. This is supplied evidence, not automatic image verification. |
| `content_conflicts` | Caller-reported source conflict; blocks the whole projection. |
| `requires_previous_context` | Explicit missing continuation dependency; blocks the whole projection. |

The supplied table, including render HTML, Markdown, prior rows, and existing
metadata, is returned unchanged. Existing `file_*`, OCR and page context inputs are
not used by this branch. Supply only the target table and explicit annotations.

Temporary crops created from `object_image_data` are owned by this request and
removed on provider initialization failure, call failure, retry exhaustion and
normal return. Caller-supplied `object_image_path` files are never deleted.
Provider initialization exceptions return `model_initialization_failed` with
`model_calls: 0`, without exposing configuration values or exception text.

The PNG/JPEG restriction applies to the new `object_image_data` input only.
Existing single-page image extensions remain PNG/JPEG/WebP/BMP/TIF/TIFF.
The shared VLM transport sends PNG/JPEG/WebP bytes unchanged with their matching
MIME; BMP/TIFF are converted to PNG in memory using the existing PyMuPDF
dependency. Conversion neither overwrites the source nor creates temporary files.

## Response and quality

```json
{
  "table": {"render_html": "exact original input and other original fields"},
  "query_enhancement": {
    "contract_version": "1",
    "binding": {"tenant_id": "tenant", "doc_id": "doc", "version": 1,
                "table_id": "table", "table_pk": "pk", "request_id": "request-1",
                "source_html_sha256": "computed hash"},
    "lookup_status": "complete",
    "lookup_sections": [{"key": "section_1", "columns": ["c0", "c1"],
                         "rows": [["Z", "9"]], "fields": [], "records": []}],
    "quality": {"content_consistency": "source_bound_not_image_verified",
                "structure_coverage": "complete", "query_projection": "complete"},
    "unresolved": [], "degraded": false, "manualReviewRequired": false,
    "model_calls": 0
  }
}
```

The example abbreviates fields/records. Each field contains an ordered
`header_path` and `units`, with source bindings at each level. Each record contains
`values`, `conditions` and `groups`. A bound value contains `raw_text`, `value`,
`kind`, `source`, `position`, `start`, `end`, `binding_id` and `status`.

- `source` names the original cell (`r0c0`, zero-based original HTML coordinates).
  `position` may name an inherited merged position. `merged_fill` is not a new source.
- Text spans use Python Unicode character offsets, end exclusive, into the returned
  source cell's cleaned text. The original HTML remains byte-exact in `table`.
  Token-internal slices are rejected. Empty cells have `value: null`.
- Leading-zero identifiers remain strings. Numbers retain original text and a
  decimal string; percentages retain the percent magnitude, not a fraction.
  Mixed fractions retain whole/numerator/denominator without float conversion.
- Explicit comparisons provide lower/upper bounds and inclusion flags. ASCII,
  fullwidth comparisons and a limited set of LaTeX comparison wrappers are supported.
`A~B`, arbitrary expressions, interpolation and cross-table rules are not executed. A tilde range such as `150~475` remains unresolved unless the caller supplies explicit header/footnote evidence and a model proposal binds that evidence; the query layer does not infer open/closed endpoints.
- Every non-whitespace source character must be bound or explicitly unresolved.
  Header paths, titles, units, groups and conditions all participate in coverage.
  Matching existing source-cell bbox/bbox_space metadata is preserved, never invented.
- `complete` describes source-bound projection checks, **not** proof against an
  original image or proof that model semantic associations are correct. Content
  consistency remains `source_bound_not_image_verified` unless a conflict is found.
  No confidence or model self-reported complete flag establishes completion.

Incomplete/invalid output has `lookup_status: unavailable`, empty `lookup_sections`,
review/degraded flags, and source-scoped `unresolved` entries. Validated partial
candidates may appear in `candidate_sections`; they are diagnostic only and must
not be published or queried as a complete table. Old table data is never cleared.
The three quality dimensions are returned after source parsing; malformed requests
can return early with only the reason and unavailable status.

Deterministic blockers (`content_conflicts`, mismatching `source_assertions`, and
`requires_previous_context`) are checked before provider creation or invocation.
They return `model_calls: 0`, preserve the supplied table, and report the blocking
reason. A supplied image can support a provider review but cannot upgrade
`source_bound_not_image_verified` to image-verified; provider/mock reports are
diagnostic evidence only.

`query_strategy` is an explicit enum. Unknown values and a nonzero strategy with
`max_model_calls: 0` return `lookup_status: unavailable` with a configuration
reason. `model_required` cannot be satisfied by the deterministic projection: at
least one successful model proposal is required.

Important reasons: `unknown_table_identity`, `revision_or_page_mismatch`,
`content_hash_mismatch`, `single_table_required`, `table_structure_unavailable`,
`ambiguous_header`, `invalid_source_reference`, `unmapped_source_cells`,
`content_conflict`, `missing_previous_context`, `unsupported_condition`,
`model_response_truncated`, `input_budget_exceeded`, `model_call_failed`,
`model_initialization_failed`.

## Semantic conversion and reference queries

The deterministic path accepts leading all-`th` header rows and rectangular body
positions, retaining rowspan origins and each header level. Ambiguous headers,
spanning body sections and recognizable conditional prose require interpretation.
It does not guess headers in all-`td` HTML.

`DynamicVLMClient.explain_table_query` reuses the text/image transport, language
instruction and token/timeout controls. Models propose only source references and
exact spans, never replacement values. Validation runs before a proposal replaces
any candidate. A second logical call receives unresolved reasons and the same
bounded table; no automatic expansion to another page or object occurs. This is a
whole-target retry with feedback, not independent per-region calls. Input limits:
200,000 HTML characters, 2,000 cells/annotations, 100,000 source text characters,
spans at most 100, timeout at most 60 seconds per logical call. A conservative
character-based context estimate rejects oversized prompts without dropping cells.
Transport/SDK fallback behavior remains that of the existing VLM client, so logical
call counts are not a count of every HTTP transport attempt.

`table_query.select_records` is an offline reference filter over a complete
projection. It accepts one section key and exact field values (or numeric probes
for interval fields). Textual applicability is never evaluated: all condition
`binding_id`s must be explicitly established by the caller before a record can
match. This helper is not a new MCP tool, database or general query engine.

## Membership handoff

Current consumers must **not** blindly copy nested sections into storage.
`Stage1TableNormalizer` currently treats any nonempty section list as complete and
only retains key/title/columns/rows/shared_rules; it cannot preserve the new
conditions, source spans, bounds or partial scope. Integration must first add a
quality gate and preserve these semantics in the existing table lifecycle.

| MCP field | Membership responsibility |
| --- | --- |
| `binding` | Recheck tenant/doc/version/table_pk/table_id and revision against current state. |
| `table.render_html` | Existing authoritative display; enhancement does not write it. |
| `query_enhancement.lookup_sections` | Same parent table_pk; section metadata maps to lookup_sections and rows to doc_table_rows only after the new gate. |
| `fields.header_path`, `units` | Preserve dimensions and units; flattened names alone are insufficient. |
| `records.conditions/groups`, interval values | Retain applicability and bounds in the query contract; do not silently flatten into unconditional rows. |
| `source_cells`, span bindings | Preserve source lineage; attach existing page/object metadata. |
| `unresolved`, `candidate_sections` | Review diagnostics, never promote partial candidates to whole-table success. |

The previously documented Membership local chat/model repair chain was a historical
snapshot and is not a verified current call chain. The separate
`enhance_object_semantics` MCP endpoint now exists; the consumer must verify its
current routing and deployment. Do not recreate a local model path from the old
snapshot. No Membership source, persistence, index or UI changes are included.

## Offline verification

```sh
.venv/bin/python -m pytest -q --no-cov tests/test_pdf2md_enhanced_table_query.py tests/test_pdf2md_enhanced_single_page_tools.py tests/test_pdf2md_enhanced_object_recovery.py tests/test_pdf2md_enhanced_upload_semantics.py
```

Fixtures in Git are synthetic. Private samples, human bindings and their reports
remain under `/tmp/docintel-complex-table-samples-20260906/`. Real provider calls,
model-assisted image consistency, runtime deployment and Membership integration
require separate acceptance. Do not treat these offline tests as product rollout.

### Diagnostic attempt history

`query_enhancement.diagnostics` is an additive v1 field containing ordered, content-free events. Each event has `stage` and `reasons` (reason codes only); model attempts additionally have a one-based `attempt`. Stages are `source_validation`, `deterministic_projection`, `strategy_validation`, `model_initialization`, `model_projection`, and `condition_validation`. A successful retry retains the earlier failure event even though final `unresolved` is empty. `model_calls` remains the actual logical call count. Diagnostic history neither relaxes source validation nor establishes image verification. No prompts, source content, provider exceptions, or provider configuration are included.

## Generic quality additions (2026-09-07)

The existing source-coordinate grid parser remains authoritative. It now preserves
empty rows, plus per-cell `raw_html` and `raw_text` before whitespace cleaning.
Existing `text` and query span offsets retain their v1 cleaned-text meaning; raw
fields preserve source strings without silently changing consumers' offsets.
Explicit leading `thead` rows also work when their cells use `td`. All-`td` headers
without structural evidence still require a source-bound semantic proposal.
Caption text participates in source coverage through `captionN` references;
footers require review. Unparsed source cells and rowspans beyond observed rows
block projection instead of manufacturing rows. Body merges, conditional prose,
and ragged rows have distinct reasons: `body_spanning_cells`,
`conditional_source_requires_review`, `ragged_table_rows`. Additional reasons are
`footer_requires_review` and `embedded_image_requires_asset`.

`requires_previous_context` now adds `dependencies` with the existing binding,
`required_evidence=caller_supplied_continuation_context`, and `auto_fetch=false`.
No inferred previous-page number or cross-page model call is introduced.
Tilde labels remain available as source text and diagnostic candidates; v1 still
blocks executable projection without endpoint evidence. This change does not
publish partially queryable sections or enable interval guessing.

The production grid parser now uses pandas/lxml in the existing
`_html_table_to_grid` implementation. It suppresses header promotion and footer
reordering, replaces each DOM cell with a unique token, expands those tokens, and
then restores original cell strings. Values never pass through pandas inference.
Each merged position is checked against its token origin; duplicate text is not
identity evidence. Standard omitted td/tr closing tags are parsed by lxml; raw
render HTML remains exact. `raw_html` uses the exact cell interior where balanced
source tags are available; otherwise it is the lxml-normalized interior, with
raw_text preserved. No synthetic rowspan overflow is eligible for query publication.

Runtime dependencies are `pandas>=2.2.3,<3` and `lxml==6.1.1`; both Dockerfiles
install the same requirements. Independent comparison still uses pandas 2.2.3.
Input expansion is checked before pandas allocation (200,000 logical positions),
in addition to HTML/cell/span limits. Text outside cells/captions is included as
`noteN` source evidence, and rowspan=0 is resolved within its declared row group.
Both isolated Docker COPY tests now execute the actual parser, not merely import
the semantic module. No image was built.

`select_candidate_labels` is an offline diagnostic helper for exact string labels
such as `150~475`. It returns `status=diagnostic_only`, requires all bound conditions
to be explicitly established, and does not perform range membership or make a
candidate publishable. `select_records` still rejects unavailable projections.

Reproducible source-only audit:
`.venv/bin/python scripts/audit_pdf2md_content_quality.py --input SNAPSHOT --output /tmp/quality.json --pandas-reference /tmp/pandas-result.json --query-spec /tmp/queries.json`.
The output contains table ordinals, counts and reasons, not source text. Coordinate
self-consistency, equality with pandas, manual-header queries, and automatic
semantic projection are distinct evidence levels.

## Calculation-sheet type guard

`table_kind=calculation_sheet` returns `calculation_sheet_not_data_table` before grid
parsing or provider creation. Other explicit non-data types return
`table_type_requires_review`. Preserve the type through persistence: its two-column
calculation view is not `lookup_sections`. See CALCULATION_SHEET_CONTRACT.md.
