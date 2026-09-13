# Calculation sheet MCP P1 contract for alignment

Status: wire contract frozen with Membership M1 on 2026-09-13, including its
requested base64 image transport. Implementation and runtime acceptance pending.
The existing `extract_page_tables` tool remains the only public extraction entry.

## Request

Retain all current parameters. Add:

| Field | Values / meaning |
| --- | --- |
| `table_kind_hint` | `auto` (default), `data_table`, `calculation_sheet` |
| `processing_mode` | `auto` (default), `organize_existing`, `reextract` |
| `context.calculation_request.identity` | `tenant_id`, `doc_id`, `version`, `page_no`, `table_pk`, `layout_id`, `source_sha256` |
| `context.calculation_request.existing_content` | Text for organize-existing mode, limited to 100000 characters; supplied content remains authoritative |
| `context.calculation_request.adjacent_objects` | Up to two relevant objects, at most one on each immediately adjacent PDF page, each with identity, `image_data` (base64 PNG/JPEG/WebP), and `source_text` (at most 100000 characters) |
| `context.calculation_request.bbox` | Normalized current-object region on a full page; required unless `context.object_crop=true` supplies an already isolated object |

Identity `source_sha256` means the full source PDF bytes, consistently for current
and adjacent objects. It is distinct from existing classification and calculation
OCR-text/source-content hashes. Membership supplies authorized identities and
same-scope context; MCP validates shape and scope consistency but cannot establish
database ownership. Existing callers without the extension keep existing behavior.

Identity must be echoed unchanged on a result for the selected object, never
broadcast onto every detected table on a page. Identity or image matching failure
must return an explicit diagnostic, never fall back to a whole-page result.

`auto` retains four-class image classification. Manual hints constrain only the
explicitly selected object. `reextract` requires a non-auto hint and that object's
image. `organize_existing` requires a non-auto hint and supplied content; it must
not fetch an image or assert image verification. No mode executes equations.
Normal descriptions-disabled/deterministic extraction gains no implicit calls.

Adjacent images use base64 bytes, not container-local paths. Each decoded image
is limited to 8 MiB; no remote fetching mechanism is added. The current image
uses existing `file_data`/`file_path` input. One bounded joint
review may revisit an uncertain or wrongly classified starting object; return its
separate proposed classification, never copy its items into the current object.
Membership validates each resulting relationship and schedules pending retries.

## Response additions and preserved fields

| Field | Meaning |
| --- | --- |
| `table_kind` | Existing four kinds; absent legacy type keeps existing default semantics |
| `table_kind_source` | `automatic` or `manual`; legacy absence is not automatic success |
| `content_format` | `calculation_sheet_json` for calculation sheets |
| `calculation_sheet` | Existing sections/items, sources and independent content quality |
| `table_classification` | Existing fields plus bounded `reason` / `diagnostics` and `proposed_kind`; no percentage confidence |
| `calculation_identity` | Exact validated current request identity |
| `continuation.status` | `none`, `proposed`, `pending`, `conflict` |
| `continuation.predecessor` | Identity of one proposed predecessor, only for `proposed` |
| `continuation.reason` | Stable diagnostic code |
| `continuation.reviewed_objects` | Separate identity-bound type proposals for bounded joint review, without foreign content |

All outputs are proposal/draft inputs. `proposed` does not mean a persisted group
assignment. Existing `table_content_quality` remains separate from classification
and continuation. Classification success must survive incomplete item extraction.
Calculation/mixed/uncertain output remains unavailable for ordinary lookup.

Proposed diagnostic vocabulary:

- `classification_kind_invalid`, `classification_evidence_missing`,
  `classification_evidence_mismatch`, `classification_evidence_ambiguous`,
  `classification_model_uncertain`, `classification_not_run`;
- `source_image_unavailable`, `calculation_identity_mismatch`,
  `adjacent_context_required`, `adjacent_context_invalid`,
  `continuation_evidence_conflict`;
- retain `table_analysis_budget_exhausted`, `calculation_provider_failed`,
  `calculation_response_incomplete`, and existing item-validation reasons.

Counts must distinguish logical calls and transport retries. Existing page logical
budget (0–8, default 2) also bounds joint review and manual model operations;
exhaustion must not trigger a hidden repair loop. Timeouts/cancellation return
failure without deleting supplied content or changing manual type.

The new processing client additionally enforces a physical HTTP request cap,
including redirects, streaming fallback and token-limit corrections. Its SDK and
outer retries are disabled. Default cap is `2 * min(logical_budget, 1)` for
`organize_existing`, and `2 * min(logical_budget, 2)` otherwise (normally 2 or 4).
`vlm_config.table_analysis_max_physical_requests` may lower that cap to an integer
including zero, but cannot raise it. The response `budget` additionally reports
`physical_requests`, `physical_request_limit` and `sdk_retries=0` when using the
instrumented client. Exhaustion is `table_analysis_physical_budget_exhausted`.
Invalid caps fail as `invalid_physical_model_budget`. Each new RPC has a new
budget; the coordinating task must reserve quota for every dispatch, follow-up
and retry to enforce a whole-run cap.

## Source-image annotations

Local sources found under `/Users/kehongwei/Documents/GB/`:

- GBT151 test set: 30 PDF pages; SHA-256
  `7584d18d5aea4539ff8ee6efae27981b37fb49ef7cea14d0a1f5facb0ce6f95c`.
- ASME test set: 38 PDF pages; SHA-256
  `0edbecf5e98c86657f8324c586118a350421d05386fb47f0427144c77b5085bd`.

The following annotations came from local rendered original pages, not model
results. No original text, formula transcription or page image is included here.

| Source / PDF page / table | Expected type | Relationship and required coverage |
| --- | --- | --- |
| ASME / 11 / 4.2.14 | data_table | Parallel joint-detail records; formulas and drawings do not make it a calculation sheet |
| ASME / 12 upper / 4.12.1 | data_table | Configuration lookup; not part of lower calculation sheet |
| ASME / 12 lower / 4.12.2 | calculation_sheet | Start; membrane/bending stresses, constants, acceptance criteria |
| ASME / 13 upper / 4.12.2 | calculation_sheet | Continues preceding row; defined-location criteria and symbol definitions remain calculation content |
| ASME / 13 lower / 4.12.3 | calculation_sheet | New type-2 object; must not attach to upper 4.12.2 |
| GBT151 / 7 (printed 66) / 8-5 | calculation_sheet | Design inputs, gasket/bolt data, operating/preload conditions, forces/arms/moments, thickness checks, embedded diagram association |
| GBT151 / 8 (printed 67) / 8-6 | calculation_sheet | Different table and component; reference to 8-5 is not continuation |
| GBT151 / 9 (printed 77) / 8-8 and 8-9 | data_table | Fixed pressure/type lookup axes with formula-valued cells; title containing calculation is insufficient |

GBT151 8-5 intentionally leaves inputs/results blank. Preserve blanks and units;
do not treat the lack of filled numeric results as extraction omission. Its
embedded diagram must remain associated with that object, not become grid cells.

The Membership document ID/version and equality of the stored original PDF hash
to these local sources still need verification. The user's supplied location is
category `test`; no document ID or PDF page was guessed from that category.

## Required shared synthetic fixture cases

The shared fixture is `tests/fixtures/calculation_processing_contract.json` in
AICMDEngine; Membership consumes an identical copy. Cases must cover
each processing mode, manual constraint persistence, same-object identity echo,
wrong scope/hash, missing image/context, predecessor proposal versus conflict,
out-of-order arrival, empty template fields, model failure, budget exhaustion and
late-result rejection in Membership. Synthetic content avoids committing source
documents or model transcripts.
