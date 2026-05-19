# Changelog

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
