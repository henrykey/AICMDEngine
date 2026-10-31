# Changelog

## v1.2.6 - 2026-10-31

### Changed

- Added bounded table and cell-image recovery while preserving recognized source content, layout identities, and unresolved diagnostics.
- Improved crop boundary checks and expansion for thin lines and dimensions; retained structured JSON and parse-failure diagnostics.
- Separated provider and per-object recovery budgets, optional formula descriptions, and document-run retention.

### Integration and verification

- Pair with Membership `v2.4-R0.4.2`; classification, Stage 1 persistence, and indexing remain Membership responsibilities.
- Targeted offline regression: 490 passed, 2 failed. The two failures concern expected cell-image missing fields and recovery invocation; their causes remain to be resolved.
- Real ASME selected-page results and remaining full-document performance limitations are documented in [Release Notes — v1.2.6](RELEASE_NOTES_v1.2.6.md).

## v1.2.5 - 2026-10-10

### Added

- Added source-bound calculation-sheet processing, explicit continuation, bounded block OCR/VLM transcription, optional per-formula semantics, and identity-bound PNG extraction.
- Added source-bound complex table queries, evidence-validated object semantic completion, and shared Docs/MCP conversion contract fixtures.
- Added Plan2 Thinking controls and safe provider diagnostics.

### Changed

- Returned classification, semantic orchestration, recovery selection, and request-budget ownership to Membership Docs; conversion tools preserve readable source without implicit business enrichment.
- Made object semantic and table-query operations single-attempt; explicit recovery uses caller-selected regions and engines while preserving source identity, ordering, and complete source on failure.
- Applied shared Thinking policy to MCP requests and retained source content when optional structured processing fails.

### Fixed

- Fixed formula-number and math-delimiter handling, table-cell image recovery, caption recovery, and incomplete-object evidence preservation.
- Fixed MCP WebSocket concurrency and stale connection mapping cleanup, and PDF2MD image module packaging.

### Integration and verification

- Pair with Membership `v2.4-R0.4.0`; callers must explicitly orchestrate classification and semantic processing.
- 943 targeted offline Python tests passed; existing HTTP transport failures and the remote manual script are excluded. Real-model/document, runtime UI, and deployment acceptance remain pending.
- See [Release Notes — v1.2.5](RELEASE_NOTES_v1.2.5.md) for details and validation boundaries.

## v1.2.4 - 2026-09-03

### Added

- Added `description_language` propagation across PDF2MD Enhanced task creation, page processing, OCR/VLM configuration, and single-page structured extraction.
- Added automatic semantic-description language detection when callers do not provide an explicit language.

### Changed

- Updated table, formula, and figure recovery prompts and fallback summaries to preserve the requested description language while retaining source-language titles, labels, values, symbols, and formulas.
- Normalized recovered figure descriptions to plain semantic text and discarded label-only or markup-wrapped descriptions.
- Reduced repetitive external MCP connection and background-reconnect logging while retaining actionable startup failures.

### Fixed

- Fixed semantic descriptions reverting to the wrong language during PDF2MD task processing, recovery, or fallback generation.
- Fixed recovered figure descriptions leaking HTML, XML, Markdown, code fences, or bare figure labels into structured output.

## v1.2.2 - 2026-08-01

### Added

- Added a hardened PDF2MD Enhanced OCR-first page-processing path with structured regression coverage for incomplete or unreliable PDF text.
- Added deployment contracts for container ownership and wheelhouse cache integrity.
- Added the structured-extraction hardening goals-loop plan.

### Changed

- Improved PDF2MD Enhanced page processing so OCR output remains the primary page source and VLM is used only for targeted recovery or semantic enrichment.
- Improved external MCP deployment wiring, stable Compose ownership checks, host routing, and platform-specific wheelhouse cache handling.

### Fixed

- Fixed unsafe text-layer fallback behavior that could discard or corrupt structured page content.
- Fixed deployment cache replacement so a failed dependency download does not destroy a known-good wheelhouse.

## v1.2.1 - 2026-05-20

### Added

- Added MCP Router external-tool engine summary logging for PDF2MD Enhanced results, including `model_calls`, item sources, and VLM runtime metadata when available.
- Added conditional VLM metadata enrichment for `extract_page_tables`: GLM keeps table structure, while VLM fills missing or unreliable table titles and semantic descriptions.

### Changed

- Updated `revise_page_markdown` default prompt to remove page headers, footers, page numbers, and repeated standard-code headers from revised page Markdown.
- Improved single-page table title normalization from GLM/VLM responses, including `table_title`, `tableName`, `table_name`, and `表名`.
- Improved GLM layout table title propagation and raw table-title fallback handling.
- Generate local table semantic descriptions from reliable table names and column headers without calling VLM.
- Documented the rule that code and documentation edits require explicit user modification instructions.

### Fixed

- Fixed PDF2MD Enhanced table results where VLM/GLM table names could be returned only in raw metadata or semantic fields and fail to populate `items[].title`.
- Aligned the single-page table README/spec with the actual current response shape.

## v1.2.0 - 2026-05-19

### Added

- Added PDF2MD Enhanced single-page extraction tools for tables, formulas, figures, structured output, layout analysis, and enhanced layout extraction.
- Added `revise_page_markdown` for image-based single-page Markdown revision in DocIntel review workflows.
- Added MCP Router schema-driven VLM/OCR config injection for external MCP tools, including `vlm_config`, `vlm_defaults`, and `ocr_config`.
- Added tests and script coverage for PDF2MD Enhanced single-page extraction and page Markdown revision flows.

### Changed

- Improved PDF2MD Enhanced hybrid OCR routing and documented provider configuration.
- Improved single-page table normalization, merged-cell handling, blank/unreadable cell status, and structured row output.
- Improved figure extraction output to include both figure names and semantic descriptions, with Chinese-language prompt guidance for Chinese documents.
- Kept PDF2MD GLM-OCR provider settings visible in MCP server metadata.
- Extended Plan2 smart import proxy timeouts and aligned MCP build platform handling.

### Fixed

- Fixed LLM provider list loading.
- Hardened MCP Router audit system token handling.
- Configured MCP message size limits.
- Fixed Aliyun MCP routing and Plan2 API fallbacks.
- Improved deployment service selection and China mirror support.

## v1.0.2 - 2026-04-17

- Previous tagged release.
