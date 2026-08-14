from __future__ import annotations

import base64
import json
import logging
import re
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


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
        self._runtime_max_tokens_cap: Optional[int] = None
        self.last_dual_output_budget: Dict[str, Any] = {}

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
        prompt = "Extract page content as clean markdown. Keep structure, formulas and tables where possible. Illustrations are replaced with placeholders described in text."
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
        )
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
        )
        text = self._call_image_prompt(image_path, prompt, max_tokens=self.max_tokens)
        data = self._extract_json(text)
        if data:
            return data
        return {"formulas": [], "tables": [], "figures": []}

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
                content, mode = self._chat_completion_with_stream_fallback(
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
                logger.info(
                    "VLM call ok: model=%s max_tokens=%s attempt=%s mode=%s elapsed=%.2fs",
                    self.model,
                    call_max_tokens,
                    attempt + 1,
                    mode,
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
                content, mode = self._chat_completion_with_stream_fallback(
                    model=self.model,
                    messages=[{"role": "user", "content": [{"type": "text", "text": prompt}]}],
                    timeout=self.timeout_sec,
                    max_tokens=call_max_tokens,
                    temperature=min(self.temperature, 0.1),
                )
                elapsed = time.time() - t0
                logger.info(
                    "VLM text call ok: model=%s max_tokens=%s attempt=%s mode=%s elapsed=%.2fs",
                    self.model,
                    call_max_tokens,
                    attempt + 1,
                    mode,
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

    def _chat_completion_with_stream_fallback(self, **kwargs: Any) -> tuple[str, str]:
        """
        Prefer streaming mode for lower first-token latency.
        Automatically falls back to non-stream mode for providers/gateways
        that do not support stream responses.
        """
        stream_err = None
        try:
            stream_resp = self._client.chat.completions.create(stream=True, **kwargs)
            chunks: list[str] = []
            for chunk in stream_resp:
                piece = self._extract_stream_chunk_text(chunk)
                if piece:
                    chunks.append(piece)

            merged = "".join(chunks)
            if merged:
                return merged, "stream"

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
                    for chunk in stream_resp:
                        piece = self._extract_stream_chunk_text(chunk)
                        if piece:
                            chunks.append(piece)

                    merged = "".join(chunks)
                    if merged:
                        return merged, "stream"
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
        normalized = self._normalize_message_content(content)
        if stream_err is not None:
            logger.info("VLM non-stream fallback succeeded after stream failure")
        return normalized, "non-stream"

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
