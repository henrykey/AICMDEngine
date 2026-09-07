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
