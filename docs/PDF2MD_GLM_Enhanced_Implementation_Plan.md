# PDF2MD GLM Enhanced - Implementation Plan

## 1. Objective

This document proposes a new PDF-to-Markdown MCP service built primarily on `glm-ocr`, while preserving the client-facing compatibility contract of `pdf2md-enhanced`.

Primary goal:
- introduce a new OCR/VLM technology path
- keep the existing task-based MCP workflow stable
- allow existing clients to switch with zero or minimal parsing changes

Compatibility baseline:
- [PDF_MCP_Compatibility_Spec.md](/Users/kehongwei/workspace/vault/AICMDEngine/PDF_MCP_Compatibility_Spec.md)
- [PDF2MD_Enhanced_Client_Guide.md](/Users/kehongwei/workspace/AICMDEngine/docs/PDF2MD_Enhanced_Client_Guide.md)
- [PDF2MD_Enhanced_TaskFlow_Design.md](/Users/kehongwei/workspace/AICMDEngine/docs/PDF2MD_Enhanced_TaskFlow_Design.md)

---

## 2. Design Positioning

This service is not a new protocol. It is a new implementation behind the same or compatible protocol boundary.

The design principle is:

1. preserve the `pdf2md-enhanced` task contract first
2. replace the internal page extraction engine second
3. normalize all outputs into the established `page_result` schema
4. keep error semantics compatible with existing MCP Router behavior

That means the project should be treated as a compatibility-preserving service variant, not as a fresh PDF MCP design.

---

## 3. Recommended Service Form

Recommended new service name:
- `pdf2md-glm-enhanced`

Recommended code location:
- `mcp/servers/PDF2MDGLMEnhanced/`

Recommended implementation strategy:
- reuse the task orchestration pattern from `PDF2MDEnhanced`
- keep the same MCP tool names
- replace only the page-processing internals and model adapter layer

Two viable deployment forms exist:

1. Standalone compatible service
- new MCP server package and Docker image
- can be registered beside `pdf2md-enhanced`
- lower migration risk

2. Engine mode inside current `pdf2md-enhanced`
- add `engine=glm_ocr` or similar internal routing
- less duplicated code
- higher coupling to current service internals

Recommendation:
- build it first as a standalone compatible service
- after the design stabilizes, consider merging engines behind one service if operationally useful

Reason:
- easier A/B comparison
- clearer rollback path
- reduced risk of destabilizing current production behavior

---

## 4. Compatibility Scope

The new service must preserve these tool names for drop-in client compatibility:

1. `start_task`
2. `process_task_page`
3. `get_task_status`
4. `retry_failed_pages`
5. `finalize_task`
6. `health_check`

Optional compatible tools:

1. `cancel_task`
2. `get_page_result`
3. `list_tasks`
4. `cleanup_task`

The following fields are contract-critical and must remain stable:

1. `start_task.task_id`
2. `start_task.total_pages`
3. `start_task.planned_pages`
4. `process_task_page.page_result`
5. `page_result.render.markdown`
6. `page_result.rag.content`
7. `page_result.rag.elements.tables|formulas|figures`
8. `page_result.elements.tables|formulas|figures`
9. `get_task_status.failed_pages`
10. `get_task_status.failed_page_errors`
11. `finalize_task.summary`
12. default `finalize_task(merge_mode=none)` summary-only behavior

Strict compatibility rules:

1. page success must return a normal success payload containing `page_result`
2. page failure must surface through MCP error semantics, not fake success JSON
3. task-level partial failures must be visible in `failed_pages` and `failed_page_errors`
4. new fields may be added, but required compatibility fields must not be removed or renamed

---

## 5. Why `glm-ocr` Is Feasible Here

`glm-ocr` is suitable if it can provide one or more of the following reliably:

1. page-level markdown extraction
2. page-level body text extraction
3. table / formula / figure recognition or description
4. predictable failure signaling on timeout, quota, malformed input, and page-level processing exceptions

The compatibility layer does not require `glm-ocr` to natively emit the exact `pdf2md-enhanced` schema.
It only requires that we can map `glm-ocr` outputs into that schema.

This is the key implementation idea:

- `glm-ocr` is the extraction engine
- `PDF2MDGLMEnhanced` is the compatibility and orchestration layer

---

## 6. High-Level Architecture

```text
MCP Router
  -> pdf2md-glm-enhanced MCP server
    -> task manager
    -> page processor
      -> page renderer (PyMuPDF / Fitz)
      -> direct text extractor
      -> glm-ocr adapter
      -> optional structure enhancer
      -> output normalizer
    -> task finalizer
```

Main modules:

1. `server.py`
- exposes MCP tools
- keeps tool signatures aligned with `pdf2md-enhanced`

2. `task_manager.py`
- creates tasks
- tracks page status
- persists task/page outputs
- computes `failed_pages`, `failed_page_errors`, and finalize summary

3. `page_processor.py`
- orchestrates per-page extraction
- chooses extraction strategy
- merges raw extraction into normalized `page_result`

4. `glm_ocr_client.py`
- isolates all `glm-ocr` provider calls
- centralizes timeout, retries, and request/response parsing

5. `normalizers.py`
- converts raw OCR/model output into:
  - `render.markdown`
  - `rag.content`
  - `elements.tables`
  - `elements.formulas`
  - `elements.figures`

6. `routing.py`
- decides page mode
- evaluates whether to use direct extraction, region extraction, or full-page OCR

7. `models.py`
- task/page records
- shared enums or constants for page states

---

## 7. Reuse Strategy From Existing `PDF2MDEnhanced`

The following modules are strong candidates for direct reuse with minimal changes:

1. task lifecycle shape in `server.py`
2. task persistence pattern in `task_manager.py`
3. task/page record data model
4. `finalize_task` default merge behavior
5. `failed_page_errors` compatibility behavior

The following modules should be refactored or replaced:

1. `vlm_client.py`
- replace with `glm_ocr_client.py`
- optionally keep a generic adapter interface for future engines

2. `page_processor.py`
- rework extraction flow to support `glm-ocr`
- preserve normalized result shape

3. routing heuristics
- retain useful Fitz-based signals
- retune thresholds for `glm-ocr` strengths and weaknesses

Recommended approach:

- fork current `PDF2MDEnhanced`
- remove provider-specific assumptions from page processing
- convert page extraction into pluggable engine steps

---

## 8. Processing Modes

Recommended internal processing modes:

1. `DIRECT`
- use PDF text layer directly
- suitable when embedded text is high quality
- no `glm-ocr` call required

2. `REGION_GLM`
- use direct text as the primary content
- use `glm-ocr` only to extract or refine:
  - tables
  - formulas
  - figures
- useful for mixed pages with good text but weak structure

3. `FULL_GLM`
- render the page as an image
- let `glm-ocr` produce the main markdown/text result
- use for scanned pages or severely corrupted text layer

Compatibility note:
- internal mode names may differ
- outward `decision.mode` should remain compatible with existing clients

Recommended outward mapping:

1. internal `DIRECT` -> `decision.mode = "DIRECT"`
2. internal `REGION_GLM` -> `decision.mode = "REGION_VLM"`
3. internal `FULL_GLM` -> `decision.mode = "FULL_VLM"`

Reason:
- existing clients may already branch on these values
- compatibility is more important than exposing engine identity through that field

If engine transparency is still desired, add additive fields such as:

```json
{
  "decision": {
    "mode": "FULL_VLM",
    "engine": "glm_ocr",
    "engine_mode": "FULL_GLM"
  }
}
```

---

## 9. Page Routing Strategy

The service should continue to use lightweight Fitz/PyMuPDF signals before deciding whether a page needs OCR.

Recommended routing signals:

1. `text_chars`
2. `text_blocks`
3. `image_area_ratio`
4. `noise_ratio`
5. `formula_score`
6. `table_score`
7. presence of broken CID-like text
8. private-use characters or symbol-heavy garbage text

Recommended routing rules:

1. if text layer is clean and sufficient, use `DIRECT`
2. if text layer is usable but structure is poor, use `REGION_GLM`
3. if text layer is empty, garbled, scan-like, or low confidence, use `FULL_GLM`

Recommended config keys:

```json
{
  "text_chars_min": 80,
  "image_area_ratio_full_glm": 0.55,
  "noise_ratio_full_glm": 0.30,
  "formula_score_region_glm": 0.12,
  "table_score_region_glm": 0.20,
  "bad_text_policy": {
    "enabled": true,
    "fallback_action": "force_glm_for_page"
  }
}
```

---

## 10. Output Normalization Contract

All raw extraction outputs must be normalized into the same page-level response shape.

Canonical success response:

```json
{
  "task_id": "task_xxx",
  "page_no": 3,
  "page_result": {
    "decision": {
      "mode": "FULL_VLM",
      "reasons": ["bad_text_detected"],
      "metrics": {
        "text_chars": 10
      },
      "vlm_calls": 1,
      "engine": "glm_ocr",
      "engine_mode": "FULL_GLM"
    },
    "render": {
      "markdown": "..."
    },
    "rag": {
      "content": "...",
      "elements": {
        "tables": [],
        "formulas": [],
        "figures": []
      }
    },
    "elements": {
      "tables": [],
      "formulas": [],
      "figures": []
    },
    "next_context": {
      "current_section": "5.3"
    }
  },
  "next_context": {
    "current_section": "5.3"
  },
  "vlm": {
    "provider": "glm",
    "model": "glm-ocr"
  }
}
```

Normalization rules:

1. `render.markdown` must always exist, even if empty
2. `rag.content` must always exist, even if empty
3. both `rag.elements` and top-level `elements` must include:
   - `tables`
   - `formulas`
   - `figures`
4. all page outputs must be representable even if the engine only provides partial structure
5. empty arrays are preferred over omitted keys

---

## 11. Raw `glm-ocr` Result Mapping

The exact `glm-ocr` response may vary by model or gateway, but we should assume it may return one of these patterns:

1. markdown-like text only
2. OCR plain text only
3. semi-structured JSON
4. mixed markdown plus descriptions

Recommended normalization strategy:

### 11.1 If `glm-ocr` returns markdown directly

Use the markdown as:
- `render.markdown = cleaned_markdown`

Then derive:
- `rag.content` from cleaned markdown or extracted body text
- `elements` from markdown parsing and heuristics

### 11.2 If `glm-ocr` returns plain OCR text

Use:
- `render.markdown = text_to_markdown(text)`
- `rag.content = cleaned_body_text`
- `elements = []` buckets unless separately detected

### 11.3 If `glm-ocr` returns structured JSON

Map directly where possible:
- structured markdown/text -> `render.markdown`
- table/formula/figure objects -> `elements`
- body text -> `rag.content`

### 11.4 If `glm-ocr` is weak on structured elements

Use a second-stage extractor:

1. markdown parser
2. regex / heuristic formula extraction
3. markdown table parser
4. optional lightweight secondary model call for figures/tables

This second stage should be isolated behind `normalizers.py` or `structure_extractors.py`.

---

## 12. RAG Construction Strategy

The current compatibility contract expects `rag.content` and `rag.elements`, but does not require the engine to natively produce them.

Recommended strategy:

1. `rag.content`
- derive from cleaned page body text
- remove page numbers, headers, footers, and footnotes where feasible
- prefer source-like body text over summaries

2. `rag.elements.tables`
- preserve structured table representations if possible
- if only markdown tables exist, store markdown or parsed row/column objects

3. `rag.elements.formulas`
- preserve LaTeX if available
- otherwise preserve recognized expression strings

4. `rag.elements.figures`
- preserve short semantic descriptions
- if figure understanding is weak, emit conservative descriptions rather than hallucinated detail

Recommended compatibility-first rule:
- if structure confidence is low, return empty arrays rather than speculative content

---

## 13. Error Handling and Failure Semantics

This area is critical because compatibility is not just about JSON shape.

### 13.1 Page-level failure

For `process_task_page`, failures must be treated as page failures and surfaced through MCP error semantics.

Examples:

1. timeout
2. transient upstream 5xx
3. model quota/rate limiting
4. invalid OCR response format
5. page number out of range
6. invalid or unreadable file content

Required behavior:

1. persist page status as `FAILED`
2. persist page error text into task state
3. expose error cause later via `failed_page_errors`
4. surface the current page call as MCP `isError=true`

### 13.2 Task-level failure

Task-level partial failure is a business result, not a transport failure.

Required behavior:

1. `get_task_status` returns:
   - `failed_pages`
   - `failed_page_errors`

2. `finalize_task` returns:
   - `summary.failed_pages`
   - `summary.failed_page_errors`

### 13.3 Error text guidance

Error text should be explicit enough for client retry logic.

Recommended categories:

1. retryable
- timeout
- rate limit
- transient upstream 5xx
- temporary gateway failure

2. non-retryable
- bad request schema
- bad credentials
- page out of range
- invalid file data
- unknown task id

Suggested wording examples:

- `process_task_page timeout after 280s`
- `glm_ocr upstream rate limited, retry suggested`
- `page_no out of range: 12 / 10`
- `task not found: task_xxx`

---

## 14. Tool Signatures

Recommended MCP tool signatures are identical to current `pdf2md-enhanced`.

### 14.1 `health_check`

Response example:

```json
{
  "ok": true,
  "service": "pdf2md-glm-enhanced",
  "version": "0.1.0"
}
```

### 14.2 `start_task`

Inputs:

1. `task_name: str`
2. `file_path: str | null`
3. `file_data: base64 | null`
4. `pages: list[int] | null`
5. `routing_config: object | null`
6. `vlm_defaults: object | null`

Outputs:

1. `task_id`
2. `task_name`
3. `total_pages`
4. `planned_pages`
5. `created_at`

### 14.3 `process_task_page`

Inputs:

1. `task_id: str`
2. `page_no: int`
3. `vlm_config: object | null`
4. `policy: str = "auto"`
5. `prev_context: object | null`
6. `routing_config: object | null`

Outputs:

1. `task_id`
2. `page_no`
3. `page_result`
4. `next_context`
5. `vlm`

### 14.4 `get_task_status`

Outputs:

1. `task_id`
2. `state`
3. `completed_pages`
4. `failed_pages`
5. `failed_page_errors`
6. `pending_pages`
7. `progress`

### 14.5 `retry_failed_pages`

Inputs:

1. `task_id`
2. `pages: list[int] | null`

Outputs:

1. `task_id`
2. `retry_pages`
3. `count`

### 14.6 `finalize_task`

Inputs:

1. `task_id`
2. `merge_mode: none|markdown|rag|both`

Outputs:

1. `summary`
2. optional merged payloads only if explicitly requested

---

## 15. Module Design

Recommended directory layout:

```text
mcp/servers/PDF2MDGLMEnhanced/
  __main__.py
  server.py
  task_manager.py
  page_processor.py
  glm_ocr_client.py
  routing.py
  normalizers.py
  models.py
  requirements.txt
  Dockerfile
  README.md
```

### 15.1 `glm_ocr_client.py`

Responsibilities:

1. provider authentication
2. request building
3. timeout / retry handling
4. response parsing
5. returning a stable internal response object

Recommended client interface:

```python
class GLMOCRClient:
    def extract_page_markdown(self, image_path: str) -> str: ...
    def extract_page_structured(self, image_path: str) -> dict: ...
    def extract_page_dual(self, image_path: str) -> dict: ...
```

The adapter should hide provider-specific transport details from the rest of the service.

### 15.2 `page_processor.py`

Responsibilities:

1. open PDF page
2. collect routing signals
3. choose processing mode
4. call direct extractor or `glm_ocr_client`
5. normalize raw result
6. build `next_context`
7. return canonical `page_result`

### 15.3 `normalizers.py`

Responsibilities:

1. clean markdown
2. strip code fences
3. remove obvious header/footer/page number noise
4. derive `rag.content`
5. derive `elements`
6. normalize empty/malformed structures

### 15.4 `routing.py`

Responsibilities:

1. compute mode from page metrics and policy
2. detect bad text pages
3. expose decision reasons for `decision.reasons`

---

## 16. Data Persistence

Recommended persistence approach is the same as current enhanced service:

1. task metadata persisted to task directory
2. page results persisted per page
3. failure messages persisted immediately when page processing fails

Recommended output structure:

```text
<output_dir>/
  tasks/
    <task_id>/
      task.json
      page_1.json
      page_2.json
```

Benefits:

1. simple recovery and debugging
2. easy comparison with existing service
3. no database dependency for MVP

---

## 17. Implementation Phases

### Phase 1: Compatibility Skeleton

Goal:
- create the new MCP service with the same tool signatures and task state behavior

Scope:

1. copy `server.py`, `task_manager.py`, `models.py`
2. rename service to `pdf2md-glm-enhanced`
3. keep `health_check`, `start_task`, `get_task_status`, `retry_failed_pages`, `finalize_task`
4. stub `process_task_page` with a minimal fake or fallback implementation

Exit criteria:

1. all required tools are visible
2. task lifecycle works
3. JSON schema is compatible

### Phase 2: `glm-ocr` Full-Page Extraction

Goal:
- support `FULL_GLM` pages end to end

Scope:

1. render page to image
2. call `glm-ocr`
3. normalize markdown/text into `page_result`
4. support timeout/retry/error persistence

Exit criteria:

1. scanned pages can return `render.markdown`
2. failures appear in `failed_page_errors`
3. `process_task_page` failures are surfaced compatibly

### Phase 3: Direct + Hybrid Routing

Goal:
- avoid unnecessary OCR calls and improve performance

Scope:

1. enable `DIRECT`
2. enable `REGION_GLM`
3. add Fitz-based routing metrics

Exit criteria:

1. text PDFs can bypass full OCR
2. mixed pages can use hybrid flow

### Phase 4: Structure Quality Improvements

Goal:
- improve `tables`, `formulas`, and `figures`

Scope:

1. build markdown-to-elements extractor
2. improve formula normalization
3. improve table placeholder / large-table fallback
4. improve figure placeholder generation

Exit criteria:

1. `elements` quality is stable enough for KB ingestion
2. empty arrays are used when confidence is low

### Phase 5: Production Hardening

Goal:
- make the service operationally safe

Scope:

1. Docker packaging
2. router registration
3. monitoring and logging
4. retry tuning
5. timeout and payload-size tuning

Exit criteria:

1. deployable beside existing MCPs
2. safe rollback path
3. acceptable page latency and failure observability

---

## 18. Testing Strategy

Testing should be compatibility-first.

### 18.1 Contract tests

Reuse or adapt:
- [test_pdf2md_enhanced_mcp.py](/Users/kehongwei/workspace/AICMDEngine/tests/test_pdf2md_enhanced_mcp.py)

Required checks:

1. `start_task` response shape
2. `process_task_page` success payload shape
3. `get_task_status.failed_pages`
4. `get_task_status.failed_page_errors`
5. `finalize_task(merge_mode=none)` summary-only behavior

### 18.2 Page failure tests

Cases:

1. invalid page number
2. invalid task id
3. timeout
4. malformed OCR response
5. provider quota/rate limit

Expected result:

1. page marked failed
2. error message persisted
3. task status reflects failure

### 18.3 Quality regression tests

Sample document categories:

1. born-digital text PDF
2. scanned standard PDF
3. table-heavy PDF
4. formula-heavy PDF
5. mixed Chinese/English technical PDF

Evaluation dimensions:

1. markdown readability
2. body text preservation
3. table retention
4. formula retention
5. figure placeholder usefulness

---

## 19. Performance and Cost Considerations

This design should not route every page to `glm-ocr`.

Recommended cost controls:

1. keep `DIRECT` for clean text pages
2. use `REGION_GLM` for mixed pages
3. use `FULL_GLM` only when necessary
4. cap timeout, max tokens, and retry counts
5. allow client-controlled routing thresholds

Recommended future optimizations:

1. page image DPI tuning by page type
2. caching rendered page images
3. caching OCR results by page hash
4. batched processing if provider supports it

---

## 20. Main Risks and Mitigations

### Risk 1: `glm-ocr` output is good markdown but weak structure

Impact:
- `elements.tables/formulas/figures` quality may lag behind markdown quality

Mitigation:

1. derive `elements` from markdown in post-processing
2. return empty arrays when uncertain
3. add optional second-stage structure extraction

### Risk 2: page failures are not surfaced compatibly

Impact:
- clients may misread failures as successful pages

Mitigation:

1. explicitly test MCP error semantics
2. align with Router behavior, not just raw local function behavior

### Risk 3: latency too high on scanned multi-page PDFs

Impact:
- poor batch throughput

Mitigation:

1. keep `DIRECT` path
2. cap retries
3. tune render DPI
4. support retrying only failed pages

### Risk 4: markdown quality varies by document type

Impact:
- inconsistent KB ingestion quality

Mitigation:

1. build representative document benchmark set
2. compare with current `pdf2md-enhanced`
3. introduce document-type-specific routing thresholds if necessary

### Risk 5: provider lock-in at adapter layer

Impact:
- future migration cost rises

Mitigation:

1. keep `glm_ocr_client.py` behind an abstract interface
2. isolate provider-specific parsing and transport code

---

## 21. Recommended MVP Scope

The first working version should target compatibility, not perfect extraction quality.

Recommended MVP:

1. standalone `pdf2md-glm-enhanced` service
2. same six required tools
3. working task lifecycle
4. `FULL_GLM` path only
5. normalized `render.markdown`
6. basic `rag.content`
7. empty but valid `elements` buckets allowed initially
8. proper failed-page persistence and summarize behavior

Not required for MVP:

1. advanced `REGION_GLM`
2. perfect table structure
3. advanced figure understanding
4. server-side merged document outputs beyond compatibility basics

Reason:
- this gets a testable, comparable service online quickly
- it validates the most important question first: can `glm-ocr` produce useful page markdown under the compatibility contract

---

## 22. Recommendation Summary

Recommended direction:

1. implement a new standalone MCP service: `pdf2md-glm-enhanced`
2. reuse the current task-based compatibility shell from `PDF2MDEnhanced`
3. treat `glm-ocr` as an internal extraction engine, not a new outward contract
4. normalize all outputs into the existing `page_result` shape
5. prioritize compatibility tests and page-failure semantics before pursuing extraction refinements

This approach gives the best balance of:

1. low client migration cost
2. controlled engineering risk
3. fast A/B comparison with existing `pdf2md-enhanced`
4. future freedom to mix `glm-ocr` with other OCR or VLM components

---

## 23. Next Step

After this plan is accepted, the next implementation document should be a build checklist containing:

1. exact file scaffold to create
2. adapter interface definitions
3. environment variables and config keys
4. Docker and MCP Router registration changes
5. initial compatibility test checklist

---

## 24. Reference Source Files

The new implementation should explicitly reference the current `PDF2MDEnhanced` service as the compatibility baseline source code.

Primary reference files:

1. [server.py](/Users/kehongwei/workspace/AICMDEngine/mcp/servers/PDF2MDEnhanced/server.py)
- MCP tool definitions
- tool signatures
- task lifecycle entry points

2. [task_manager.py](/Users/kehongwei/workspace/AICMDEngine/mcp/servers/PDF2MDEnhanced/task_manager.py)
- task creation
- page state transitions
- `failed_page_errors`
- finalize summary behavior

3. [page_processor.py](/Users/kehongwei/workspace/AICMDEngine/mcp/servers/PDF2MDEnhanced/page_processor.py)
- page-level orchestration
- routing heuristics
- normalized `page_result` construction

4. [vlm_client.py](/Users/kehongwei/workspace/AICMDEngine/mcp/servers/PDF2MDEnhanced/vlm_client.py)
- current model-adapter responsibilities
- timeout/retry design pattern
- provider isolation boundary

5. [models.py](/Users/kehongwei/workspace/AICMDEngine/mcp/servers/PDF2MDEnhanced/models.py)
- task/page record structures
- task status computation dependencies

6. [__main__.py](/Users/kehongwei/workspace/AICMDEngine/mcp/servers/PDF2MDEnhanced/__main__.py)
- service startup pattern
- stdio / streamable-http startup alignment

7. [README.md](/Users/kehongwei/workspace/AICMDEngine/mcp/servers/PDF2MDEnhanced/README.md)
- current service positioning
- expected operational notes

Compatibility and test reference documents:

1. [PDF_MCP_Compatibility_Spec.md](/Users/kehongwei/workspace/AICMDEngine/docs/PDF_MCP_Compatibility_Spec.md)
2. [PDF2MD_Enhanced_Client_Guide.md](/Users/kehongwei/workspace/AICMDEngine/docs/PDF2MD_Enhanced_Client_Guide.md)
3. [PDF2MD_Enhanced_TaskFlow_Design.md](/Users/kehongwei/workspace/AICMDEngine/docs/PDF2MD_Enhanced_TaskFlow_Design.md)
4. [test_pdf2md_enhanced_mcp.py](/Users/kehongwei/workspace/AICMDEngine/tests/test_pdf2md_enhanced_mcp.py)

Implementation instruction:

1. treat the files above as behavior references, not copy-everything blindly guidance
2. preserve compatibility-relevant behavior first
3. replace provider-specific extraction internals second
4. if behavior differs from current implementation, the compatibility spec takes precedence

---

## 25. Suggested Initial Scaffold

If the implementation is handed to another developer, the recommended starting point is to create the following directory and files before integrating `glm-ocr`.

Suggested scaffold:

```text
mcp/servers/PDF2MDGLMEnhanced/
  __init__.py
  __main__.py
  server.py
  task_manager.py
  page_processor.py
  glm_ocr_client.py
  normalizers.py
  routing.py
  models.py
  requirements.txt
  Dockerfile
  README.md
```

Recommended initial file sourcing strategy:

1. `server.py`
- start from `PDF2MDEnhanced/server.py`
- keep the same required MCP tools
- rename service to `pdf2md-glm-enhanced`

2. `task_manager.py`
- start from `PDF2MDEnhanced/task_manager.py`
- preserve task persistence and summary behavior

3. `models.py`
- copy or adapt from `PDF2MDEnhanced/models.py`
- keep statuses and timestamps compatible with task manager expectations

4. `__main__.py`
- start from `PDF2MDEnhanced/__main__.py`
- preserve startup behavior and transport style

5. `page_processor.py`
- use `PDF2MDEnhanced/page_processor.py` as the orchestration reference
- remove current provider assumptions
- rewire extraction to `glm_ocr_client.py`

6. `glm_ocr_client.py`
- new file
- replace `vlm_client.py` responsibilities with `glm-ocr` adapter logic

7. `normalizers.py`
- new or extracted file
- centralize markdown cleanup and compatibility normalization

8. `routing.py`
- new or extracted file
- centralize route decision logic

9. `README.md`
- describe required tools
- describe env vars
- describe startup mode
- document compatibility goal explicitly

10. `requirements.txt`
- include `fastmcp`
- include `pymupdf` or existing PDF rendering dependency
- include `glm-ocr` related SDK or HTTP client dependency

Scaffold objective:

1. let the assignee start from a known-compatible shell
2. isolate the risky part to page extraction and normalization
3. avoid reinterpreting task flow from scratch

Recommended implementation order inside the scaffold:

1. make service boot and expose tools
2. make `start_task` and `get_task_status` work
3. make `process_task_page` return a minimal compatible success payload
4. connect `glm-ocr`
5. add failure persistence and finalize semantics
6. improve output quality after compatibility is stable

---

## 26. Handover Package Checklist

If this work is assigned to another developer or vendor, the handover package should contain at least the following:

1. this implementation plan
- [PDF2MD_GLM_Enhanced_Implementation_Plan.md](/Users/kehongwei/workspace/AICMDEngine/docs/PDF2MD_GLM_Enhanced_Implementation_Plan.md)

2. compatibility spec
- [PDF_MCP_Compatibility_Spec.md](/Users/kehongwei/workspace/AICMDEngine/docs/PDF_MCP_Compatibility_Spec.md)

3. current reference implementation files
- [server.py](/Users/kehongwei/workspace/AICMDEngine/mcp/servers/PDF2MDEnhanced/server.py)
- [task_manager.py](/Users/kehongwei/workspace/AICMDEngine/mcp/servers/PDF2MDEnhanced/task_manager.py)
- [page_processor.py](/Users/kehongwei/workspace/AICMDEngine/mcp/servers/PDF2MDEnhanced/page_processor.py)
- [vlm_client.py](/Users/kehongwei/workspace/AICMDEngine/mcp/servers/PDF2MDEnhanced/vlm_client.py)
- [models.py](/Users/kehongwei/workspace/AICMDEngine/mcp/servers/PDF2MDEnhanced/models.py)
- [__main__.py](/Users/kehongwei/workspace/AICMDEngine/mcp/servers/PDF2MDEnhanced/__main__.py)

4. integration and behavior references
- [PDF2MD_Enhanced_Client_Guide.md](/Users/kehongwei/workspace/AICMDEngine/docs/PDF2MD_Enhanced_Client_Guide.md)
- [PDF2MD_Enhanced_TaskFlow_Design.md](/Users/kehongwei/workspace/AICMDEngine/docs/PDF2MD_Enhanced_TaskFlow_Design.md)
- [test_pdf2md_enhanced_mcp.py](/Users/kehongwei/workspace/AICMDEngine/tests/test_pdf2md_enhanced_mcp.py)

5. explicit delivery expectations
- required tool names must remain compatible
- required response fields must remain compatible
- page failures must be visible through MCP error semantics
- task failures must be visible through `failed_pages` and `failed_page_errors`
- `finalize_task(merge_mode=none)` must remain summary-first

Optional but strongly recommended handover addition:

1. a pre-created scaffold directory under `mcp/servers/PDF2MDGLMEnhanced/`

When scaffold code is not provided, the assignee should still be instructed to create the scaffold described in Section 25 before implementing provider integration.
