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
        self.temperature = float(cfg.get("temperature", 0.1))
        self.extra_headers = cfg.get("extra_headers") or {}

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
            "Analyze this PDF page and return strict JSON only, no markdown fence, no explanations.\n"
            "You must output exactly keys: render, rag.\n"
            "Rules:\n"
            "1) Ignore and exclude all non-content artifacts: watermarks, headers, footers, page numbers, and footnote markers from BOTH render and rag. Focus only on the main technical content — tables, figures, formulas, and body text\n"
            "2) render: clean markdown for display; keep headings/paragraphs/list/table/formula. "
            "Tables as markdown tables, formulas as LaTeX. "
            "Figures are represented by placeholder blocks using textual descriptions.\n"
            "3) rag.page_text: verbatim body text for retrieval (not a summary), after removing header/footer/page number/footnotes.\n"
            "4) rag.elements: object with keys formulas/tables/figures, each value is list of semantic descriptions.\n"
            "5) No base64 image output.\n"
            "6) If extraction is uncertain for any field, return empty string/empty array for that field; never output invalid JSON.\n"
            "Output schema:\n"
            "{\"render\":\"...\",\"rag\":{\"page_text\":\"...\",\"elements\":{\"formulas\":[],\"tables\":[],\"figures\":[]}}}"
        )
        text = self._call_image_prompt(image_path, prompt, max_tokens=self.max_tokens)
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

    def extract_region_structured(self, image_path: str) -> Dict[str, Any]:
        prompt = (
            "Extract formulas, tables and figure captions from this page and return strict JSON keys: "
            "formulas(list of latex strings), tables(list of markdown tables), figures(list of captions)."
        )
        text = self._call_image_prompt(image_path, prompt, max_tokens=self.max_tokens)
        data = self._extract_json(text)
        if data:
            return data
        return {"formulas": [], "tables": [], "figures": []}

    def _call_image_prompt(self, image_path: str, prompt: str, max_tokens: int) -> str:
        self.ensure_enabled()
        with open(image_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")

        last_err = None
        for attempt in range(self.max_retries + 1):
            try:
                t0 = time.time()
                resp = self._client.chat.completions.create(
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
                    max_tokens=max_tokens,
                    temperature=self.temperature,
                )
                elapsed = time.time() - t0
                logger.info(
                    "VLM call ok: model=%s max_tokens=%s attempt=%s elapsed=%.2fs",
                    self.model,
                    max_tokens,
                    attempt + 1,
                    elapsed,
                )
                content = resp.choices[0].message.content if resp.choices else ""
                if isinstance(content, list):
                    return "\n".join([x.get("text", "") for x in content if isinstance(x, dict)])
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
        # If the model ignored JSON and returned long free-form content directly,
        # still accept it as render to keep single-call semantics.
        if s.startswith("{") and s.endswith("}"):
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

        def _as_str_list(v: Any) -> list[str]:
            if isinstance(v, list):
                return [str(x).strip() for x in v if str(x).strip()]
            return []

        illustrations = _as_str_list(elements_obj.get("illustrations")) or _as_str_list(elements_obj.get("figures"))
        normalized_elements = {
            "formulas": _as_str_list(elements_obj.get("formulas")),
            "tables": _as_str_list(elements_obj.get("tables")),
            "figures": illustrations,
        }

        return {
            "render": render_text,
            "rag": {
                "page_text": page_text_str,
                "elements": normalized_elements,
            },
        }
