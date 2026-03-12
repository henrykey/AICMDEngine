# PDF2MD Enhanced Frontend Integration Notes

## Purpose

This note is for frontend developers integrating `PDF2MD Enhanced` into UI flows such as:

- document parsing progress
- page result preview
- markdown rendering
- structured metadata inspection
- knowledge-base ingestion review

It focuses on actual runtime behavior and integration boundaries, not internal server implementation details.

## Core Principle

Treat `render.markdown` as the display layer, and treat structured page JSON as the data layer.

Do not assume all pages have the same extraction path or the same output quality profile.

## What The Frontend Should Use

### For display

Use:

- `page_result.render.markdown`

This is the best available page-level display output and is suitable for:

- page preview
- markdown viewer
- export preview

### For structured workflows

Use:

- `page_result.elements.tables`
- `page_result.elements.formulas`
- `page_result.elements.figures`
- canonical page JSON produced by the client/test-side pipeline

This is the correct source for:

- knowledge-base ingestion review
- field inspection
- table/formula metadata panels
- downstream chunking/indexing pipelines

Do not try to reconstruct structured data from `render.markdown` in the frontend if structured JSON is already available.

## Output Variability

`PDF2MD Enhanced` supports both:

- scanned PDFs
- text-layer PDFs

These two classes do not behave the same internally.

### Scanned PDFs

Scanned pages rely more on VLM output.

Typical frontend expectation:

- stronger markdown rendering for formulas, figures, and layout
- less reliable direct text extraction

### Text-layer PDFs

Text-layer pages rely more on:

- direct text extraction
- code-based table reconstruction
- selective VLM enhancement

Typical frontend expectation:

- better plain text fidelity
- tables may be rebuilt from structured elements rather than directly emitted by the original page text

## Table Handling

Frontend must support two valid outcomes:

### 1. Real markdown table

This is the ideal case.

The UI can render it directly.

### 2. Table placeholder / semantic placeholder

This is also valid for:

- large tables
- wide horizontal tables
- complex layouts where exact reconstruction is intentionally downgraded

Frontend should:

- render the placeholder normally
- clearly indicate that the full numeric table should be checked against the original PDF page
- provide a direct way to open the source page when possible

Do not mark placeholder pages as extraction failures by default.

## Formula Handling

Frontend should not assume that every formula in structured data must also appear as a block formula in markdown.

Current behavior is intentionally conservative for text-layer table pages:

- table-related formulas should remain inside table/structured data
- only truly independent formulas should be appended into markdown render

This avoids duplicated formulas being appended at page tail.

## Recommended UI Elements

### Page-level preview panel

Recommended fields:

- page number
- render markdown preview
- original PDF page preview / jump link
- extraction mode
- table source
- placeholder count

### Structured inspection panel

Recommended sections:

- tables
- formulas
- figures
- decision metadata

This is important for debugging extraction issues without needing server logs.

## Recommended Debug Fields

Expose these when available:

- `page_result.decision.mode`
- `page_result.decision.table_source`
- `page_result.decision.table_placeholder_count`
- `page_result.decision.metrics`
- `page_result.decision.vlm_calls`

These fields help distinguish:

- scanned-page VLM extraction
- text-layer direct extraction
- table reconstruction path
- placeholder downgrade path

## Progress Display

Progress should be shown at task level, not internal subtask level.

For example:

- good: `page 24 (1/2)`, `page 25 (2/2)`
- avoid: multiple independent `1/1` progress displays for a single user request

The user should perceive one document task, even if the backend internally sends pages one by one.

## Frontend Must Not Do

Do not:

- send `render.markdown` back into another LLM for rewriting or beautification
- re-interpret placeholder tables as hard failures
- parse markdown back into tables when structured table data already exists
- assume all pages have exact layout fidelity

A second uncontrolled rewrite step in the frontend can easily break:

- table structure
- formula fidelity
- page-level alignment with original PDF

## Recommended Fallback UX

For pages with complex tables or placeholders, frontend should offer:

- markdown preview
- structured JSON preview
- open original PDF page
- copy page JSON
- copy markdown

This gives users an operational fallback instead of forcing the extraction result to look perfect in all cases.

## Suggested Integration Rule

Use this practical rule in frontend implementation:

- show `render.markdown` by default
- show structured elements in a side panel or expandable debug panel
- when page contains large-table placeholder, encourage users to inspect original PDF page
- when page looks suspicious, rely on structured JSON and source-page preview rather than visual markdown alone

## Summary

Frontend integration should treat `PDF2MD Enhanced` as a hybrid output service:

- markdown for display
- structured JSON for downstream data use
- original PDF page as the final reference for complex cases

This is the correct integration model for both scanned and text-layer PDFs.
