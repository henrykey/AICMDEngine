# PDF2MD Enhanced

Task-oriented MCP service for page-by-page PDF processing.

## Service name

`pdf2md-enhanced`

## Core tools

- `start_task`
- `process_task_page`
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

`ocr_config` is injected by the caller at runtime. The service does not require global environment variables for normal GLM-OCR or VLM-OCR routing.

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

All four tools accept the same input shape:

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

Use exactly one of `file_path`, `file_data`, or `file_url`. For PDF input, `page_no` selects the page. For image input, the image is treated as a single page.

### `extract_page_tables`

Extracts tables only. It ignores formulas and figures even when they are visible on the same page.

Strategy:

- PDF input tries PyMuPDF native tables first.
- If native tables are unavailable, GLM-OCR is used when enabled.
- VLM-OCR is fallback when GLM-OCR is unavailable or returns no tables.

JSON result shape:

```json
{
  "tool": "extract_page_tables",
  "source": {"input_type": "pdf", "page_no": 1, "source_sha1": "..."},
  "items": [
    {
      "source": "pymupdf | glm_ocr | vlm_ocr",
      "title": "",
      "markdown": "",
      "description": "",
      "context": ""
    }
  ],
  "model_calls": {"glm_ocr": 0, "vlm_ocr": 0},
  "warnings": []
}
```

### `extract_page_formulas`

Extracts formulas only. It ignores tables and figures.

Strategy:

- GLM-OCR is preferred for LaTeX normalization.
- VLM-OCR is fallback when GLM-OCR is unavailable or returns no formulas.
- PDF text layer is used only as context for description and variable extraction.

### `extract_page_figures`

Extracts figures only and returns figure descriptions. It ignores tables and formulas.

Strategy:

- VLM-OCR is required for final figure semantic descriptions.
- If VLM-OCR is unavailable, the tool returns no figure items and includes a warning instead of fabricating a description.

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
