# PDF2MD Enhanced

Task-oriented MCP service for page-by-page PDF processing.

## Service name

`pdf2md-enhanced`

## Core tools

- `start_task`
- `process_task_page`
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

## Notes

- No MinerU runtime dependency.
- Uses Fitz for PDF text/geometry/image rendering.
- VLM config is dynamically injected by caller (`vlm_config` or `ocr_config.vlm_ocr`).
- GLM-OCR is an internal OpenAI-compatible client, not another MCP hop.
- `process_task_page` failures mark the page as `FAILED` and persist the error message.
- Via MCP Router, page-level failures are surfaced as MCP errors instead of silent success payloads.
- `get_task_status` and `finalize_task` include `failed_page_errors` so clients can show page-specific failure reasons directly.
