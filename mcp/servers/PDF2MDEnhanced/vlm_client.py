from __future__ import annotations

import base64
import json
import logging
import re
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _description_language_instruction(value: Any) -> str:
    language = str(value or "").strip().lower()
    if language in {"zh", "zh-cn", "zh_hans", "chinese"}:
        output_language = "Chinese"
    else:
        output_language = "English"
    return (
        " All generated semantic descriptions, captions, contexts, and variable explanations must be "
        f"written in {output_language}. Copy visible titles, labels, table cells, symbols, and formulas "
        "verbatim; do not translate source content."
    )


def _extract_html_table(text: Any) -> str:
    """Keep the single HTML table from a model response, stripping only a fence."""
    value = str(text or "").strip()
    if value.startswith("```"):
        first_newline = value.find("\n")
        if first_newline >= 0:
            value = value[first_newline + 1:]
        if value.rstrip().endswith("```"):
            value = value.rstrip()[:-3]
    start = re.search(r"<table\b[^>]*>", value, flags=re.IGNORECASE)
    end = list(re.finditer(r"</table\s*>", value, flags=re.IGNORECASE))
    if not start:
        return ""
    if not end:
        return value[start.start():].strip()
    return value[start.start():end[-1].end()].strip()


class DynamicVLMClient:
    def __init__(self, vlm_config: Optional[Dict[str, Any]]) -> None:
        cfg = vlm_config or {}
        self.provider = str(cfg.get("provider") or "").strip()
        self.model = str(cfg.get("model") or "").strip()
        self.api_key = str(cfg.get("api_key") or "").strip()
        self.base_url = str(cfg.get("base_url") or "").strip()
        self.timeout_sec = int(cfg.get("timeout_sec", 60))
        self.max_retries = int(cfg.get("max_retries", 2))
        self.max_tokens = int(cfg.get("max_tokens", 4096))
        self.context_window = int(cfg.get("context_window", 4096))
        self.dual_output_max_tokens = int(cfg.get("dual_output_max_tokens", 4096))
        self.context_window_safety_margin = int(cfg.get("context_window_safety_margin", 0))
        self.temperature = float(cfg.get("temperature", 0.1))
        self.extra_headers = cfg.get("extra_headers") or {}
        self.description_language = str(cfg.get("description_language") or "unknown")
        self._runtime_max_tokens_cap: Optional[int] = None
        self.last_dual_output_budget: Dict[str, Any] = {}
        self.last_call_info: Dict[str, Any] = {}
        self.last_object_call_info: Dict[str, Any] = {}

        self.enabled = bool(self.model and self.api_key and self.base_url)
        self._client = None
        if self.enabled:
            from openai import OpenAI

            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url, default_headers=self.extra_headers)
        logger.info(
            "DynamicVLMClient init: enabled=%s provider=%s model=%s base_url=%s timeout=%s max_retries=%s max_tokens=%s",
            self.enabled,
            self.provider,
            self.model,
            self.base_url,
            self.timeout_sec,
            self.max_retries,
            self.max_tokens,
        )

    def ensure_enabled(self) -> None:
        if not self.enabled or self._client is None:
            raise ValueError("vlm_config is required for this mode")

    def recognize_layout(self, image_path: str) -> Dict[str, Any]:
        prompt = (
            "Analyze page layout and return strict JSON with keys: "
            "page_type(header/footer/page_number/content_summary/confidence). "
            "page_type in [normal,toc,cover,blank]."
        )
        text = self._call_image_prompt(image_path, prompt, max_tokens=min(self.max_tokens, 1200))
        data = self._extract_json(text)
        if data:
            return data
        return {
            "page_type": "normal",
            "header": [],
            "footer": [],
            "page_number": "",
            "content_summary": "",
            "confidence": "low",
        }

    def full_page_markdown(self, image_path: str) -> str:
        prompt = "Extract page content as clean markdown. Keep structure, formulas and tables where possible. Illustrations are replaced with placeholders described in text." + _description_language_instruction(self.description_language)
        # prompt = """
        #     分析这页PDF，生成Render数据。
        #     Render（展示用）：
        #     - 识别类型（封面/目录/正文）
        #     - 正文：表格→Markdown，插图→详细描述，公式→LaTeX
        #     """
        return self._call_image_prompt(image_path, prompt, max_tokens=self.max_tokens)

    def full_page_dual_output(self, image_path: str) -> Dict[str, Any]:
        """
        One-call dual dataset extraction for FULL_VLM mode.
        Expected JSON:
        {
          "render": "<markdown>",
          "rag": {
            "page_text": "<verbatim body text for retrieval>",
            "elements": {
              "formulas": [ ... ],
              "tables": [ ... ],
              "illustrations": [ ... ]
            }
          }
        }
        """
        
        # prompt = """
        #     You are a technical document analyst. Process the input page image and output ONLY a valid JSON object with no extra text, markdown fences, or explanations.

        #     Required keys: "render", "rag".

        #     Rules:
        #     1. IGNORE ALL NON-CONTENT ARTIFACTS:
        #     - Watermarks (e.g., faint background text/logo)
        #     - Headers (top-aligned text, e.g., standard numbers)
        #     - Footers (bottom-aligned text, including page numbers)
        #     - Footnote markers (e.g., *, †, [1]) AND their associated footnote text
        #     - Decorative borders or icons

        #     2. render (for human display):
        #     - Output clean Markdown containing ONLY:
        #             • Tables → full markdown tables (preserve all visible rows/columns)
        #             • Formulas → exact LaTeX expressions
        #             • Figures → placeholder blocks: "[FIGURE: <concise textual description>]"
        #             Description must include: shape/type (e.g., "schematic", "cross-section"), key labels (e.g., "D", "R ≥ 0.25D"), and context (e.g., "in泄放系数 table")
        #     - DO NOT include headings, paragraphs, lists, or prose — VLM cannot reliably reconstruct layout from image alone.

        #     3. rag (for retrieval/indexing):
        #     - rag.page_text: raw body text AFTER removing all ignored artifacts above. If none remains, use "".
        #     - rag.elements:
        #             • formulas: list of {"latex": "...", "context": "location hint (e.g., 'below Note 2')"}
        #             • tables: list of {"title": "Table X.Y", "description": "brief purpose", "data": [...] or "markdown string"}
        #             • figures: list of {"id": "Fig.X.Y", "description": "concise technical description"}  
        #             → Note: "figures" means numbered/labeled technical diagrams (e.g., schematics, cross-sections), NOT decorative art.

        #     4. STRICT CONSTRAINTS:
        #     - Never output base64 images.
        #     - If content is partially occluded, include visible parts and mark missing cells as "..." (do not omit rows/columns).
        #     - If uncertain, output empty string/array — NO HALLUCINATION.
        #     - JSON must be parseable; no trailing commas, no extra fields.

        #     Output schema (exact):
        #     {
        #         "render": "string",
        #         "rag": {
        #             "page_text": "string",
        #             "elements": {
        #             "formulas": [{"latex": "...", "context": "..."}],
        #             "tables": [{"title": "...", "description": "...", "data": [...] or "string"}],
        #             "figures": [{"id": "...", "description": "..."}]
        #             }
        #         }
        #     }
        # """
        prompt = (
            "Analyze this PDF page and return strict JSON only.\n"
            "Output keys exactly: render, rag.\n"
            "Rules:\n"
            "1) Remove watermarks, headers, footers, page numbers, footnotes.\n"
            "2) render: markdown for display; keep headings/paragraphs/lists/tables/formulas. "
            "Tables in markdown; formulas in LaTeX; figures as [FIGURE: description].\n"
            "3) rag.page_text: plain body text for retrieval (can be empty if uncertain).\n"
            "4) rag.elements: formulas, tables, figures arrays with short semantic items and source geometry. "
            "All bbox values use [x0,y0,x1,y1] normalized to the full page image in 0..1 and "
            "bbox_space=normalized_page. Each table includes columns, normalized_rows, source_cell_row_offset=1, "
            "and only reliably bounded source_cells; source_cells row 0 is the header row and each cell includes "
            "row, col, rowspan, colspan, source_cell_index, bbox, bbox_space, and confidence.\n"
            "5) If uncertain, omit the uncertain bbox or use empty string/empty arrays. No extra text outside JSON.\n"
            "Schema:\n"
            "{\"render\":\"...\",\"rag\":{\"page_text\":\"\",\"elements\":{"
            "\"formulas\":[{\"latex\":\"\",\"description\":\"\",\"bbox\":[0,0,0,0],\"bbox_space\":\"normalized_page\",\"confidence\":0.0}],"
            "\"tables\":[{\"title\":\"\",\"markdown\":\"\",\"description\":\"\",\"columns\":[],\"normalized_rows\":[[]],\"bbox\":[0,0,0,0],\"bbox_space\":\"normalized_page\",\"source_cell_row_offset\":1,\"source_cells\":[]}],"
            "\"figures\":[{\"caption\":\"\",\"description\":\"\",\"bbox\":[0,0,0,0],\"bbox_space\":\"normalized_page\",\"confidence\":0.0}]}}}"
        ) + _description_language_instruction(self.description_language)
        # Keep dual-output bounded by the provider, task setting, and context reserve.
        effective_max_tokens = self._dual_output_budget()
        text = self._call_image_prompt(image_path, prompt, max_tokens=effective_max_tokens)
        data = self._extract_json(text)
        if not data:
            # Fallback rule: if render markdown can be recovered from partial/truncated JSON,
            # treat it as usable output and let downstream rebuild RAG from render.
            recovered_render = self._recover_render_from_broken_json(text)
            if recovered_render:
                return {
                    "render": recovered_render,
                    "rag": {
                        "page_text": "",
                        "elements": {"formulas": [], "tables": [], "figures": []},
                    },
                }
            raise ValueError("dual output json parse failed")
        return self._normalize_dual_payload(data)

    def _dual_output_budget(self) -> int:
        provider_max = max(512, self.max_tokens)
        configured_max = max(512, self.dual_output_max_tokens)
        context_available = max(512, self.context_window - max(0, self.context_window_safety_margin))
        effective = min(provider_max, configured_max, context_available)
        if effective == context_available and context_available < min(provider_max, configured_max):
            cap_reason = "context_window"
        elif effective == configured_max and configured_max < provider_max:
            cap_reason = "dual_output_max_tokens"
        else:
            cap_reason = "provider_max_tokens"
        self.last_dual_output_budget = {
            "provider_max_tokens": provider_max,
            "context_window": self.context_window,
            "configured_max_tokens": configured_max,
            "effective_max_tokens": effective,
            "cap_reason": cap_reason,
        }
        logger.info(
            "VLM dual-output budget: provider_max=%s context_window=%s configured_max=%s effective_max=%s cap_reason=%s",
            provider_max,
            self.context_window,
            configured_max,
            effective,
            cap_reason,
        )
        return effective

    def extract_region_structured(self, image_path: str) -> Dict[str, Any]:
        prompt = (
            "Extract tables, formulas, and meaningful figures from this page. Return strict JSON only with keys "
            "tables, formulas, figures. Preserve visible source content; do not invent missing values. "
            "Use objects so downstream persistence retains semantics and source location. "
            "All bbox values must use [x0,y0,x1,y1] normalized to the full page image in the 0..1 range, "
            "with bbox_space set to normalized_page. For tables, source_cells row 0 is the header row and "
            "source_cell_row_offset is 1; each source cell must include its original row/col, spans, confidence, "
            "source_cell_index, and bbox. Do not return a cell bbox when its boundary is uncertain. Schema: "
            '{"tables":[{"title":"","markdown":"","description":"","bbox":[0,0,0,0],'
            '"bbox_space":"normalized_page","columns":[],"normalized_rows":[[]],'
            '"source_cell_row_offset":1,"source_cells":[{"row":0,"col":0,"text":"",'
            '"rowspan":1,"colspan":1,"source_cell_index":0,"bbox":[0,0,0,0],'
            '"bbox_space":"normalized_page","confidence":0.0}],"cell_status":[],'
            '"confidence":0.0,"status":"EXTRACTED|LOW_CONFIDENCE|UNREADABLE"}],'
            '"formulas":[{"latex":"","description":"","variables":"","context":"",'
            '"bbox":[0,0,0,0],"bbox_space":"normalized_page",'
            '"confidence":0.0,"status":"EXTRACTED|LOW_CONFIDENCE|UNREADABLE"}],'
            '"figures":[{"caption":"","type":"schematic|chart|diagram|figure|unknown",'
            '"description":"","labels":[],"context":"","bbox":[0,0,0,0],"bbox_space":"normalized_page",'
            '"confidence":0.0,"status":"EXTRACTED|LOW_CONFIDENCE|UNREADABLE"}]}. '
            "Do not invent content for unreadable objects; empty content remains incomplete downstream."
        ) + _description_language_instruction(self.description_language)
        text = self._call_image_prompt(image_path, prompt, max_tokens=self.max_tokens)
        data = self._extract_json(text)
        if data:
            return data
        return {"formulas": [], "tables": [], "figures": []}

    def extract_layout_structured(self, image_path: str, layout_blocks: list[Dict[str, Any]]) -> Dict[str, Any]:
        bounded_blocks = []
        for block in layout_blocks:
            if not isinstance(block, dict):
                continue
            bounded_blocks.append(
                {
                    "layout_id": block.get("layout_id"),
                    "source_block_index": block.get("source_block_index"),
                    "type": block.get("type"),
                    "reading_order": block.get("reading_order"),
                    "bbox": block.get("bbox") or [],
                    "bbox_space": "normalized_page",
                    "content": str(block.get("content") or "")[:1200],
                }
            )
        prompt = (
            "Recover only the listed failed semantic layout blocks from this page. "
            "Do not discover, merge, reorder, or omit other page objects. Return at most one object per input block, "
            "and copy layout_id, source_block_index, and normalized bbox exactly. If a block is unreadable, omit it. "
            "Return strict JSON only with tables, formulas, figures arrays. Schema: "
            '{"tables":[{"layout_id":"","source_block_index":1,"bbox":[0,0,1,1],'
            '"bbox_space":"normalized_page","title":"","markdown":"","description":""}],'
            '"formulas":[{"layout_id":"","source_block_index":2,"bbox":[0,0,1,1],'
            '"bbox_space":"normalized_page","latex":"","description":"","variables":"","context":""}],'
            '"figures":[{"layout_id":"","source_block_index":3,"bbox":[0,0,1,1],'
            '"bbox_space":"normalized_page","caption":"","type":"figure","description":"",'
            '"labels":[],"context":""}]}. '
            f"Failed layout blocks: {json.dumps(bounded_blocks, ensure_ascii=False)}"
        ) + _description_language_instruction(self.description_language)
        text = self._call_image_prompt(image_path, prompt, max_tokens=self.max_tokens)
        data = self._extract_json(text)
        if not data:
            return {"formulas": [], "tables": [], "figures": []}
        return {
            "tables": data.get("tables") if isinstance(data.get("tables"), list) else [],
            "formulas": data.get("formulas") if isinstance(data.get("formulas"), list) else [],
            "figures": data.get("figures") if isinstance(data.get("figures"), list) else [],
        }

    def extract_object_structured(
        self, image_path: str, block: Dict[str, Any], compact: bool = False,
    ) -> Dict[str, Any]:
        """Transcribe one existing layout object's crop, not another layout inventory."""
        object_type = block.get("type")
        schemas = {
            "table": {"markdown": "", "title": ""},
            "formula": {"latex": "", "description": "", "variables": "", "context": ""},
            "figure": {"description": "", "caption": ""},
        }
        if object_type not in schemas:
            raise ValueError("unsupported object type")
        schema = {
            "layout_id": block.get("layout_id"), "type": object_type,
            "status": "EXTRACTED", "complete": True, **schemas[object_type],
        }
        prompt = (
            "The input image is already cropped to ONE identified document object, with small padding. "
            "Transcribe the complete visible object from the IMAGE, not a layout preview or a summary. "
            "The original page bbox is metadata only: do not apply it again to this crop. "
            "Return exactly one JSON object, no arrays, code fences or surrounding prose. "
            "Copy layout_id and type exactly. Do not discover, merge or substitute other objects. "
            "For a table preserve EVERY visible row, column, value, unit, formula, footnote and merged cell. "
            "Use complete valid HTML with all table/tr/td/th tags closed for merged cells, otherwise HTML or "
            "pipe Markdown with a header separator and consistent columns. Do not abbreviate repeated data. "
            "For a formula return complete LaTeX with balanced groups and environments. "
            "For a figure describe its visual contents and relationships in plain text only; a title alone is insufficient. "
            "Figure description must not contain HTML, XML, Markdown formatting, list markers, tags, or code fences. "
            "Set status=EXTRACTED and complete=true ONLY if the entire object is readable and transcribed. "
            "Otherwise set status=FAILED, complete=false and leave its payload empty. Never invent missing "
            "cells or values, and never close a partial table merely to claim completeness. "
            f"Original page bbox (metadata only): {json.dumps(block.get('bbox') or [])}. "
            f"Response schema: {json.dumps(schema, ensure_ascii=False)}. "
        ) + _description_language_instruction(self.description_language)
        if compact:
            prompt += (
                "This is the single compact retry after an invalid or incomplete response. Re-read the entire "
                "crop afresh. Minimize whitespace and omit optional title/description/context for tables or "
                "formulas, but keep every data row and cell; for figures keep the full visual description."
            )
        budget = max(1, min(self.max_tokens, 16384))
        self.last_call_info = {}
        self.last_object_call_info = {}
        text = self._call_image_prompt(image_path, prompt, max_tokens=budget)
        try:
            data = json.loads(text)
            json_status = "object" if isinstance(data, dict) else "non_object"
        except (TypeError, ValueError):
            data = None
            json_status = "invalid" if text else "empty"
        call = self.last_call_info
        finish = call.get("finish_reason")
        self.last_object_call_info = {
            "response_chars": len(text or ""),
            "json_status": json_status,
            "finish_reason": finish if finish in {None, "stop", "length", "content_filter", "tool_calls"} else "other",
            "requested_max_tokens": budget,
            "effective_max_tokens": call.get("effective_max_tokens"),
            "truncated": finish == "length",
            "call_mode": call.get("mode") if call.get("mode") in {"stream", "non_stream"} else "unknown",
        }
        return data if isinstance(data, dict) else {}

    def extract_table_html(
        self, image_path: str, block: Dict[str, Any], compact: bool = False,
    ) -> str:
        """Transcribe one cropped table as HTML; MCP owns object metadata."""
        prompt = (
            "The input image is already cropped to ONE identified table, with small padding. "
            "Return ONLY one complete valid HTML <table>...</table>, with no JSON, code fence, "
            "title, explanation, or surrounding prose. Preserve every visible row, column, value, "
            "formula, footnote, rowspan and colspan. Do not invent cells or abbreviate repeated data. "
            "The original page bbox is metadata only: do not apply it again to this crop. "
        )
        if compact:
            prompt += (
                "This is the single compact retry. Re-read the entire crop and minimize whitespace, "
                "but keep every cell and the complete HTML table."
            )
        budget = max(1, min(self.max_tokens, 16384))
        self.last_call_info = {}
        self.last_object_call_info = {}
        text = self._call_image_prompt(image_path, prompt, max_tokens=budget)
        html = _extract_html_table(text)
        call = self.last_call_info
        finish = call.get("finish_reason")
        self.last_object_call_info = {
            "response_chars": len(text or ""),
            "json_status": "html" if html else "invalid",
            "finish_reason": finish if finish in {None, "stop", "length", "content_filter", "tool_calls"} else "other",
            "requested_max_tokens": budget,
            "effective_max_tokens": call.get("effective_max_tokens"),
            "truncated": finish == "length",
            "call_mode": call.get("mode") if call.get("mode") in {"stream", "non_stream"} else "unknown",
        }
        return html

    def cleanup_markdown_table_noise(self, markdown_text: str) -> str:
        self.ensure_enabled()
        prompt = (
            "Clean the following markdown page content.\n"
            "Goal: remove only duplicated table residue that appears after or around markdown tables.\n"
            "Rules:\n"
            "1) Keep all markdown tables unchanged.\n"
            "2) Keep normal paragraphs, headings, notes, and formulas unchanged.\n"
            "3) Delete only obvious table residue lines that repeat table headers/cells as broken fragments.\n"
            "4) Do not summarize, rewrite, reorder, or translate.\n"
            "5) Return markdown only, no code fences, no explanations.\n"
            "\n"
            "Markdown input:\n"
            f"{markdown_text}"
        )
        return self._call_text_prompt(prompt, max_tokens=min(self.max_tokens, 4096))

    def _call_image_prompt(self, image_path: str, prompt: str, max_tokens: int) -> str:
        self.ensure_enabled()
        with open(image_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")

        last_err = None
        for attempt in range(self.max_retries + 1):
            try:
                t0 = time.time()
                call_max_tokens = self._apply_runtime_max_tokens_cap(max_tokens)
                content, mode, finish_reason = self._chat_completion_with_stream_fallback(
                    model=self.model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
                            ],
                        }
                    ],
                    timeout=self.timeout_sec,
                    max_tokens=call_max_tokens,
                    temperature=self.temperature,
                )
                elapsed = time.time() - t0
                self.last_call_info = {
                    "mode": mode,
                    "finish_reason": finish_reason,
                    "requested_max_tokens": max_tokens,
                    "effective_max_tokens": call_max_tokens,
                    "response_chars": len(content or ""),
                    "truncated": finish_reason == "length",
                }
                logger.info(
                    "VLM call ok: model=%s max_tokens=%s attempt=%s mode=%s finish_reason=%s response_chars=%s elapsed=%.2fs",
                    self.model,
                    call_max_tokens,
                    attempt + 1,
                    mode,
                    finish_reason,
                    len(content or ""),
                    elapsed,
                )
                return content or ""
            except Exception as exc:
                last_err = exc
                logger.warning(
                    "VLM call failed: model=%s attempt=%s/%s error=%s",
                    self.model,
                    attempt + 1,
                    self.max_retries + 1,
                    repr(exc),
                )
                if attempt >= self.max_retries:
                    break
                time.sleep(0.4 * (attempt + 1))

        raise RuntimeError(f"VLM call failed: {last_err}")

    def _call_text_prompt(self, prompt: str, max_tokens: int) -> str:
        self.ensure_enabled()

        last_err = None
        for attempt in range(self.max_retries + 1):
            try:
                t0 = time.time()
                call_max_tokens = self._apply_runtime_max_tokens_cap(max_tokens)
                content, mode, finish_reason = self._chat_completion_with_stream_fallback(
                    model=self.model,
                    messages=[{"role": "user", "content": [{"type": "text", "text": prompt}]}],
                    timeout=self.timeout_sec,
                    max_tokens=call_max_tokens,
                    temperature=min(self.temperature, 0.1),
                )
                elapsed = time.time() - t0
                self.last_call_info = {
                    "mode": mode,
                    "finish_reason": finish_reason,
                    "requested_max_tokens": max_tokens,
                    "effective_max_tokens": call_max_tokens,
                    "response_chars": len(content or ""),
                    "truncated": finish_reason == "length",
                }
                logger.info(
                    "VLM text call ok: model=%s max_tokens=%s attempt=%s mode=%s finish_reason=%s response_chars=%s elapsed=%.2fs",
                    self.model,
                    call_max_tokens,
                    attempt + 1,
                    mode,
                    finish_reason,
                    len(content or ""),
                    elapsed,
                )
                return content or ""
            except Exception as exc:
                last_err = exc
                logger.warning(
                    "VLM text call failed: model=%s attempt=%s/%s error=%s",
                    self.model,
                    attempt + 1,
                    self.max_retries + 1,
                    repr(exc),
                )
                if attempt >= self.max_retries:
                    break
                time.sleep(0.4 * (attempt + 1))

        raise RuntimeError(f"VLM text call failed: {last_err}")

    def _chat_completion_with_stream_fallback(self, **kwargs: Any) -> tuple[str, str, str]:
        """
        Prefer streaming mode for lower first-token latency.
        Automatically falls back to non-stream mode for providers/gateways
        that do not support stream responses.
        """
        stream_err = None
        try:
            stream_resp = self._client.chat.completions.create(stream=True, **kwargs)
            chunks: list[str] = []
            finish_reason = ""
            for chunk in stream_resp:
                finish_reason = self._stream_finish_reason(chunk) or finish_reason
                piece = self._extract_stream_chunk_text(chunk)
                if piece:
                    chunks.append(piece)

            merged = "".join(chunks)
            if merged:
                return merged, "stream", finish_reason

            logger.warning("VLM stream call returned empty content, fallback to non-stream mode")
        except Exception as exc:
            stream_err = exc
            if self._adjust_max_tokens_from_error(exc, kwargs):
                logger.warning(
                    "VLM stream call failed due to max_tokens range, retry stream with adjusted max_tokens=%s",
                    kwargs.get("max_tokens"),
                )
                try:
                    stream_resp = self._client.chat.completions.create(stream=True, **kwargs)
                    chunks: list[str] = []
                    finish_reason = ""
                    for chunk in stream_resp:
                        finish_reason = self._stream_finish_reason(chunk) or finish_reason
                        piece = self._extract_stream_chunk_text(chunk)
                        if piece:
                            chunks.append(piece)

                    merged = "".join(chunks)
                    if merged:
                        return merged, "stream", finish_reason
                    logger.warning("VLM stream retry returned empty content, fallback to non-stream mode")
                except Exception as retry_exc:
                    stream_err = retry_exc
                    logger.warning("VLM stream retry failed, fallback to non-stream mode: error=%s", repr(retry_exc))
            else:
                logger.warning("VLM stream call failed, fallback to non-stream mode: error=%s", repr(exc))

        try:
            resp = self._client.chat.completions.create(stream=False, **kwargs)
        except Exception as exc:
            if self._adjust_max_tokens_from_error(exc, kwargs):
                logger.warning(
                    "VLM non-stream call failed due to max_tokens range, retry with adjusted max_tokens=%s",
                    kwargs.get("max_tokens"),
                )
                resp = self._client.chat.completions.create(stream=False, **kwargs)
            else:
                raise
        content = resp.choices[0].message.content if resp.choices else ""
        finish_reason = str(getattr(resp.choices[0], "finish_reason", "") or "") if resp.choices else ""
        normalized = self._normalize_message_content(content)
        if stream_err is not None:
            logger.info("VLM non-stream fallback succeeded after stream failure")
        return normalized, "non-stream", finish_reason

    def _apply_runtime_max_tokens_cap(self, max_tokens: int) -> int:
        cap = self._runtime_max_tokens_cap
        if cap is None:
            return max_tokens
        return min(max_tokens, cap)

    def _adjust_max_tokens_from_error(self, exc: Exception, kwargs: Dict[str, Any]) -> bool:
        text = f"{type(exc).__name__}: {exc!s}"
        m = re.search(r"Range of max_tokens should be \[(\d+),\s*(\d+)\]", text)
        if not m:
            return False

        low = int(m.group(1))
        high = int(m.group(2))
        raw = kwargs.get("max_tokens", self.max_tokens)
        try:
            current = int(raw)
        except Exception:
            current = self.max_tokens

        adjusted = min(max(current, low), high)
        if adjusted == current:
            return False

        kwargs["max_tokens"] = adjusted
        self._runtime_max_tokens_cap = high if self._runtime_max_tokens_cap is None else min(self._runtime_max_tokens_cap, high)
        logger.warning(
            "Detected provider max_tokens range [%s, %s]; auto-adjust max_tokens from %s to %s",
            low,
            high,
            current,
            adjusted,
        )
        return True

    def _extract_stream_chunk_text(self, chunk: Any) -> str:
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            return ""
        delta = getattr(choices[0], "delta", None)
        if delta is None:
            return ""
        content = getattr(delta, "content", "")
        return self._normalize_message_content(content)

    def _stream_finish_reason(self, chunk: Any) -> str:
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            return ""
        return str(getattr(choices[0], "finish_reason", "") or "")

    def _normalize_message_content(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [x.get("text", "") for x in content if isinstance(x, dict)]
            return "\n".join([x for x in parts if x])
        return ""

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        if not text:
            return None
        try:
            return json.loads(text)
        except Exception:
            pass

        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
        return None

    def _recover_render_from_broken_json(self, text: str) -> str:
        """
        Recover "render" field from non-parseable/truncated JSON text.
        Returns empty string when recovery fails or content is too short to trust.
        """
        if not text:
            return ""
        # Case 1: model ignored JSON schema and returned plain markdown/text directly.
        direct = self._maybe_direct_markdown(text)
        if direct:
            return direct
        m = re.search(r'"render"\s*:\s*"((?:\\.|[^"\\])*)"', text, re.S)
        if not m:
            return ""
        raw = m.group(1)
        try:
            render = json.loads(f'"{raw}"')
        except Exception:
            return ""
        render = (render or "").strip()
        # Heuristic: avoid using tiny/fragmented render blocks as "complete".
        if len(render) < 120:
            return ""
        return render

    def _maybe_direct_markdown(self, text: str) -> str:
        s = (text or "").strip()
        if not s:
            return ""
        # Strip one outer markdown fence when present.
        if s.startswith("```"):
            lines = s.splitlines()
            if lines:
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            s = "\n".join(lines).strip()
        if len(s) < 120:
            return ""
        # If content still looks like JSON (including truncated JSON),
        # do not treat it as direct markdown.
        if s.startswith("{"):
            return ""
        return s

    def _normalize_dual_payload(self, data: Dict[str, Any]) -> Dict[str, Any]:
        render = data.get("render")
        render_text = render if isinstance(render, str) else ""

        rag = data.get("rag")
        rag_obj = rag if isinstance(rag, dict) else {}
        page_text = rag_obj.get("page_text")
        page_text_str = page_text if isinstance(page_text, str) else ""

        elements_raw = rag_obj.get("elements")
        elements_obj = elements_raw if isinstance(elements_raw, dict) else {}

        def _as_item_list(v: Any) -> list[Any]:
            if not isinstance(v, list):
                return []
            items: list[Any] = []
            for item in v:
                if isinstance(item, dict):
                    items.append(dict(item))
                elif isinstance(item, str) and item.strip():
                    items.append(item.strip())
            return items

        illustrations = _as_item_list(elements_obj.get("illustrations")) or _as_item_list(elements_obj.get("figures"))
        normalized_elements = {
            "formulas": _as_item_list(elements_obj.get("formulas")),
            "tables": _as_item_list(elements_obj.get("tables")),
            "figures": illustrations,
        }

        return {
            "render": render_text,
            "rag": {
                "page_text": page_text_str,
                "elements": normalized_elements,
            },
        }
