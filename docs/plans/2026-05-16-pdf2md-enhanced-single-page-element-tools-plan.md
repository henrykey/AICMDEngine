# PDF2MD Enhanced Single Page Element Tools Plan

Date: 2026-05-16

## Background

PDF2MD Enhanced already supports task-oriented page extraction and hybrid OCR routing for full document workflows. That flow is suitable for normal ingestion, retry, resume, and page persistence.

Membership DocIntel also needs a smaller repair-oriented workflow:

- A large PDF has already been processed.
- One page was extracted poorly.
- The user wants to run a direct single-page tool against that page.
- The user knows whether they want tables, formulas, figures, or all structured elements.
- The tool should do only the selected job and return focused output.

This plan adds direct single-page MCP tools to PDF2MD Enhanced for extraction repair and manual补漏. These tools do not replace the existing task lifecycle.

## Goals

1. Add four explicit MCP tools:
   - `extract_page_tables`
   - `extract_page_formulas`
   - `extract_page_figures`
   - `extract_page_structured`
2. Each tool processes exactly one PDF page or one image.
3. The first three tools are single-purpose:
   - table tool extracts only tables
   - formula tool extracts only formulas
   - figure tool extracts only figures
4. Return JSON by default and optionally Markdown for human inspection.
5. Support descriptions for extracted tables, formulas, and figures.
6. Do not create tasks, page records, retries, or task output files.
7. Reuse existing PDF rendering, OCR clients, VLM client, and normalizers where practical.
8. Preserve existing `start_task` / `process_task_page` behavior.

## Non-Goals

1. Do not add another general-purpose `extract_element` tool with `element_type`.
2. Do not replace `process_task_page`.
3. Do not process multiple pages in one call.
4. Do not build a new task lifecycle.
5. Do not index or persist results.
6. Do not describe non-selected element types in single-purpose tools.
7. Do not use GLM-OCR as the final source for figure semantic descriptions.

## Tools

### `extract_page_tables`

Purpose:

- Extract tables from one PDF page or one image.
- Ignore formulas and figures even if they appear on the same page.

Expected output fields:

```json
{
  "tool": "extract_page_tables",
  "source": {
    "input_type": "pdf | image",
    "page_no": 1
  },
  "items": [
    {
      "source": "pymupdf | glm_ocr | vlm_ocr",
      "title": "",
      "markdown": "",
      "description": "",
      "context": ""
    }
  ],
  "model_calls": {
    "glm_ocr": 0,
    "vlm_ocr": 0
  },
  "warnings": []
}
```

Extraction strategy:

1. For PDF input, try PyMuPDF native table extraction first.
2. If native table extraction is empty or insufficient, use GLM-OCR when enabled.
3. If GLM-OCR is unavailable or fails, fallback to VLM-OCR when enabled.
4. Descriptions should be conservative and based on table title, nearby text, headers, and table shape.

### `extract_page_formulas`

Purpose:

- Extract formulas from one PDF page or one image.
- Ignore tables and figures even if they appear on the same page.

Expected output fields:

```json
{
  "tool": "extract_page_formulas",
  "source": {
    "input_type": "pdf | image",
    "page_no": 1
  },
  "items": [
    {
      "source": "glm_ocr | vlm_ocr",
      "latex": "",
      "description": "",
      "variables": "",
      "context": ""
    }
  ],
  "model_calls": {
    "glm_ocr": 0,
    "vlm_ocr": 0
  },
  "warnings": []
}
```

Extraction strategy:

1. Use GLM-OCR first when enabled because formula LaTeX normalization is the main goal.
2. Fallback to VLM-OCR when GLM-OCR is disabled, unavailable, or returns no formulas.
3. For PDF input, use text-layer context around formula indicators such as `按下式`, `式中`, `公式`, and equation numbers.
4. Descriptions should be conservative and based on nearby text and `式中` variable blocks.

### `extract_page_figures`

Purpose:

- Extract figure information from one PDF page or one image.
- Ignore tables and formulas even if they appear on the same page.
- Return figure descriptions.

Expected output fields:

```json
{
  "tool": "extract_page_figures",
  "source": {
    "input_type": "pdf | image",
    "page_no": 1
  },
  "items": [
    {
      "source": "vlm_ocr",
      "caption": "",
      "type": "schematic | chart | diagram | figure | unknown",
      "description": "",
      "labels": [],
      "context": ""
    }
  ],
  "model_calls": {
    "glm_ocr": 0,
    "vlm_ocr": 1
  },
  "warnings": []
}
```

Extraction strategy:

1. Use VLM-OCR as the required source for figure semantic descriptions.
2. GLM-OCR may be used only for optional caption or layout hints if this becomes useful later.
3. If VLM-OCR is unavailable, return an empty item list with a warning rather than fabricating a description.
4. The prompt must ask only for figures and must ignore tables/formulas.

### `extract_page_structured`

Purpose:

- Extract tables, formulas, and figures from one PDF page or one image.
- This is the only comprehensive tool among the four.
- Use it when the user wants a full single-page structured repair pass.

Expected output fields:

```json
{
  "tool": "extract_page_structured",
  "source": {
    "input_type": "pdf | image",
    "page_no": 1
  },
  "tables": [],
  "formulas": [],
  "figures": [],
  "semantic_status": {
    "complete": true,
    "missing": [],
    "reason": ""
  },
  "model_calls": {
    "glm_ocr": 0,
    "vlm_ocr": 0
  },
  "warnings": []
}
```

Extraction strategy:

1. Reuse the hybrid OCR approach:
   - PyMuPDF / text layer for PDF context and native tables.
   - GLM-OCR for tables and formulas.
   - VLM-OCR for figure descriptions.
2. The comprehensive tool can merge model outputs, but it should still keep each element source explicit.
3. If figure descriptions are required but VLM-OCR is disabled or fails, set `semantic_status.complete = false`.

## Common Parameters

All four tools should accept the same input and runtime config shape:

```python
file_path: Optional[str] = None
file_data: Optional[str] = None
file_url: Optional[str] = None
page_no: int = 1
input_type: str = "auto"      # auto | pdf | image
output_format: str = "json"   # json | markdown
describe: bool = True
ocr_config: Optional[dict] = None
vlm_config: Optional[dict] = None
routing_config: Optional[dict] = None
```

Rules:

- Exactly one source should be provided among `file_path`, `file_data`, and `file_url`.
- `page_no` is used only for PDF input.
- Image input is treated as one page; `page_no` is metadata only.
- `output_format=json` returns machine-readable JSON.
- `output_format=markdown` formats the same result into human-readable Markdown.
- `describe=false` may omit table/formula descriptions but should not suppress figure descriptions unless explicitly documented.

## Input Handling

### PDF Input

For PDF input:

1. Resolve the source with the existing source resolver or an equivalent direct helper.
2. Open the PDF with PyMuPDF.
3. Validate `page_no`.
4. Render only that page to a temporary PNG when OCR/VLM is needed.
5. Use the page text layer only as context for descriptions and native table extraction.

### Image Input

For image input:

1. Resolve source to a local image file.
2. Do not open with PyMuPDF.
3. Send the image directly to GLM-OCR or VLM-OCR based on the selected tool.
4. Return `source.input_type = "image"`.

Supported image extensions for `input_type=auto` should include:

- `.png`
- `.jpg`
- `.jpeg`
- `.webp`
- `.bmp`
- `.tif`
- `.tiff`

## Model and Prompt Strategy

### Table Prompt

Prompt must explicitly say:

- Extract tables only.
- Ignore formulas unless they are table cell contents.
- Ignore figures.
- Return strict JSON with table title, markdown, and optional description.

### Formula Prompt

Prompt must explicitly say:

- Extract formulas only.
- Ignore tables and figures.
- Return LaTeX.
- Include nearby variable explanations when visible.
- Return strict JSON.

### Figure Prompt

Prompt must explicitly say:

- Extract figures only.
- Ignore tables and formulas.
- Describe technical diagrams and visual semantics.
- Return labels and caption when visible.
- Return strict JSON.

### Structured Prompt

Prompt can request tables, formulas, and figures together, but should preserve separate arrays and explicit sources.

## Output Format

### JSON

All tools should return JSON strings because MCP tools return strings.

### Markdown

When `output_format=markdown`, format from the same internal result object:

- table tool:
  - title
  - description
  - markdown table
- formula tool:
  - description
  - LaTeX block
  - variables
- figure tool:
  - caption
  - type
  - description
  - labels
- structured tool:
  - sections for tables, formulas, and figures

Do not run a second model call only to create Markdown.

## Implementation Plan

### Phase 1: Direct Single-Page Helpers

Add a helper module under `mcp/servers/PDF2MDEnhanced`, for example:

```text
single_page_tools.py
```

Responsibilities:

- resolve PDF/image input
- infer input type
- render PDF page to image
- collect PDF text context when available
- format JSON and Markdown output

### Phase 2: Element-Specific Extractors

Add focused internal functions:

```python
extract_tables_from_page(...)
extract_formulas_from_page(...)
extract_figures_from_page(...)
extract_structured_from_page(...)
```

Each function should call only the model path needed for its tool.

### Phase 3: Server Tool Registration

Register four MCP tools in `server.py`:

```text
extract_page_tables
extract_page_formulas
extract_page_figures
extract_page_structured
```

Keep tool signatures explicit and similar so they are easy to select in MCP UI/tool settings.

### Phase 4: Tests

Add focused tests for:

1. `extract_page_tables` ignores formulas and figures.
2. `extract_page_formulas` ignores tables and figures.
3. `extract_page_figures` ignores tables and formulas.
4. image input routes directly to OCR/VLM without PyMuPDF page text.
5. PDF input validates `page_no`.
6. `output_format=markdown` formats the same JSON result.
7. GLM failure in table/formula extraction falls back to VLM when enabled.
8. figure extraction returns warning when VLM is disabled.
9. structured extraction returns separate `tables`, `formulas`, and `figures` arrays.

## Acceptance Criteria

1. Four explicit MCP tools are available.
2. Each single-purpose tool extracts only its target element type.
3. All tools support PDF page and image input.
4. All tools support JSON and Markdown output.
5. Table/formula tools prefer GLM-OCR and fallback to VLM-OCR.
6. Figure tool uses VLM-OCR for descriptions.
7. No task is created or updated by these tools.
8. Existing task-oriented PDF2MD Enhanced tools continue to pass existing tests.
9. README documents the new tools and their intended补漏 use case.

## Open Questions

1. Should `file_url` support remote image URLs in the first implementation, or only remote PDFs already supported by the source resolver?
2. Should `describe=false` be allowed for figures, or should figure descriptions always be returned?
3. Should extracted figure image crops be returned or persisted later, or is textual description enough for the first version?
4. Should table descriptions be deterministic only, or should model-generated table descriptions be allowed when `describe=true`?

