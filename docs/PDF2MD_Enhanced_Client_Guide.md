# PDF2MD Enhanced - Client Integration Guide

## 1. Audience and Scope

This guide is for client-side developers integrating **`pdf2md-enhanced`** via MCP Router.

It focuses on:
- Task lifecycle
- Single-page processing calls
- Resume/retry patterns
- Dynamic VLM injection
- Production-safe usage patterns

---

## 2. Service Basics

- MCP service name: `pdf2md-enhanced`
- Core pattern: **task-based + page-based processing**
- No MinerU dependency in this service path
- VLM config is injected at runtime by MCP Router (from configured LLM provider)

## 2.1 Default Contract (Important)

To avoid large payload failures and ambiguity, default client behavior is:

1. Use `start_task` + per-page `process_task_page`
2. Keep `merge_mode=none` in `finalize_task` by default
3. Client owns md/rag concatenation and persistence
4. Only enable server-side merge (`markdown`/`rag`/`both`) when explicitly needed

This service is designed for **small per-page responses**, not large single finalize payloads.

---

## 3. Tool Overview

Required tools:
1. `start_task`
2. `process_task_page`
3. `finalize_task`
4. `get_task_status`
5. `retry_failed_pages`
6. `health_check`

Optional tools (if enabled):
1. `cancel_task`
2. `get_page_result`
3. `list_tasks`
4. `cleanup_task`

---

## 4. End-to-End Call Flow

## 4.1 Recommended sequence

1. `health_check`
2. `start_task`
3. loop `process_task_page` for each page
4. if any failed pages -> `retry_failed_pages`
5. `finalize_task`
6. optional `cleanup_task`

## 4.2 Minimal sequence diagram

```text
Client
  -> health_check
  -> start_task
  -> process_task_page(page=1)
  -> process_task_page(page=2)
  -> ...
  -> get_task_status
  -> finalize_task
```

## 4.3 Multi-page Mechanism (Important)

For multi-page documents, processing is still page-serial at task level:

1. Create one task (`start_task`) with target page list/range
2. Execute `process_task_page` **page by page** (recommended in order)
3. Persist each page result immediately (append mode)
4. Build merged outputs and indexes on client side

Notes:
- The service is task-based orchestration over single-page execution, not one-shot full-document parsing.
- Ordered processing is strongly recommended for better cross-page context continuity.

---

## 5. Dynamic VLM Injection

## 5.1 Why this matters

You can switch model/provider at runtime in MCP Router without server redeploy.

## 5.2 Router-managed injection (recommended)

Recommended: do not send `vlm_config` in client tool args.
Set MCP server -> LLM provider binding in MCP Management UI (or related API), then Router injects:
- `start_task.vlm_defaults`
- `process_task_page.vlm_config`

Use explicit `vlm_config` in request only for temporary debugging overrides.

## 5.3 `vlm_config` example (debug override only)

```json
{
  "provider": "gpt-4o",
  "model": "gpt-4o",
  "api_key": "sk-...",
  "base_url": "https://api.openai.com/v1",
  "timeout_sec": 60,
  "max_retries": 2,
  "temperature": 0.1
}
```

## 5.4 Priority rules

1. `process_task_page.vlm_config`
2. `start_task.vlm_defaults`
3. service fallback defaults (local debug only)

---

## 6. API Usage Examples

All examples assume your client calls MCP Router tool execution endpoint.

## 6.1 Start task

Request payload (tool args):

```json
{
  "task_name": "gb151-run-20260304",
  "file_path": "/data/input/GB151-2020.pdf",
  "pages": [1,2,3,4,5],
  "routing_config": {
    "text_chars_min": 80,
    "image_area_ratio_full_vlm": 0.55,
    "noise_ratio_full_vlm": 0.30
  }
}
```

If MCP runs in Docker/remote and cannot access host file path, use `file_data` instead of `file_path`.

Expected response:

```json
{
  "task_id": "task_01J...",
  "total_pages": 5,
  "planned_pages": [1,2,3,4,5],
  "created_at": "2026-03-04T10:30:00+08:00"
}
```

## 6.2 Process one page

```json
{
  "task_id": "task_01J...",
  "page_no": 3,
  "policy": "auto",
  "prev_context": {
    "current_section": "5.2",
    "open_table": null,
    "carry_over_text": "..."
  }
}
```

Expected response (simplified):

```json
{
  "task_id": "task_01J...",
  "page_no": 3,
  "decision": {
    "mode": "REGION_VLM",
    "reasons": ["table_score_high"],
    "metrics": {
      "text_chars": 1240,
      "image_area_ratio": 0.18,
      "noise_ratio": 0.05
    },
    "vlm_calls": 1
  },
  "render": {"markdown": "..."},
  "rag": {"content": "...", "chunks": [], "elements": []},
  "elements": {"tables": [], "formulas": [], "figures": []},
  "next_context": {"current_section": "5.3"}
}
```

## 6.3 Finalize task

```json
{
  "task_id": "task_01J...",
  "merge_mode": "none"
}
```

Default (`none`) returns summary/page stats only.
Use `markdown`/`rag`/`both` only when you intentionally need server-side merged content.

## 6.4 Required client-side post-processing

When `merge_mode=none` (default), client must handle:

1. Per-page persistence
- Save each page result right after `process_task_page` returns.
- Do not wait for whole task completion.

2. Merge strategy
- Build merged markdown from page `render.markdown` in page order.
- Build merged rag from page `rag` objects in page order.

3. Index construction (RAG)
- Build retrieval units using page-level `rag.page_text` + `rag.elements[*].semantic_desc`.
- Keep page/section trace fields (`page_no`, `section_path`, `element_id`) for source attribution.
- Chunking/vectorization/vectorless indexing should be done in client pipeline (e.g., LangChain).

---

## 7. Client State Management

## 7.1 Must store locally

For each task/page, client should persist:
1. `task_id`
2. `planned_pages`
3. `completed_pages`
4. `failed_pages`
5. latest `next_context` per page
6. `config_hash` (optional, for idempotency)

## 7.2 Resume after interruption

After reconnect/restart:
1. call `get_task_status(task_id)`
2. compute remaining pages
3. continue `process_task_page` from pending/failed pages
4. call `retry_failed_pages` if needed

---

## 8. Parallelism Strategy

## 8.1 Safe parallel pattern

- Process pages in small batches (e.g., 3-10 pages concurrently)
- Keep `task_id` constant
- Use independent `prev_context` chains if strict continuity is not required

## 8.2 When strict continuity matters

For legal/standard docs with cross-page tables/sections:
- process pages sequentially
- pass previous page `next_context` into next page `prev_context`

---

## 9. Error Handling Contract

## 9.1 Common error classes

1. Input errors
- invalid page number
- missing file
- invalid base64

2. VLM errors
- auth failure (401/403)
- rate limit (429)
- timeout
- malformed JSON output from VLM

3. Task errors
- unknown task_id
- task already finalized/cancelled

## 9.2 Retry policy recommendation

1. Retryable:
- timeout
- transient 5xx
- rate limit (with backoff)

2. Non-retryable:
- bad request schema
- invalid credentials
- page out of range

Backoff suggestion:
- exponential: 1s, 2s, 4s (max 3 retries)

---

## 10. Performance Recommendations

1. For digital-text PDFs:
- keep `policy=auto`
- rely on router decision to stay in `DIRECT` mode when possible

2. For scanned PDFs:
- allow `FULL_VLM` routing
- reduce parallelism to avoid VLM saturation

3. For huge PDFs (500+ pages):
- page-batch processing
- incremental persistence of page outputs
- periodic status checks
- client-side incremental index build (avoid full-doc in-memory merge)

---

## 11. Security Guidelines

1. Never log plaintext `api_key`
2. Avoid persisting full `vlm_config` in client logs
3. If needed, store only provider/model/base_url and key fingerprint
4. Use short-lived credentials where possible

---

## 12. Example Client Pseudocode

```python
# 1) start
resp = call_tool("start_task", {...})
task_id = resp["task_id"]

context = None
for page in planned_pages:
    page_resp = call_tool("process_task_page", {
        "task_id": task_id,
        "page_no": page,
        "policy": "auto",
        "prev_context": context,
    })

    save_page_result(task_id, page, page_resp)
    context = page_resp.get("next_context")

# 2) finalize
final = call_tool("finalize_task", {
    "task_id": task_id,
    "merge_mode": "none"
})
```

---

## 13. Migration Notes (from legacy PDF2MD)

1. Do not assume old tool names (`process_pdf_document` etc.)
2. Integrate with task-oriented tools only
3. Stop relying on MinerU-related environment settings
4. Move model control to per-request dynamic injection

---

## 14. Acceptance Checklist for Client Integration

1. Can start task and receive valid `task_id`
2. Can process a single page end-to-end
3. Can process multi-page task with resume
4. Can switch VLM model/provider without server code change
5. Can finalize with `merge_mode=none` and complete client-side merge
6. Can explicitly enable `markdown`/`rag`/`both` merge when required
7. Can handle retries and partial failures safely
8. Can build client-side retrieval index from per-page rag outputs

---

## 15. DocIntel Process Monitor Alignment

The current DocIntel UI `Process Monitor` renders task cards using a fixed status/progress contract.
For smooth integration, `pdf2md-enhanced` should expose compatible fields.

## 15.1 UI implementation references

- `src/components/ProcessingMonitor.jsx`
- `src/hooks/useProcessingTasks.js`
- `src/hooks/useWebSocketProgress.js`
- `src/services/api.js`

## 15.2 Expected task fields (UI-facing)

Each task item should include:

- `_id`: task/document identifier
- `content_title`: display title
- `file_type`: inferred or provided type
- `uploaded_by_name`
- `status`
- `progress` (0-100)
- `file_size`
- `uploaded_at`
- `error_message` (for failed tasks)
- `ocrProgress` (optional detail for extracting stage)

## 15.3 Status values currently recognized by UI

- `QUEUED`
- `UPLOADED`
- `EXTRACTING`
- `CHUNKING`
- `EMBEDDING`
- `INDEXING`
- `COMPLETED`
- `ERROR`
- `FAILED`
- `UPLOADING` (upload pipeline events)

## 15.4 Progress mapping in current UI

If `ocrProgress.progressPercentage` exists, UI uses it directly.
Otherwise UI fallback mapping is:

- `QUEUED`: 0
- `UPLOADED`: 10
- `EXTRACTING`: 30
- `CHUNKING`: 50
- `EMBEDDING`: 70
- `INDEXING`: 90
- `COMPLETED`: 100
- `ERROR`/`FAILED`: 0

Recommendation:
- Return explicit `progress` from backend whenever possible.
- During page processing, set `status=EXTRACTING` and provide detailed `ocrProgress`.

## 15.5 OCR detail object used by monitor card

When `status=EXTRACTING`, monitor expects:

```json
{
  "ocrProgress": {
    "totalPages": 120,
    "completedPages": 37,
    "progressPercentage": 30.8,
    "estimatedRemainingSeconds": 420,
    "failedPages": [9, 23]
  }
}
```

## 15.6 WebSocket event compatibility

Current monitor hook handles these events:

- `connected` / `disconnected` / `error`
- `task.update`
- `task.batch_update`
- `UPLOAD_PROGRESS`
- `UPLOAD_COMPLETE`
- `UPLOAD_ERROR`

For `pdf2md-enhanced`, if WebSocket push is provided, prefer:

- `task.update` for per-task/per-page updates
- `task.batch_update` for burst sync

## 15.7 REST endpoints used by monitor today

Current UI fetches and actions use:

- `GET /documents`
- `GET /documents/{id}/status`
- `POST /processing/tasks/{taskId}/retry`
- `DELETE /processing/tasks/{taskId}`
- `DELETE /processing/tasks/completed`

If `pdf2md-enhanced` has a different API namespace, add a lightweight adapter layer in `documentApi`
or expose compatibility endpoints to avoid UI refactor.
