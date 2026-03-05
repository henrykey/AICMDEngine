# PDF2MD Enhanced - Design & Implementation Specification

## 1. Scope

- Service name: `pdf2md-enhanced`
- Positioning: task-based, page-by-page PDF understanding service
- Primary goal: produce stable per-page `render` + `rag` outputs for client-side knowledge-base construction
- Deployment: MCP server behind MCP Router (HTTP streamable transport)

This document is the implementation baseline for PDF2MD Enhanced v2.

---

## 2. Core Principles

1. Default is page-level processing
- Parse unit is always one page.
- Multi-page work is orchestration over many single-page calls.

2. Client owns merge/chunk/index by default
- MCP returns per-page atomic results.
- Client (LangChain pipeline) handles cross-page merge, chunking, embedding/vectorless indexing.

3. Server-side merge is opt-in only
- `finalize_task` default `merge_mode=none`.
- `markdown|rag|both` only when explicitly requested.

4. No MinerU in enhanced path
- Use Fitz/PyMuPDF for page reading, text layer, rendering, geometry.
- OCR/understanding by external VLM only.

5. VLM configuration is runtime injected
- Router injects provider/model/base_url/key at call time.
- No hardcoded provider binding in service.

---

## 3. End-to-End Workflow

1. `health_check`
2. `start_task`
3. loop `process_task_page` for each planned page
4. optional `retry_failed_pages`
5. `get_task_status`
6. `finalize_task` (default `none`)

Recommended production behavior:
- Persist each page result immediately when `process_task_page` returns.
- Do not wait until task end to write output files.

---

## 4. Tool Contract

## 4.1 Required tools

1. `start_task`
- Input:
  - `task_name: str`
  - `file_path: str` or `file_data: base64` (mutually exclusive)
  - `pages: list[int] | null`
  - `routing_config: object | null`
  - `vlm_defaults: object | null` (injected by Router)
- Output:
  - `task_id`, `task_name`, `total_pages`, `planned_pages`, `created_at`

2. `process_task_page`
- Input:
  - `task_id: str`
  - `page_no: int`
  - `policy: auto|force_direct|force_vlm`
  - `prev_context: object | null`
  - `vlm_config: object | null` (injected by Router)
- Output:
  - `task_id`, `page_no`
  - `page_result`
  - `next_context`
  - `vlm` (provider/model/base_url actually used)

3. `get_task_status`
- Output:
  - `state`, `completed_pages`, `failed_pages`, `pending_pages`, `progress`

4. `retry_failed_pages`

5. `finalize_task`
- Input:
  - `merge_mode: none|markdown|rag|both`
- Default:
  - `none`
- Output:
  - `summary` always
  - merged payload only if explicitly requested

6. `health_check`

## 4.2 Optional tools

- `cancel_task`
- `get_page_result`
- `list_tasks`
- `cleanup_task`

---

## 5. Page Routing Strategy

Router decides one of:
- `DIRECT`: text layer reliable, no VLM call
- `REGION_VLM`: text layer usable, VLM for structure enhancement
- `FULL_VLM`: scan-like/unreliable text, full-page VLM extraction

Signals (from Fitz):
- `text_chars`, `text_blocks`, `image_area_ratio`, `noise_ratio`, `formula_score`, `table_score`

Configurable thresholds via `routing_config`.

---

## 6. FULL_VLM Optimization (Mandatory)

Current issue in many implementations: `FULL_VLM` often does two VLM calls (markdown + structured extraction).

Target implementation:
- In `FULL_VLM`, perform **one VLM call** and return dual dataset in one strict JSON payload:

```json
{
  "render": "...markdown...",
  "rag": {
    "page_text": "...plain retrieval text...",
    "elements": [
      {
        "id": "p14_t1",
        "type": "table",
        "anchor": "表1",
        "semantic_desc": "...",
        "raw_markdown": "..."
      },
      {
        "id": "p14_f2",
        "type": "formula",
        "semantic_desc": "...",
        "latex": "..."
      }
    ]
  }
}
```

Fallback rule:
- If strict JSON parse fails, fallback to legacy split path.

Benefits:
- lower latency/cost
- stronger consistency between render/rag
- less prompt drift across calls

---

## 7. Output Normalization Rules

Applied per page before returning to client:

1. Remove wrapper fences
- Strip one outer code fence like ```` ```markdown ... ``` ````.

2. Remove noisy layout content
- Remove page number, header, footer, footnotes (including footnote index/text).
- This rule must be in prompt and can be reinforced by post-cleaning.

3. Keep content semantics
- Keep tables/formulas/figures as meaningful content.
- Do not drop section titles or standard references in body.

---

## 8. VLM Prompt Requirements

Dual-output prompt must explicitly enforce:

- Produce `render` and `rag` together in one JSON.
- Remove `页号/页眉/页脚/注脚` in both datasets.
- No base64 image output.
- Formula as LaTeX for render; semantic meaning for rag.
- Table as Markdown/HTML for render; semantic summary for rag.

---

## 9. Data Model for Next-Stage RAG

Per-page canonical record (from MCP):

```json
{
  "task_id": "task_xxx",
  "doc_id": "gb150_2024",
  "page_no": 14,
  "section_path": ["5", "5.4", "5.4.1"],
  "render": {
    "markdown": "..."
  },
  "rag": {
    "page_text": "...",
    "elements": [
      {
        "id": "p14_t1",
        "type": "table|formula|figure",
        "anchor": "表1",
        "semantic_desc": "...",
        "raw_markdown": "...",
        "latex": "...",
        "keywords": ["..."]
      }
    ]
  },
  "trace": {
    "source_page_no": 14,
    "model": "qwen...",
    "provider": "multmode"
  }
}
```

Notes:
- `chunks` are **not mandatory** in MCP output.
- `chunks` are recommended to be generated by client pipeline.

---

## 10. Responsibilities Split

MCP responsibilities:
- parse single page
- produce normalized per-page `render` + `rag`
- maintain task/page states

Client responsibilities:
- incremental persistence (append per page)
- cross-page merge
- chunking strategy
- embedding/vectorless indexing
- retrieval/rerank policy

This split is required for flexibility and avoids oversized server responses.

---

## 11. File Transport Rules

`start_task` input policy:

1. same host/shared FS:
- use `file_path`

2. docker/remote MCP cannot access host file:
- use `file_data` (base64)
- recommended optimization: send subset PDF for selected pages

---

## 12. finalize_task Policy

Default:
- `merge_mode=none`
- return summary only

Explicit modes:
- `markdown`: include merged markdown
- `rag`: include merged rag
- `both`: include both

Warning:
- `markdown/rag/both` can create large payloads and may hit transport limits.

---

## 13. Observability & Error Handling

Required logs:
- task create/start/end
- page decision mode
- per-page latency
- VLM used (`provider/model/base_url` masked key)

Retry policy:
- retryable: timeout, 429, transient 5xx
- non-retryable: schema errors, invalid credentials, page out of range

Page timeout:
- enforce page-level timeout and mark page failed deterministically

---

## 14. Implementation Checklist

1. Prompt layer
- [x] update dual-output prompt with header/footer/page-number/footnote removal
- [x] enforce strict JSON output

2. FULL_VLM execution
- [x] implement one-call dual-output method
- [x] keep fallback for parse failure

3. Result schema
- [ ] align per-page result with canonical record
- [ ] include `trace` and stable element ids

4. finalize behavior
- [ ] keep `merge_mode=none` default
- [ ] avoid large payload by default

5. Client integration
- [ ] append-per-page persistence in test/client scripts
- [ ] client-side chunk/index pipeline (LangChain)

6. Documentation
- [ ] keep client guide synchronized with this design

---

## 15. Acceptance Criteria

1. For multi-page run, client receives and persists each page result incrementally.
2. `merge_mode=none` completes without large payload transfer.
3. FULL_VLM uses one VLM call for dual output in normal path.
4. Output no longer contains page number/header/footer/footnote in render/rag.
5. RAG elements are semantically usable for downstream chunking/indexing.
