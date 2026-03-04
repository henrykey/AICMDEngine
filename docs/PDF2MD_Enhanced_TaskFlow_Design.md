# PDF2MD TaskFlow - Enhanced Design Specification

## 1. Naming and Positioning

- Product name: **PDF2MD TaskFlow**
- MCP service name: **`pdf2md-enhanced`**
- Positioning: task-oriented, page-by-page PDF understanding service for DocIntel, with resumable processing and dynamic VLM injection.

This replaces the previous "lite" direction and aligns with the requirement of an **enhanced** PDF2MD architecture.

---

## 2. Background and Problem Statement

Current PDF2MD logic is mixed:
- Multiple pathways (legacy + v2 tools)
- MinerU and Fitz paths coexist with inconsistent behavior
- Scan/text decision is too coarse in some branches
- Task identity and cross-page continuity are weak for large documents and multi-client concurrency

DocIntel PaddleOCR already uses task-based resumable processing. PDF2MD should follow the same operational pattern.

---

## 3. Core Requirements

## 3.1 Functional Requirements

1. **Single-page processing as core unit**
- Every actual parse operation is page-scoped.
- Supports one page at a time or many pages through task orchestration.

2. **Task concept (mandatory)**
- Client starts a task with name and page range/list.
- Pages are processed independently but linked by task context.
- Must support checkpoint/resume and retry by page.

3. **No MinerU dependency in new service**
- Remove MinerU from the new service execution path.
- Keep Fitz/PyMuPDF for PDF reading, text-layer extraction, rendering, geometry.
- OCR/semantic extraction depends on external VLM only when needed.

4. **Dynamic VLM configuration injection (mandatory)**
- VLM config provided by caller per request/task.
- No fixed provider/model/api key hardcoded in service runtime.
- Supports OpenAI-compatible providers (Qwen, GPT-4o, GLM-4V, etc.).

5. **Cross-page RAG continuity**
- Return per-page RAG and Markdown.
- Keep/return task context for chapter/table/formula continuation across pages.

6. **Large PDF support**
- Page-level idempotency
- Partial completion
- Resume after interruption
- Memory-safe streaming/persisting of page results

## 3.2 Non-Functional Requirements

1. **Docker-first deployment**
- Single container deployable service
- Stateless mode by default; optional external state backend

2. **Concurrency safety**
- Multiple tasks from multiple clients must be isolated
- Task ID used as namespace for state, cache, and logs

3. **Observability**
- Page-level metrics and routing decisions must be returned and logged
- Each page result includes decision details (`DIRECT`, `REGION_VLM`, `FULL_VLM`)

4. **Deterministic behavior**
- Same input page + same config => same result (best effort)
- Controlled retries and timeout policies

---

## 4. High-Level Architecture

```text
Client (DocIntel)
  -> MCP Router
    -> pdf2md-enhanced MCP service
       - task manager
       - page router (direct vs vlm)
       - page processor
       - optional state store (redis/sqlite)
       - result store (filesystem/object storage)
```

Key principle:
- **Direct text extraction first** for digital-text pages
- **VLM only when needed** (scan page or region enhancement)

---

## 5. MCP Tool Contract

## 5.1 Required Tools

1. `start_task`
- Input:
  - `task_name: str`
  - `file_path: str` OR `file_data: base64`
  - `pages: list[int] | null`
  - `routing_config: object | null`
  - `vlm_defaults: object | null` (optional defaults, can still be overridden per page)
- Output:
  - `task_id`
  - `total_pages`
  - `planned_pages`
  - `created_at`

2. `process_task_page`
- Input:
  - `task_id: str`
  - `page_no: int`
  - `vlm_config: object` (dynamic injected; required unless policy=force_direct)
  - `policy: "auto" | "force_direct" | "force_vlm"`
  - `prev_context: object | null`
- Output:
  - `page_result`
  - `next_context`
  - `decision`
  - `metrics`

3. `finalize_task`
- Input:
  - `task_id: str`
  - `merge_mode: "none" | "markdown" | "rag" | "both"`
- Output:
  - `summary`
  - `merged_markdown` (optional)
  - `merged_rag` (optional)
  - `page_stats`

4. `get_task_status`
- Input: `task_id`
- Output:
  - `state`
  - `completed_pages`
  - `failed_pages`
  - `pending_pages`
  - `progress`

5. `retry_failed_pages`
- Input: `task_id`, `pages | null`
- Output: retry schedule/result

6. `health_check`
- Output: service health, backend availability, version

## 5.2 Optional Tools

1. `cancel_task`
2. `get_page_result`
3. `list_tasks`
4. `cleanup_task`

---

## 6. Page Routing Strategy (Improved)

Replace the old coarse threshold (`chars < 10`) with a metric-driven router.

## 6.1 Signals from Fitz

For each page:
- `text_chars`: non-whitespace text length
- `text_blocks`: count of text blocks
- `image_area_ratio`: total image area / page area
- `drawing_density`: vector drawing count or normalized density
- `noise_ratio`: mojibake/garbled character ratio
- `formula_score`: formula marker score (`=`, `∑`, `∫`, superscript patterns, LaTeX-like fragments)
- `table_score`: table structure score (alignment/separators/grid hints)

## 6.2 Decision Modes

1. `DIRECT`
- Reliable text-layer page
- Use fitz text extraction and light cleanup only

2. `REGION_VLM`
- Text is usable but formulas/tables/figures need enhancement
- Extract text directly + VLM on selected regions

3. `FULL_VLM`
- Scan-like page or text-layer unusable
- Render full page image and VLM OCR/structure extraction

## 6.3 Suggested Initial Rules

- If `text_chars < 80` and `image_area_ratio > 0.55` -> `FULL_VLM`
- Else if `noise_ratio > 0.30` -> `FULL_VLM`
- Else if `formula_score >= threshold` or `table_score >= threshold` -> `REGION_VLM`
- Else -> `DIRECT`

All thresholds must be configurable via `routing_config`.

---

## 7. Dynamic VLM Injection

## 7.1 Per-page injected config

`vlm_config` schema:
- `provider`
- `model`
- `api_key`
- `base_url`
- `timeout_sec` (optional)
- `max_retries` (optional)
- `temperature` (optional)
- `extra_headers` (optional)

No persistent server-side binding to one provider/model.

## 7.2 Priority

1. `process_task_page.vlm_config`
2. `start_task.vlm_defaults`
3. service env fallback (optional, for local debugging only)

---

## 8. Task and State Model

## 8.1 Task Entity

- `task_id`
- `task_name`
- `source_ref`
- `total_pages`
- `planned_pages`
- `created_at`, `updated_at`
- `status`: `created|running|partial_failed|completed|failed|cancelled`

## 8.2 Page Entity

- `task_id`, `page_no`
- `status`: `pending|running|completed|failed`
- `decision_mode`
- `md_result`
- `rag_result`
- `elements`
- `context_out`
- `error`
- `attempts`

## 8.3 Context Entity (cross-page)

- `current_section`
- `open_table`
- `open_formula`
- `keywords_window`
- `carry_over_text`

---

## 9. Resume / Retry / Idempotency

1. `process_task_page` must be idempotent by `(task_id, page_no, config_hash)`
2. Resume should only process `pending/failed` pages
3. Retry policy:
- transient errors: bounded retries with backoff
- deterministic parsing errors: fail-fast with structured error

---

## 10. Output Schema (Per Page)

```json
{
  "task_id": "...",
  "page_no": 12,
  "decision": {
    "mode": "DIRECT|REGION_VLM|FULL_VLM",
    "reasons": ["text_chars_low", "image_ratio_high"],
    "metrics": {
      "text_chars": 34,
      "image_area_ratio": 0.73,
      "noise_ratio": 0.41,
      "formula_score": 0.12,
      "table_score": 0.08
    },
    "vlm_calls": 1
  },
  "render": {"markdown": "..."},
  "rag": {
    "content": "...",
    "chunks": [],
    "elements": []
  },
  "elements": {
    "tables": [],
    "formulas": [],
    "figures": []
  },
  "next_context": {}
}
```

---

## 11. Docker Deployment Requirements

1. Service image includes:
- Python runtime
- `pymupdf` (fitz)
- MCP runtime libraries
- OpenAI-compatible client library

2. No MinerU models or runtime required.

3. Runtime mounts:
- input directory (optional)
- output/task result directory
- optional state backend config

4. Runtime config:
- concurrency limits
- timeout defaults
- logging level

---

## 12. Compatibility with DocIntel

1. Align with PaddleOCR task-style operation:
- start task
- process page(s)
- query status
- finalize/merge

2. Frontend can treat PDF2MD TaskFlow as another task engine with page-level progress.

3. Existing multi-process orchestration can isolate by `task_id` with no cross-task contamination.

---

## 13. Security and Compliance

1. Never persist plaintext API key in task state/result logs.
2. Mask keys in logs and diagnostics.
3. Enforce max page count and max image size to prevent abuse.
4. Provide configurable redaction for sensitive output.

---

## 14. Migration Plan

1. Keep current `PDF2MD` service unchanged during migration.
2. Introduce new `pdf2md-enhanced` service in parallel.
3. A/B verify per-page outputs on representative documents.
4. Switch router binding after acceptance.
5. Deprecate legacy tools after stabilization.

---

## 15. Implementation Phases

1. Phase 1: skeleton + task tools + direct extraction path
2. Phase 2: page router + full VLM mode
3. Phase 3: region-level VLM enhancement + cross-page context
4. Phase 4: finalize/merge + retry/resume hardening + metrics
5. Phase 5: production tuning and rollout

---

## 16. Acceptance Criteria

1. Can process a 500+ page PDF via task workflow without memory explosion.
2. Resume works after interruption at arbitrary page.
3. Decision mode is explicit and traceable for every processed page.
4. VLM provider/model can be changed per request without code change.
5. No MinerU dependency in runtime path.

