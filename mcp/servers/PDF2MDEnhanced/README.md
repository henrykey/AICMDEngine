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

## Notes

- No MinerU runtime dependency.
- Uses Fitz for PDF text/geometry/image rendering.
- VLM config is dynamically injected by caller (`vlm_config`).
