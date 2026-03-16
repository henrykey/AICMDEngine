# PDF MCP Compatibility Spec

## 1. Purpose

This document defines the **client-facing response contract** for any new PDF-processing MCP service that must be compatible with **`pdf2md-enhanced`**.

Compatibility target:
- a client already integrated with `pdf2md-enhanced`
- the new service can replace `pdf2md-enhanced` without requiring client-side response parsing changes

This is a **compatibility spec**, not an implementation spec.
Internal parsing logic, model choice, OCR engine, and routing strategy may differ, but the returned result shape and failure semantics must stay compatible.

---

## 2. Compatibility Scope

To be considered compatible, a PDF MCP service must preserve:

1. Task-based workflow
- `start_task`
- `process_task_page`
- `get_task_status`
- `finalize_task`

2. Success payload shape
- especially `process_task_page.page_result`

3. Failure signaling rules
- page-level failure via MCP `isError=true`
- task-level failure details via `failed_pages` and `failed_page_errors`

4. Merge behavior
- `finalize_task(merge_mode=none)` returns summary only by default

---

## 3. Required Client Contract

Required tools:
1. `start_task`
2. `process_task_page`
3. `get_task_status`
4. `finalize_task`
5. `retry_failed_pages`
6. `health_check`

Optional tools:
1. `cancel_task`
2. `get_page_result`
3. `list_tasks`
4. `cleanup_task`

Tool names may differ only if the caller is also updated. If the goal is drop-in compatibility with existing clients, keep the same tool names.

---

## 4. Success Contract

## 4.1 `start_task`

Successful response:

```json
{
  "task_id": "task_01J...",
  "total_pages": 5,
  "planned_pages": [1, 2, 3, 4, 5],
  "created_at": "2026-03-04T10:30:00+08:00"
}
```

Required fields:
- `task_id: string`
- `total_pages: integer`
- `planned_pages: integer[]`
- `created_at: string`

Recommended fields:
- `task_name: string`

Rules:
- `task_id` must be stable across all subsequent calls for that task
- `planned_pages` must match the pages the service intends to process

## 4.2 `process_task_page`

Successful response:

```json
{
  "task_id": "task_01J...",
  "page_no": 3,
  "page_result": {
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
    "provider": "OpenAI",
    "model": "gpt-4o"
  }
}
```

Required top-level fields:
- `task_id: string`
- `page_no: integer`
- `page_result: object`

Recommended top-level fields:
- `next_context: object`
- `vlm: object`

Required `page_result` fields:
- `decision: object`
- `render: object`
- `rag: object`
- `elements: object`

Recommended `page_result` fields:
- `next_context: object`

Required `decision` fields:
- `mode: string`

Recommended `decision` fields:
- `reasons: string[]`
- `metrics: object`
- `vlm_calls: integer`

Required `render` fields:
- `markdown: string`

Required `rag` fields:
- `content: string`
- `elements: object`

Required `elements` container keys:
- `tables: array`
- `formulas: array`
- `figures: array`

Rules:
- success must always include `page_result`
- `render.markdown` may be empty, but the field must exist
- `rag.elements` and top-level `elements` must use the same three buckets: `tables`, `formulas`, `figures`
- clients must not be forced to infer success from free-text content

## 4.3 `get_task_status`

Successful response:

```json
{
  "task_id": "task_01J...",
  "state": "PARTIAL_FAILED",
  "completed_pages": [1, 2],
  "failed_pages": [3, 4],
  "pending_pages": [5],
  "failed_page_errors": {
    "3": "process_task_page timeout after 280s",
    "4": "VLM token quota exhausted"
  },
  "progress": 40
}
```

Required fields:
- `task_id: string`
- `state: string`
- `completed_pages: integer[]`
- `failed_pages: integer[]`

Recommended fields:
- `pending_pages: integer[]`
- `failed_page_errors: object`
- `progress: integer`

Allowed `state` values should include at least:
- `PENDING`
- `RUNNING`
- `SUCCESS`
- `PARTIAL_FAILED`
- `FAILED`
- `CANCELLED`

## 4.4 `finalize_task`

Default request:

```json
{
  "task_id": "task_01J...",
  "merge_mode": "none"
}
```

Successful response with default `merge_mode=none`:

```json
{
  "summary": {
    "task_id": "task_01J...",
    "status": "FAILED",
    "completed_pages": [1, 2],
    "failed_pages": [3],
    "failed_page_errors": {
      "3": "VLM token quota exhausted"
    },
    "progress": 66
  },
  "failed_page_errors": {
    "3": "VLM token quota exhausted"
  }
}
```

Required fields:
- `summary: object`

Required `summary` fields:
- `task_id: string`
- `status: string`
- `completed_pages: integer[]`
- `failed_pages: integer[]`

Recommended `summary` fields:
- `failed_page_errors: object`
- `progress: integer`

Rules:
- `merge_mode=none` must return summary-only behavior by default
- merged markdown/rag content must be returned only when explicitly requested

---

## 5. Failure Contract

## 5.1 Page-level failure

For `process_task_page`, page-level failure must be reported via the MCP error transport, not by returning a fake success JSON payload.

Compatible failure shape:

```json
{
  "result": {
    "isError": true,
    "content": [
      {
        "type": "text",
        "text": "具体错误信息"
      }
    ]
  }
}
```

Rules:
- if `isError=true`, the call is failed
- do not return normal success payload together with `isError=true`
- do not wrap page failure only inside `page_result.error`
- client should read `content[0].text` as the primary message

## 5.2 Task-level partial failure or final failure

For `get_task_status` and `finalize_task`, partial failures should normally be returned as a successful business response containing page-level failure details:

```json
{
  "task_id": "task_01J...",
  "state": "PARTIAL_FAILED",
  "completed_pages": [1, 2],
  "failed_pages": [3, 4],
  "failed_page_errors": {
    "3": "process_task_page timeout after 280s",
    "4": "VLM token quota exhausted"
  }
}
```

Rules:
- task-level partial failure is not the same as transport failure
- clients must rely on `failed_pages` and `failed_page_errors`
- `failed_page_errors` should be keyed by page number as string for compatibility

## 5.3 Retryability guidance

Retryable errors:
- timeout
- transient 5xx
- rate limit / quota throttling

Non-retryable errors:
- bad request schema
- invalid credentials
- page out of range
- invalid file data
- unknown task_id

This classification should be reflected in the error text even if no dedicated error code is present.

---

## 6. Strict Compatibility Rules

If the new service claims `pdf2md-enhanced` compatibility, it must satisfy all of the following:

1. `process_task_page` success returns `page_result`
2. `process_task_page` failure uses `isError=true`
3. `page_result.render.markdown` exists
4. `page_result.rag.content` exists
5. `page_result.rag.elements.tables|formulas|figures` exist
6. top-level `elements.tables|formulas|figures` exist
7. `get_task_status` and `finalize_task` expose `failed_pages`
8. page-specific causes are exposed in `failed_page_errors`
9. `finalize_task(merge_mode=none)` does not force merged full-document payloads

Any service that breaks these rules is not wire-compatible with existing `pdf2md-enhanced` clients.

---

## 7. Implementation Freedom

The following may differ without breaking compatibility:
- OCR engine
- VLM provider
- parsing strategy
- routing logic
- internal `decision.metrics` details
- exact wording of error messages
- optional extra fields

The following should not differ if compatibility matters:
- required field names
- page-level failure transport
- task-level failure summary fields
- default merge behavior

---

## 8. Recommended Developer Guidance

When implementing a new compatible PDF MCP:

1. Reuse the same outward response schema first, then evolve internals freely
2. Treat `page_result` as the stable client contract boundary
3. Keep page failures on the MCP error channel
4. Keep task summary failures in `failed_page_errors`
5. Add new fields only in an additive way
6. Do not rename or remove existing compatibility fields

---

## 9. Reference Baseline

This compatibility spec is derived from:
- `/Users/kehongwei/workspace/AICMDEngine/docs/PDF2MD_Enhanced_Client_Guide.md`
- `/Users/kehongwei/workspace/AICMDEngine/docs/PDF2MD_Enhanced_TaskFlow_Design.md`
- `/Users/kehongwei/workspace/AICMDEngine/tests/test_pdf2md_enhanced_mcp.py`

If those documents evolve, this compatibility spec should be updated accordingly.
