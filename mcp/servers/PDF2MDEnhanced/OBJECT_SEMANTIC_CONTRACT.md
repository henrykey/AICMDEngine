# Single-object semantic completion

`enhance_object_semantics(request, vlm_config)` is the MCP entry point for Membership semantic completion.
It reuses DynamicVLMClient; page parsing, cropped-object extraction and complex-table query conversion keep their
existing authoritative implementations. This endpoint does not re-extract an entire page or modify source content.

Request: `element_type` (table/formula/figure), exact `element_id`, `candidate_object`, requested `missing_fields`
(semantic_desc/formula_name/table_title), document_language (zh/en), bounded local_context, and request_id.
The router supplies the tenant-bound VLM configuration through the established tool-schema injection.
All supplied evidence is data, never model instructions. Input validation runs before provider creation.

A successful response echoes request_id, returns one same-identity object under `repairs.tables/formulas/figures`,
and records unresolved_fields plus evidence_basis=supplied_text_not_image_verified. Only requested semantic fields
and semantic confidence are permitted; HTML, cells, LaTeX and geometry are never replacement output.
Missing source names stay unresolved. `status=complete` means an accepted proposal, not that every requested field
was recovered; unresolved_fields and the consumer's quality validation still apply.

Failures contain a bounded reason code and model_calls; no exception payload is exposed. There is one provider
invocation per tool request and no corrective model prompt inside Membership. Underlying provider transport policy
is the existing DynamicVLMClient policy. Task retries belong to Membership.

This text endpoint does not claim image verification. Existing `extract_object_structured` remains the source-crop
transcription implementation. Offline tests do not establish real-model or original-document accuracy.
Both services need their matching source packages deployed and tool discovery refreshed before E2E acceptance.

Offline tests: `.venv/bin/python -m pytest -q --no-cov tests/test_pdf2md_object_semantics.py`

## Language result validation (2026-09-07)

The shared `semantic_language` module reuses the single-page language detector.
It checks generated prose, including an English heading followed by substantive
Chinese prose, and Chinese headings followed by English prose. For zh results,
prose after a short colon-delimited heading is checked separately. Four Han characters establish Chinese evidence; at least three
Latin words totalling twelve letters establish English evidence. Math blocks and
HTML tags are excluded. Short symbols/names alone do not establish a mismatch.
This conservative check is not a general multilingual classifier or proof of
semantic accuracy. Unknown document language does not reject an inferred result.
Copied source titles/names are retained, including in display summaries.

For `enhance_object_semantics`, a mismatching `semantic_desc` is removed from the
repair. If another requested field is valid, `complete` retains its existing
meaning (accepted partial proposal), with `quality.unresolved_fields` and
`quality.reasons=[description_language_mismatch]`. If no requested field remains
valid, the result is `failed`, without `repairs`, and includes the reason, quality,
request_id and actual logical model_calls. There is still only one logical call.
Consumers must never interpret `complete` alone as requested-field completion.
Provider, malformed-response and identity failures remain whole-proposal failures.

Upload, single-page table/formula/figure, structured-page and object-crop results
use the same checker. Rejected generated fields become empty, with
`semantic_reason=description_language_mismatch`, `semantic_status=unresolved` and
`missing_fields`. HTML, Markdown and LaTeX source artifacts remain unchanged;
consumers must not treat retained raw Markdown as a validated description.
`extract_page_layout_enhanced` now also accepts `description_language` (default
`unknown`), forwards it to figure prompting and validates its figure fields.

See `CONTENT_QUALITY_CONTRACT.md` for parent/cell relationships and actual crop
bytes. Neither endpoint writes back a page, stores an asset, nor updates an index.
