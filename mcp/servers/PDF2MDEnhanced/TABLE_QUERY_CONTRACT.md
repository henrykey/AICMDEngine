# Single-table query enhancement, contract 1

`extract_page_tables` accepts optional `query_enhancement`. Omit it to retain the
existing extraction behavior and response. The new branch operates on exactly one
supplied table; it does not OCR a page or discover adjacent objects. JSON output is
required. No additional packages are required.

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

Read-only call-chain check: `ReviewAutoCompletionJobService` chooses
`extract_page_tables`; `StructuredElementSemanticEnhancementService.run` instead
calls `StructuredElementSemanticRepairBackfillService.repairDocument` →
`StructuredElementSemanticRepairService.repairPage` → tenant-aware chat/model
repair. Updating MCP alone does not wire that semantic-enhancement path. No
Membership source, persistence, index or UI changes are included here.

## Offline verification

```sh
.venv/bin/python -m pytest -q --no-cov tests/test_pdf2md_enhanced_table_query.py tests/test_pdf2md_enhanced_single_page_tools.py tests/test_pdf2md_enhanced_object_recovery.py tests/test_pdf2md_enhanced_upload_semantics.py
```

Fixtures in Git are synthetic. Private samples, human bindings and their reports
remain under `/tmp/docintel-complex-table-samples-20260906/`. Real provider calls,
model-assisted image consistency, runtime deployment and Membership integration
require separate acceptance. Do not treat these offline tests as product rollout.
