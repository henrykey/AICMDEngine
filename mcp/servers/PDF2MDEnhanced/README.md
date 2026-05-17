# PDF2MD Enhanced

Task-oriented MCP service for page-by-page PDF processing.

## Service name

`pdf2md-enhanced`

## Core tools

- `start_task`
- `process_task_page`
- `analyze_page_layout`
- `extract_page_layout_enhanced`
- `extract_page_tables`
- `extract_page_formulas`
- `extract_page_figures`
- `extract_page_structured`
- `get_task_status`
- `retry_failed_pages`
- `finalize_task`
- `health_check`

## Runtime OCR configuration

`process_task_page` keeps the existing `vlm_config` argument and also accepts optional `ocr_config`.
The single-page tools also accept both arguments.

`ocr_config` can be injected by the caller at runtime. When called through the AICMDEngine MCP router, Plan2's MCP settings can also bind a separate `GLM-OCR Provider` for `pdf2md-enhanced`; the router converts that provider into `ocr_config.glm_ocr` for `process_task_page` and the single-page extraction tools. The existing `LLM Provider` binding remains the VLM provider and is injected as `vlm_config` or `vlm_defaults`.

The service does not require global environment variables for normal GLM-OCR or VLM-OCR routing.

Example:

```json
{
  "glm_ocr": {
    "enabled": true,
    "base_url": "http://host.docker.internal:11434/v1",
    "api_key": "ollama",
    "model": "glm-ocr",
    "timeout_sec": 300,
    "max_retries": 2
  },
  "vlm_ocr": {
    "enabled": true,
    "base_url": "https://example.openai-compatible/v1",
    "api_key": "...",
    "model": "vision-model",
    "timeout_sec": 300,
    "max_retries": 2
  }
}
```

`routing_config` can also include routing flags:

```json
{
  "routing": {
    "hybrid_ocr_enabled": true,
    "glm_ocr_enabled": true,
    "vlm_ocr_enabled": true,
    "full_vlm_fallback_enabled": true,
    "figure_semantic_description_required": true
  }
}
```

## Routing modes

Page processing now reports capability-oriented route names:

- `text_only`: reliable text layer, no OCR model call.
- `hybrid_glm_ocr`: text layer body plus GLM-OCR table/formula extraction.
- `hybrid_vlm_ocr`: text layer body plus VLM-OCR visual/figure semantics.
- `full_glm_ocr`: full-page GLM-OCR for scanned or bad-text pages.
- `full_vlm_ocr`: full-page VLM-OCR fallback or visual-heavy extraction.
- `blank`: blank-page placeholder, completed without OCR calls.

`decision.mode` remains backward-compatible with the older internal modes (`DIRECT`, `REGION_VLM`, `FULL_VLM`). Results also include `legacy_route_selected` with the older `text_layer` or `vlm` value for clients that still need it.

If GLM-OCR is disabled, text-layer/VLM behavior is preserved. If VLM-OCR is disabled and figure semantics are required, the page is completed with an explicit incomplete semantic status instead of fabricating a figure description.

## Page output fields

Each page result includes:

- `route_selected`: one of the capability route names above.
- `legacy_route_selected`: previous coarse route value.
- `semantic_status`: `complete`, `missing`, and `reason` fields for semantic completeness.
- `decision.glm_calls` and `decision.vlm_calls`: model call counts.
- `decision.engine_selected` and `decision.fallback_reason`: routing and fallback diagnostics.
- `elements.tables`, `elements.formulas`, `elements.figures`: structured RAG elements with explicit `source` such as `pymupdf`, `glm_ocr`, or `vlm_ocr`.
- `rag.page_text`, `rag.content`, and `rag.elements`: retrieval-friendly page payload.

## Single-page repair tools

These tools are direct补漏 tools for one page or one page image. They do not create tasks, do not update task status, and do not write page results to `data/tasks`.

All single-page tools accept the same source fields:

```python
file_path: Optional[str] = None
file_data: Optional[str] = None
file_url: Optional[str] = None
page_no: int = 1
input_type: str = "auto"      # auto | pdf | image
output_format: str = "json"   # json | markdown
ocr_config: Optional[dict] = None
routing_config: Optional[dict] = None
```

`extract_page_tables`, `extract_page_formulas`, `extract_page_figures`, `extract_page_structured`, and `extract_page_layout_enhanced` also accept `vlm_config`. `extract_page_tables`, `extract_page_formulas`, `extract_page_figures`, and `extract_page_structured` accept `describe`. `extract_page_tables` also accepts `table_rows_format` (`structured_json`, `markdown`, `csv`, or `tsv`) and defaults to `structured_json` so DocIntel can publish normalized rows without parsing Markdown. `analyze_page_layout` is a GLM-OCR layout-only tool and does not require VLM config.

Use exactly one of `file_path`, `file_data`, or `file_url`. For PDF input, `page_no` selects the page. For image input, the image is treated as a single page.

### `analyze_page_layout`

Recognizes the layout of a single page or page image. Use this first when the page type is unclear.

Strategy:

- Uses GLM-OCR `layout_parsing`.
- Returns page Markdown plus normalized layout blocks.
- Each block includes type, normalized bbox, content, width, and height.
- The summary recommends which single-page repair tool to use next.

JSON result shape:

```json
{
  "tool": "analyze_page_layout",
  "source": {"input_type": "image", "page_no": 1, "source_sha1": "..."},
  "markdown": "...",
  "blocks": [
    {"index": 1, "type": "text|table|formula|image", "bbox": [0, 0, 1, 1], "content": ""}
  ],
  "summary": {
    "block_counts": {"text": 2, "table": 1},
    "dominant_type": "mixed",
    "has_text": true,
    "has_table": true,
    "has_formula": false,
    "has_image": false,
    "recommended_tool": "extract_page_structured"
  },
  "model_calls": {"glm_ocr": 1, "vlm_ocr": 0},
  "warnings": []
}
```

### `extract_page_layout_enhanced`

Runs one GLM-OCR layout pass and returns the page Markdown, layout blocks, and block-derived table/formula/figure arrays. For `image` blocks, it calls VLM once with the full page image plus block `bbox`/index hints, then attaches semantic descriptions to the matching figure items. It does not crop images or upload/store files.

Strategy:

- Uses GLM-OCR `layout_parsing`.
- Returns full-page Markdown as recognized by GLM-OCR.
- Returns normalized blocks with bbox and content.
- Derives `tables`, `formulas`, and `figures` directly from block labels.
- Uses VLM only to describe `image` blocks; if there are no image blocks, VLM is not called.

JSON result shape:

```json
{
  "tool": "extract_page_layout_enhanced",
  "source": {"input_type": "image", "page_no": 1, "source_sha1": "..."},
  "markdown": "...",
  "blocks": [
    {"index": 1, "type": "text|table|formula|image", "bbox": [0, 0, 1, 1], "content": ""}
  ],
  "tables": [{"source": "glm_ocr_layout", "markdown": "...", "bbox": [0, 0, 1, 1]}],
  "formulas": [{"source": "glm_ocr_layout", "latex": "$$...$$", "bbox": [0, 0, 1, 1]}],
  "figures": [{"source": "glm_ocr_layout+vlm_ocr", "caption": "Figure 1", "description": "...", "bbox": [0, 0, 1, 1]}],
  "summary": {"recommended_tool": "extract_page_structured"},
  "model_calls": {"glm_ocr": 1, "vlm_ocr": 1},
  "warnings": []
}
```

Field details:

- `tool`: Always `extract_page_layout_enhanced`.
- `source`: Input metadata.
  - `input_type`: Resolved input type, `image` or `pdf`.
  - `page_no`: Page number used for PDF input. Image input is always treated as one page.
  - `source_sha1`: SHA1 of the original input file.
- `markdown`: Full-page Markdown returned by GLM-OCR layout parsing. This is the page-level reading-order output and may include text, formulas, table HTML/Markdown, and image placeholders depending on GLM-OCR output.
- `blocks`: Normalized layout blocks from GLM-OCR.
  - `page`: 1-based page index from the GLM-OCR layout response.
  - `index`: Block index assigned by GLM-OCR.
  - `type`: Block label such as `text`, `title`, `table`, `formula`, `image`, or `unknown`.
  - `bbox`: `[x1, y1, x2, y2]` coordinates from GLM-OCR.
  - `content`: Raw text/HTML/LaTeX content for the block when GLM-OCR provides it.
  - `width` / `height`: Block dimensions when present in the GLM-OCR response.
  - `raw`: Original GLM-OCR block payload for callers that need provider-specific fields.
- `tables`: Blocks whose `type` is `table`, normalized into table items.
  - `source`: Always `glm_ocr_layout`.
  - `title`: Best-effort table title derived from the table content.
  - `markdown`: Table content from the layout block. HTML tables are preserved/normalized; empty cells are filled as `n/a` where the post-processor can detect them.
  - `description`: Empty string for this tool; table semantic description is not generated here.
  - `context`: Empty string unless future GLM output provides nearby context.
  - `block_index`: The source layout block index.
  - `bbox`: The source layout block bbox.
- `formulas`: Blocks whose `type` is `formula`, normalized into formula items.
  - `source`: Always `glm_ocr_layout`.
  - `latex`: Formula content wrapped as a display math block when needed.
  - `description`: Empty string for this tool.
  - `variables`: Empty string for this tool.
  - `context`: Empty string for this tool.
  - `block_index`: The source layout block index.
  - `bbox`: The source layout block bbox.
- `figures`: Blocks whose `type` is `image`, optionally enriched by VLM.
  - `source`: `glm_ocr_layout` when only the layout block is available; `glm_ocr_layout+vlm_ocr` when VLM matched and described the image block.
  - `caption`: Best-effort caption from GLM/VLM, or `Figure N`.
  - `type`: VLM figure type such as `schematic`, `chart`, `diagram`, `figure`, or `unknown`.
  - `description`: VLM semantic description when available. Without VLM enrichment, this is the GLM block content or empty.
  - `labels`: Visible labels returned by VLM.
  - `context`: Nearby context returned by VLM.
  - `block_index`: The source layout block index.
  - `bbox`: The source layout block bbox.
- `summary`: Layout summary.
  - `block_counts`: Count by block type.
  - `dominant_type`: `table`, `formula`, `image`, `text`, `mixed`, or `unknown`.
  - `has_text` / `has_table` / `has_formula` / `has_image`: Boolean flags derived from `blocks`.
  - `recommended_tool`: Suggested follow-up single-page tool when a more focused repair pass is useful.
- `model_calls`: Model call counts.
  - `glm_ocr`: Normally `1` when GLM-OCR is enabled.
  - `vlm_ocr`: `1` only when image blocks exist and VLM is available; otherwise `0`.
- `warnings`: Non-fatal failures such as GLM-OCR unavailability, VLM unavailability for image descriptions, or model call errors.

Important boundary: this tool does not crop images or store/upload image files. If a visual element is embedded inside a table and GLM-OCR does not emit a separate `image` block for it, it will remain part of the table/block content and will not receive a separate `figures` entry.

### `extract_page_tables`

Extracts tables only. It ignores formulas and figures even when they are visible on the same page.

This section describes the contract for the single-page repair tools only: `extract_page_tables` and table items returned by `extract_page_structured`. It does not change the task/document pipeline output schema used by `start_task`, `process_task_page`, `finalize_task`, `prepare_rag_chunks`, or standard document parsing. Task/page processing continues to publish page `render`, `rag`, `elements`, markdown, chunks, and layout structures in the legacy document pipeline shape.

Strategy:

- PDF input tries PyMuPDF native tables first.
- If native tables are unavailable, GLM-OCR is used when enabled.
- VLM-OCR is fallback when GLM-OCR is unavailable or returns no tables.
- `tableRowsContent` is always normalized publishable table rows, never raw HTML.
- Raw OCR/VLM HTML is preserved in `sourceHtml` or `rawText` for audit.
- HTML/model `rowspan` is expanded by filling covered cells with the source cell text, not `n/a`.
- HTML/model `colspan` is expanded into logical columns when possible; complex headers keep source span metadata and are marked `degraded=true` and `manualReviewRequired=true`.
- Empty cell sources are distinguished with `cell_status`: `merged_fill`, `blank_in_source`, `unreadable`, and `recognized`.
- `items[]` contains every extracted table. `tables` is an alias of `items`.
- When exactly one table is available, the first table's normalized schema is also promoted to the result top level for DocIntel compatibility.
- If local post-processing cannot reliably infer table orientation, `orientation` is `0` and `warnings` includes `orientation_defaulted_to_0`. OCR/VLM-provided `orientation` values `0/90/180/270` are preserved.

JSON result shape:

```json
{
  "tool": "extract_page_tables",
  "source": {"input_type": "pdf", "page_no": 1, "source_sha1": "..."},
  "columns": ["牌号", "热处理状态", "规格mm"],
  "normalized_rows": [["20", "正火", "≤M22"], ["20", "正火", "M24~M48"]],
  "rows": [["20", "正火", "≤M22"], ["20", "正火", "M24~M48"]],
  "source_cells": [
    {"row": 1, "col": 0, "text": "20", "rowspan": 2, "colspan": 1, "confidence": 0.98}
  ],
  "cell_status": [
    {"row": 2, "col": 0, "status": "merged_fill", "source_row": 1, "source_col": 0}
  ],
  "orientation": 0,
  "raw_html": "<table>...</table>",
  "sourceHtml": "<table>...</table>",
  "markdown": "| 牌号 | 热处理状态 | 规格mm |\n| --- | --- | --- |\n| 20 | 正火 | ≤M22 |\n| 20 | 正火 | M24~M48 |",
  "tableRowsFormat": "structured_json",
  "tableRowsContent": "{\"table_title\":\"\",\"orientation\":0,\"columns\":[\"牌号\",\"热处理状态\",\"规格mm\"],\"normalized_rows\":[[\"20\",\"正火\",\"≤M22\"],[\"20\",\"正火\",\"M24~M48\"]],\"rows\":[[\"20\",\"正火\",\"≤M22\"],[\"20\",\"正火\",\"M24~M48\"]],\"source_cells\":[{\"row\":1,\"col\":0,\"text\":\"20\",\"rowspan\":2,\"colspan\":1,\"confidence\":0.98}],\"cell_status\":[{\"row\":2,\"col\":0,\"status\":\"merged_fill\",\"source_row\":1,\"source_col\":0}],\"markdown\":\"| 牌号 | 热处理状态 | 规格mm |\\n| --- | --- | --- |\\n| 20 | 正火 | ≤M22 |\\n| 20 | 正火 | M24~M48 |\",\"degraded\":false,\"manualReviewRequired\":false,\"warnings\":[],\"reason\":\"\"}",
  "degraded": false,
  "manualReviewRequired": false,
  "reason": "",
  "items": [
    {
      "source": "pymupdf | glm_ocr | vlm_ocr",
      "title": "",
      "markdown": "",
      "description": "",
      "semanticDesc": "",
      "tableRowsFormat": "structured_json",
      "tableRowsContent": "{\"columns\":[\"牌号\",\"热处理状态\",\"规格mm\"],\"normalized_rows\":[[\"20\",\"正火\",\"≤M22\"],[\"20\",\"正火\",\"M24~M48\"]]}",
      "orientation": 0,
      "columns": ["牌号", "热处理状态", "规格mm"],
      "normalized_rows": [["20", "正火", "≤M22"], ["20", "正火", "M24~M48"]],
      "source_cells": [
        {"row": 1, "col": 0, "text": "20", "rowspan": 2, "colspan": 1, "confidence": 0.98}
      ],
      "cell_status": [
        {"row": 2, "col": 0, "status": "merged_fill", "source_row": 1, "source_col": 0}
      ],
      "raw_html": "<table>...</table>",
      "sourceHtml": "<table>...</table>",
      "rawText": "",
      "warnings": [],
      "degraded": false,
      "manualReviewRequired": false,
      "reason": "",
      "context": ""
    }
  ],
  "tables": [
    {"source": "pymupdf | glm_ocr | vlm_ocr", "columns": ["牌号", "热处理状态", "规格mm"], "normalized_rows": [["20", "正火", "≤M22"], ["20", "正火", "M24~M48"]]}
  ],
  "model_calls": {"glm_ocr": 0, "vlm_ocr": 0},
  "warnings": []
}
```

Table item field details:

- `markdown`: Backward-compatible normalized Markdown table. If the model returned HTML, this field contains the converted Markdown table, not HTML.
- `semanticDesc`: Alias of `description` for table semantics.
- `tableRowsFormat`: Requested normalized rows format.
  - `structured_json`: default. `tableRowsContent` is a JSON string that can be parsed with `JSON.parse`/`json.loads`. It contains `table_title`, `orientation`, `columns`, `normalized_rows`, `rows`, `source_cells`, `cell_status`, `markdown`, `degraded`, `manualReviewRequired`, `warnings`, and `reason`. It intentionally does not embed raw HTML.
  - `markdown`: `tableRowsContent` is a Markdown table, but normalized fields are still available on the item and, for a single table, on the result top level.
  - `csv`: `tableRowsContent` is CSV text.
  - `tsv`: `tableRowsContent` is TSV text.
- `tableRowsContent`: Publishable normalized row data. It must not contain `<table`.
- `orientation`: Detected table orientation in degrees. Expected values are `0`, `90`, `180`, or `270` when supplied by OCR/VLM output.
- `columns`: Header/logical column labels for the normalized matrix.
- `normalized_rows`: Matrix rows with consistent width. `rowspan` fill values repeat the original source text.
- `source_cells`: Traceability records with `row`, `col`, `text`, `rowspan`, `colspan`, and `confidence`.
- `cell_status`: Per-cell provenance/status records. `merged_fill` points back to `source_row` and `source_col`; true blanks use `blank_in_source`; unreadable content uses `unreadable`.
- `raw_html`: Alias of original HTML table when available.
- `sourceHtml`: Original HTML table from OCR/VLM when the model returned HTML.
- `rawText`: Original raw model text when useful for audit and different from `sourceHtml`.
- `warnings`: Item-level warnings produced by table normalization.
- `degraded` / `manualReviewRequired` / `reason`: Set when normalization may be lossy or ambiguous, especially for complex merged cells.

### `extract_page_formulas`

Extracts a formula page or local formula crop. It returns the recognized page/crop as Markdown in natural reading order and indexes the LaTeX formulas in `items`. Tables and figures are not structurally extracted by this tool.

Strategy:

- GLM-OCR is preferred for full formula-page Markdown and LaTeX normalization.
- The top-level `markdown` field preserves formula titles, surrounding explanation, `式中` variable text, and formula positions.
- `items` contains formula indexes extracted from the Markdown, with nearby description, variables, and context.
- VLM-OCR is fallback when GLM-OCR is unavailable or returns no formula Markdown.

JSON result shape:

```json
{
  "tool": "extract_page_formulas",
  "source": {"input_type": "image", "page_no": 1, "source_sha1": "..."},
  "markdown": "所需最小泄放面积按公式（B.13）计算：\n\n$$...$$\n\n式中：...",
  "items": [
    {
      "source": "glm_ocr | vlm_ocr",
      "latex": "$$...$$",
      "description": "",
      "variables": "",
      "context": ""
    }
  ],
  "model_calls": {"glm_ocr": 0, "vlm_ocr": 0},
  "warnings": []
}
```

### `extract_page_figures`

Extracts a page or local crop that contains figures/illustrations. It returns the recognized page/crop as Markdown in natural reading order and indexes figure descriptions in `items`. Tables and formulas are not structurally extracted by this tool.

Strategy:

- VLM-OCR is required for final figure semantic descriptions.
- The top-level `markdown` field preserves surrounding text, figure caption, figure position, and concise figure description.
- `items` contains figure indexes with caption, type, labels, description, and context.
- If VLM-OCR is unavailable, the tool returns empty Markdown/items and includes a warning instead of fabricating a description.

JSON result shape:

```json
{
  "tool": "extract_page_figures",
  "source": {"input_type": "image", "page_no": 1, "source_sha1": "..."},
  "markdown": "正文...\n\n## 图1 ...\n\n图像描述：...",
  "items": [
    {
      "source": "vlm_ocr",
      "caption": "",
      "type": "schematic|chart|diagram|figure|unknown",
      "description": "",
      "labels": [],
      "context": ""
    }
  ],
  "model_calls": {"glm_ocr": 0, "vlm_ocr": 0},
  "warnings": []
}
```

### `extract_page_structured`

Runs a single-page comprehensive repair pass and returns separate `tables`, `formulas`, and `figures` arrays. Use this only when the page needs a full structured补漏 pass; otherwise prefer the single-purpose tools above.

## Notes

- No MinerU runtime dependency.
- Uses Fitz for PDF text/geometry/image rendering.
- VLM config is dynamically injected by caller (`vlm_config` or `ocr_config.vlm_ocr`).
- GLM-OCR is an internal OpenAI-compatible client, not another MCP hop.
- `process_task_page` failures mark the page as `FAILED` and persist the error message.
- Via MCP Router, page-level failures are surfaced as MCP errors instead of silent success payloads.
- `get_task_status` and `finalize_task` include `failed_page_errors` so clients can show page-specific failure reasons directly.
