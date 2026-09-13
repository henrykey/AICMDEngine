# PDF2MD figure export: reuse and bounded repair Goals Loop

## Authorization and baseline

2026-09-13: user authorized planning then local execution through coordinating task
`01a098b2-895b-7f11-95c0-d2af7d86ebc8`. Membership owner:
`01a098b3-9862-78c1-a9fa-793911837da8`; cross-repo plan:
[Membership figure reuse Goals Loop](/Users/kehongwei/workspace/membership/docs/plans/2026-09-13-FIGURE-EXTRACTION-REUSE-GOALS-LOOP.md).
Checkout: `/Users/kehongwei/workspace/AICMDEngine`, branch `main`, HEAD `8abf756`.
Retain existing owned candidates in `page_processor.py`, `single_page_tools.py`,
and `tests/test_pdf2md_content_quality.py`; do not treat prior 300 passing tests
as full cross-entry or runtime acceptance. Root AGENTS.md read; CodeGraph current
(older-engine notice). No relevant nested AGENTS/specification found in scanned paths.

Allowed: this plan, minimal source fixes, synthetic offline tests, syntax checks,
CodeGraph sync, diff review. Forbidden: commit/push, image/container operations,
deployment, real extraction/model calls, DB/S3 writes. No Membership source edits.

## Fixed constraints and decision gate

Keep 16M page pixels, 32 candidate positions, 8MiB per image, 16MiB total.
Keep model routing, call budgets, retry counts, and public response envelopes.
Source image/OCR, normalized bbox and source-page metadata remain authoritative.
Transport PNG dimensions must equal pixel_bbox spans in its export canvas.

Existing MCP capabilities: normalized crop to at most 150 DPI and model-recovery
2/3 image shrink. The latter is a model retry policy, not an asset export policy.
Membership has page-render fallbacks 180/150/120 DPI. Do not invent a new MCP
120 DPI/byte retry schedule or copy model retry policy into asset export.
Coordinate ownership of exhausted pixel/byte cases with Membership. Mark policy
work unresolved if existing mechanisms cannot satisfy it without a new rule.

## Loop and acceptance

For each goal: inspect -> failure-first check where applicable -> smallest change
-> focused validation -> self-review -> record evidence. Failed acceptance stays open.

| Goal | Work / acceptance | Status |
|---|---|---|
| G0 | Verify baseline, dirty ownership, instructions, index and boundaries | Complete |
| G1 | Map every figure entry and actual existing resize/field mechanisms | Complete; map below |
| G2 | Agree cross-repo fallback/coordinate contract, no new retry policy | Ownership agreed; D2 remains open |
| G3 | Failure-first synthetic tests for missing actual DPI/metadata/exports | Complete |
| G4 | Minimal reuse fixes at eligible entries; no guessed identity/geometry | Complete within existing policy; D2 excluded |
| G5 | Focused pytest, syntax, sync, diff audit; record limitations | Complete: 313 passed; syntax/diff/sync pass |
| G6 | Real TEMA p13 -> MCP -> Membership asset/readback | Not authorized; not accepted |

## Entry map and scope

- `page_processor.process_page`: layout-driven payloads call `_attach_figure_assets`;
  existing candidate forwards render DPI and resamples only oversized export pages.
  Non-layout paths lack trusted layout geometry: do not invent it or reroute OCR.
- `single_page_tools.extract_page_figures_direct`: `_extract_figure_page_result`
  returns `items`; `_figure_item` currently drops identity. Preserve supplied identity
  and attach existing assets only where normalized geometry is trusted.
- `extract_page_structured_direct`: `_extract_figures` feeds `figures`; same eligible
  asset handling without changing response envelope or model calls.
- layout-enhanced: `_figures_from_layout_blocks` keeps raw bbox/index, not normalized
  page identity. Preserve trustworthy fields if supplied; do not label raw bbox normalized.
- `context.structure_target`: currently tables only; generated cell figures share
  `_attach_figure_assets`. Actual PDF DPI is missing from model crop call; repair
  that argument without changing recovery policy.
- title-only/object-crop description: do not export another figure from a guessed
  page-relative crop identity. Existing caller-bound semantics remain unchanged.

## Validation matrix

Synthetic cases: 150/300 DPI small pages unchanged; oversized 300 page correct
150 export; still-overlimit page unresolved; colored quadrants/noninteger and edge
bboxes; original image hash, source metadata and normalized bbox unchanged;
PNG/header dimensions equal pixel_bbox spans; count/single/total budgets unchanged;
missing/NaN/out-of-range geometry rejected; no temporary leaks; real PDF context
DPI forwarded; all eligible entry envelopes/identity retained; model counts unchanged.
Policy-dependent further fallback cases remain G2, never implied by local green tests.

## Execution report

- G0/G1: read-only source inspection completed. Prior candidate retained. No runtime
  artifact inspected. Oracle missing-layout causality remains unproven: compare the
  same request raw MCP response, adapter, stored record and readback plus runtime HEAD.
- G2: Membership owner confirmed its existing `DocumentPageRenderService` owns
  requested 150 -> 120 PDF render fallback with its unchanged 18M limit. MCP owns
  the existing 150 export adaptation and unchanged 16M/32/8MiB/16MiB limits.
  Identity/integrity errors do not authorize fallback. No asset lifecycle resize
  policy is introduced in this repository.
- **D2 decision gate:** neither current mechanism provides crop-byte/total-byte
  adaptive downsampling. MCP has no existing 120 asset schedule. These cases still
  return the existing unresolved reason; this is NOT full acceptance of "all
  applicable shrinking strategies exhausted". A new policy needs an explicit
  decision rather than copying model 2/3 retries. Pixel failure may be recovered
  by Membership's existing trusted-source rendering, subject to its own acceptance.
- G3: initial entry-test stub lacked the OCR `source` constructor keyword; corrected
  the fixture before claiming regression evidence. Then
  `/tmp/pdf2md-export-entry-red.log`: **3 failed, 3 passed**; bound figures lost
  `layout_id` in direct/structured/layout-enhanced, unbound negative cases passed.
  `/tmp/pdf2md-export-dpi-red.log`: PDF structure recovery produced 120x120 at
  renderDPI=300 instead of existing 150-DPI crop's expected 60x60.
- G4: retained oversized-page export candidate and actual DPI context forwarding;
  fixed the missing structure-recovery crop argument. Preserved explicit
  `layout_id`/`bbox_space` and attached the existing export result at three single-page
  entries only when identity and normalized bbox exist. Candidate positions still
  count toward the same limit. Unknown geometry and object-crop descriptions do
  not acquire guessed page assets. No extra provider call or new tool parameter.
- Public compatibility: response envelopes `items` / `figures` remain unchanged;
  eligible figure items now additionally preserve `layout_id` and contain the
  existing `image_asset` schema. Layout-enhanced raw pixel boxes without explicit
  normalized coordinates remain metadata only; no normalization is invented.
- Self-review caught and corrected an initial patch matching an unrelated formula
  metadata loop; the final diff changes only the figure loop.
- Covered offline: budget boundaries with controlled encoded sizes, invalid bbox,
  32/33 counts, colored crop geometry, edge/noninteger landscape bounds, 150/300 DPI,
  source hash and original dimensions, PNG hash and identity, temporary cleanup,
  direct/structured/layout-enhanced model counts and object-crop negative cases.
  Encoded-size stubs isolate budget logic; actual PNG fixtures separately validate
  geometry/integrity. No OCR/model response quality claim follows from stubs.

### Validation command

```sh
.venv/bin/python -m pytest -q --no-cov tests/test_pdf2md_content_quality.py tests/test_pdf2md_quality_completion.py tests/test_pdf2md_enhanced_object_recovery.py tests/test_pdf2md_enhanced_single_page_tools.py tests/test_pdf2md_enhanced_bad_text_policy.py
```

Log: `/tmp/pdf2md-export-reuse-tests.log`. Each edit batch followed by CodeGraph
sync; targeted modules/tests checked with `py_compile` and `git diff --check`.
Final run: **313 passed, 64 warnings, 11.53s** (dependency/deprecation warnings).
No commit, push, container, deployment, real-model, real-document, DB or S3 action.
G6 and Oracle field provenance remain unverified, not automatically accepted by G5.
