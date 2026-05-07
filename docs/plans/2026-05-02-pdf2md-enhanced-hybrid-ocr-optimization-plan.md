# PDF2MD Enhanced Hybrid OCR Optimization Plan

Date: 2026-05-02

## Background

PDF2MD Enhanced is currently the main PDF extraction service used by Membership DocIntel. It already supports page-level processing, text-layer quality checks, VLM fallback, S3 remote source loading, page result persistence, and retry/resume flows.

The current routing strategy is still too coarse for technical standards documents:

- If a page has a reliable text layer, it may choose `text_layer` and skip visual understanding.
- This preserves text well, but can miss figure semantics, formula LaTeX normalization, and table structure.
- If a page is forced to VLM, quality can improve for visual content, but cost and latency are higher.
- A local or online GLM-OCR-compatible endpoint can lower cost for OCR, tables, and formulas, but it cannot reliably perform "look at the diagram and explain it" semantic figure understanding.

The target is to keep PDF2MD Enhanced as the single main MCP service and add a capability-based hybrid extraction strategy inside it.

## Goals

1. Keep the existing PDF2MD Enhanced MCP interface and task lifecycle.
2. Preserve the existing text-layer-first behavior for pure text pages.
3. Add optional GLM-OCR support for OCR, table extraction, and formula LaTeX extraction.
4. Keep VLM-OCR as the mandatory semantic fallback for figures and complex visual pages.
5. Generate RAG-friendly structured elements for tables, formulas, and figures.
6. Avoid adding another MCP hop for GLM-OCR; it should be an internal client of PDF2MD Enhanced.
7. Allow runtime enable/disable of GLM-OCR and VLM-OCR through injected config, not hardcoded environment variables.

## Non-Goals

1. Do not replace PDF2MD Enhanced with PDF2MDGLMEnhanced.
2. Do not reuse the task/server layer from PDF2MDGLMEnhanced.
3. Do not require local GLM-OCR. It is optional.
4. Do not force VLM on every page.
5. Do not generate speculative semantic explanations for tables/formulas when source context is enough.
6. Do not depend on file path sharing between Membership and MCP services.

## Capability Model

The extraction service should expose three internal capability layers:

```text
text_layer
glm_ocr
vlm_ocr
```

### text_layer

Source:

- PyMuPDF text layer extraction.
- PyMuPDF table detection where available.
- Existing PDF2MD Enhanced bad-text, blank-page, and quality checks.

Responsibilities:

- Fast and stable body text extraction.
- Basic native table extraction through `page.find_tables()`.
- Context extraction around tables/formulas, such as headings, table titles, and "式中" variable descriptions.

Limitations:

- Does not describe figures.
- Does not reliably LaTeX-normalize formulas.
- Does not handle scanned pages.

### glm_ocr

Source:

- OpenAI-compatible OCR/layout endpoint.
- Can point to local Ollama-hosted GLM-OCR, online GLM-OCR, or any compatible endpoint.

Responsibilities:

- OCR for scanned or bad-text pages.
- Table structure extraction.
- Formula OCR and LaTeX extraction.
- Low-cost first attempt for structured visual elements.

Limitations:

- Not suitable for semantic "look at the figure and explain it" tasks.
- Figure outputs should be treated only as layout/caption hints unless proven otherwise.

### vlm_ocr

Source:

- Existing dynamic VLM client or another OpenAI-compatible vision model.

Responsibilities:

- Semantic figure description.
- Technical diagram interpretation.
- Complex visual page fallback.
- Final fallback when text layer and GLM-OCR are insufficient.

Limitations:

- Higher cost and latency.
- Full-page VLM may introduce hallucination risk if prompts are not constrained.

## Routing Modes

The service should move from the current `DIRECT / REGION_VLM / FULL_VLM` mental model to explicit capability modes:

```text
text_only
hybrid_glm_ocr
hybrid_vlm_ocr
full_glm_ocr
full_vlm_ocr
blank
```

### text_only

Use when:

- Text layer is reliable.
- No meaningful visual content is detected.
- No formula/table complexity requires OCR help.

Processing:

- Extract text via text layer.
- Extract native tables if found.
- Do not call GLM-OCR or VLM-OCR.

### hybrid_glm_ocr

Use when:

- Text layer is reliable enough for body text.
- Page has table/formula indicators.
- Page has visual content that is not primarily a semantic figure, or GLM-OCR is useful as a first structured extraction pass.
- `glm_ocr.enabled = true`.

Processing:

- Body text from text layer.
- Tables/formulas from GLM-OCR.
- Simple semantic summaries from source context, not model speculation.
- If GLM-OCR fails or returns insufficient structured data, fallback to `hybrid_vlm_ocr`.

### hybrid_vlm_ocr

Use when:

- Text layer is reliable enough for body text.
- Page has figures, technical diagrams, or GLM-OCR could not produce sufficient table/formula output.
- Figure semantic description is required.

Processing:

- Body text from text layer.
- Figure descriptions from VLM-OCR.
- Table/formula fallback from VLM-OCR only where GLM-OCR or native extraction failed.

### full_glm_ocr

Use when:

- Text layer is missing, near-empty, or bad.
- Page appears scanned.
- Page is mostly OCR-able text/table/formula content.
- `glm_ocr.enabled = true`.

Processing:

- Full page through GLM-OCR.
- Normalize markdown and layout elements.
- If output is empty, invalid, or misses obvious visual content, fallback to `full_vlm_ocr`.

### full_vlm_ocr

Use when:

- Text layer is unusable and GLM-OCR is disabled or failed.
- Page is visual-heavy with required figure semantics.
- Final extraction fallback is needed.

Processing:

- Full page through VLM-OCR.
- Return render markdown and RAG elements.

### blank

Use when:

- Visual blank-page detection confirms the page is blank.

Processing:

- Produce an empty page placeholder result.
- Mark the page completed.
- Do not add it to failed pages.

## Decision Signals

Reuse and extend the current PDF2MD Enhanced page metrics:

- `text_chars`
- `text_blocks`
- `image_area_ratio`
- `drawing_density`
- `non_text_blocks`
- `visual_content_detected`
- `formula_score`
- `table_score`
- `native_table_count`
- `noise_ratio`
- `cjk_ratio`
- `ascii_symbol_ratio`
- `long_symbol_runs`
- `missing_unicode_mapping`
- blank-page visual metrics

Add derived signals:

- `has_meaningful_figures`
- `needs_formula_latex`
- `needs_table_structure`
- `text_layer_reliable`
- `text_layer_bad`
- `glm_ocr_available`
- `vlm_ocr_available`

## Routing Sketch

```text
if blank_page:
    blank

elif text_layer_bad or scanned_or_near_empty_with_visual_content:
    if glm_ocr.enabled:
        full_glm_ocr -> full_vlm_ocr fallback
    else:
        full_vlm_ocr

elif text_layer_reliable:
    if has_meaningful_figures:
        hybrid_vlm_ocr
    elif needs_formula_latex or needs_table_structure:
        if glm_ocr.enabled:
            hybrid_glm_ocr -> hybrid_vlm_ocr fallback
        else:
            hybrid_vlm_ocr
    else:
        text_only

else:
    full_vlm_ocr
```

## Runtime Configuration

Configuration must be injected by the caller at runtime. Do not require global environment variables for normal operation.

Suggested config shape:

```json
{
  "ocr_config": {
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
  },
  "routing": {
    "hybrid_ocr_enabled": true,
    "glm_ocr_enabled": true,
    "vlm_ocr_enabled": true,
    "full_vlm_fallback_enabled": true,
    "figure_semantic_description_required": true
  }
}
```

Notes:

- `glm_ocr` and `vlm_ocr` are capability names, not deployment location names.
- Local Ollama, local OpenAI-compatible servers, and online APIs should all use the same client abstraction.
- Disabling `glm_ocr` should preserve the current text-layer/VLM behavior.
- Disabling `vlm_ocr` is allowed, but pages that need figure semantics should be marked as semantically incomplete rather than silently treated as complete.

## Output Schema

Page output should make extraction source explicit.

```json
{
  "route_selected": "text_only | hybrid_glm_ocr | hybrid_vlm_ocr | full_glm_ocr | full_vlm_ocr | blank",
  "render": {
    "markdown": "..."
  },
  "rag": {
    "page_text": "...",
    "content": "...",
    "elements": {
      "tables": [],
      "formulas": [],
      "figures": []
    }
  },
  "elements": {
    "tables": [
      {
        "source": "pymupdf | glm_ocr | vlm_ocr",
        "title": "...",
        "markdown": "...",
        "semantic_summary": "...",
        "context": "..."
      }
    ],
    "formulas": [
      {
        "source": "glm_ocr | vlm_ocr",
        "latex": "...",
        "semantic_summary": "...",
        "variables": "...",
        "context": "..."
      }
    ],
    "figures": [
      {
        "source": "vlm_ocr",
        "type": "schematic | chart | diagram | figure | unknown",
        "caption": "...",
        "description": "...",
        "labels": [],
        "semantic_summary": "...",
        "context": "..."
      }
    ]
  }
}
```

## Simple Semantic Description Rules

Do not add a general LLM semantic generation step for tables/formulas in the first implementation. Use deterministic context extraction.

### Table semantic summary

Priority:

1. Table title near the table.
2. 1-3 preceding explanation lines.
3. Header fields.
4. Conservative generated fallback:

```text
表格：{title_or_page_anchor}，包含 {rows} 行、{cols} 列，字段包括 {headers}。
```

### Formula semantic summary

Priority:

1. Text immediately before the formula, such as "按下式计算".
2. "式中" variable explanation block after the formula.
3. Current section heading.
4. Conservative generated fallback:

```text
公式：位于 {section_or_page}，变量说明见原文。
```

### Figure semantic summary

Rules:

- Must come from `vlm_ocr`.
- GLM-OCR may provide bbox or caption hints, but not final semantic description.
- If VLM-OCR is disabled or fails, mark the figure as needing semantic extraction rather than fabricating a description.

## Implementation Plan

### Phase 1: Internal OCR Client Abstraction

Add internal modules under `mcp/servers/PDF2MDEnhanced`:

```text
ocr_clients/
  openai_compatible_ocr_client.py
  ocr_models.py
  ocr_normalizers.py
```

Responsibilities:

- Call OpenAI-compatible image endpoints.
- Support GLM-OCR layout parsing response normalization.
- Support VLM JSON prompt response normalization.
- Return a common `OcrResult`.

### Phase 2: Routing Refactor

Update page routing in `page_processor.py`:

- Keep existing metrics.
- Introduce explicit route names.
- Keep backward-compatible `decision.mode` where needed.
- Add log fields:
  - `sourcePageNo`
  - `routeSelected`
  - `textLayerReliable`
  - `visualContentDetected`
  - `engineSelected`
  - `fallbackReason`

### Phase 3: Hybrid Extraction Merge

Implement merge logic:

- Text layer body remains authoritative when reliable.
- Native PyMuPDF tables are preferred when usable.
- GLM-OCR fills table/formula elements.
- VLM-OCR fills figure semantics and final fallback elements.
- RAG content combines:
  - body text
  - table summaries
  - formula summaries
  - figure semantic descriptions

### Phase 4: Fallback and Incomplete Semantics

Add explicit incomplete flags:

```json
{
  "semantic_status": {
    "complete": false,
    "missing": ["figure_description"],
    "reason": "vlm_ocr_disabled"
  }
}
```

This prevents silently indexing pages as complete when required visual semantics are missing.

### Phase 5: Membership Integration

Membership should continue calling PDF2MD Enhanced the same way, but can inject:

- `ocr_config.glm_ocr`
- `ocr_config.vlm_ocr`
- routing flags

No extra MCP service call is required for GLM-OCR.

### Phase 6: Tests

Create targeted tests:

1. Pure text page chooses `text_only`.
2. Text page with formula chooses `hybrid_glm_ocr` when GLM-OCR is enabled.
3. Text page with figure chooses `hybrid_vlm_ocr`.
4. Scanned text page chooses `full_glm_ocr` then falls back to `full_vlm_ocr` on failure.
5. Blank page produces a completed placeholder result.
6. GLM-OCR disabled preserves text-layer/VLM behavior.
7. VLM-OCR disabled marks missing figure semantics as incomplete.
8. Table semantic summary is generated from title/header/context without model speculation.
9. Formula semantic summary is generated from neighboring text and "式中" blocks.

## Validation Dataset

Use a small page-level validation set:

- Pure text standard page.
- Standard page with formula and "式中" block.
- Standard page with native table.
- Standard page with large table.
- Standard page with engineering figure.
- Scanned page.
- Blank page.
- Bad text layer page with missing Unicode mapping.

For each page, record:

- selected route
- model calls
- extracted markdown length
- table count
- formula count
- figure count
- semantic completeness
- processing time
- fallback reason, if any

## Acceptance Criteria

1. Existing PDF2MD Enhanced text-only behavior remains unchanged when OCR config is disabled.
2. Pure text pages do not call GLM-OCR or VLM-OCR.
3. Formula pages produce LaTeX when GLM-OCR is enabled.
4. Table pages produce structured tables or conservative table placeholders.
5. Figure pages produce VLM-generated semantic descriptions when VLM-OCR is enabled.
6. If figure semantics are required but unavailable, the page is marked incomplete rather than failed or silently complete.
7. Blank pages are completed with empty placeholders, not failed.
8. Failed GLM-OCR calls fallback to VLM-OCR when enabled.
9. Logs clearly show page number, route, selected engine, and fallback reason.
10. The MCP interface remains compatible with the current Membership PDF extraction workflow.

## Open Questions

1. What exact OpenAI-compatible request shape does the local Ollama-hosted GLM-OCR endpoint require?
2. Does local GLM-OCR expose a `layout_parsing` endpoint or only chat/completions style vision inference?
3. Should large tables be fully indexed, summarized, or stored separately with placeholders?
4. Should semantic incompleteness block chunk/embedding, or be indexed with a warning flag?
5. Should VLM figure description use surrounding text context from the text layer in the prompt?

## Recommended Next Step

Before implementation, run a page-level proof test against the local GLM-OCR endpoint:

1. One formula page.
2. One native table page.
3. One large table page.
4. One figure page.

The goal is not full integration yet. The goal is to confirm the local GLM-OCR response shape and decide how much of it can be normalized directly into PDF2MD Enhanced `elements`.
