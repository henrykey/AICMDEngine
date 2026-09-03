from __future__ import annotations

import base64
import json
import logging
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from .ocr_models import OcrElement, OcrResult
from .ocr_normalizers import normalize_text_response

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


class OpenAICompatibleOcrClient:
    def __init__(self, config: Optional[Dict[str, Any]], source: str = "glm_ocr") -> None:
        cfg = config or {}
        self.source = source
        self.model = str(cfg.get("model") or "").strip()
        self.api_key = str(cfg.get("api_key") or "").strip()
        self.base_url = str(cfg.get("base_url") or "").strip()
        self.timeout_sec = int(cfg.get("timeout_sec", 300))
        self.max_retries = int(cfg.get("max_retries", 2))
        self.max_tokens = int(cfg.get("max_tokens", 4096))
        self.temperature = float(cfg.get("temperature", 0.0))
        self.extra_headers = cfg.get("extra_headers") or {}
        self.description_language = str(cfg.get("description_language") or "unknown")
        self.mode = str(cfg.get("mode") or cfg.get("api_type") or cfg.get("endpoint_type") or "").strip().lower()
        self.layout_url = str(cfg.get("layout_url") or cfg.get("api_url") or "").strip()
        self.use_layout_parsing = self._should_use_layout_parsing()
        self.enabled = bool(cfg.get("enabled", False) and self.model and self.base_url)
        self._client = None
        if self.enabled and not self.use_layout_parsing:
            from openai import OpenAI

            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url, default_headers=self.extra_headers)

    def extract_page(self, image_path: str, prompt: Optional[str] = None) -> OcrResult:
        self.ensure_enabled()
        if self.use_layout_parsing:
            return self._call_layout_parsing(image_path)
        text = self._call_image_prompt(image_path, prompt or self._default_prompt())
        return normalize_text_response(text, self.source)

    def extract_table_html(self, image_path: str) -> str:
        """Read one already-cropped table; keep HTML without flattening or adding metadata."""
        self.ensure_enabled()
        self.last_object_call_info = {}
        if self.use_layout_parsing:
            data = self._call_layout_parsing_raw(image_path)
            tables = [item for page in data.get("layout_details") or [] if isinstance(page, list)
                      for item in page if isinstance(item, dict) and item.get("label") == "table"]
            # Never pick the first of multiple tables returned for one ledger object.
            if len(tables) > 1:
                raise ValueError("ocr_crop_multiple_tables")
            text = str(tables[0].get("content") or "") if tables else str(
                data.get("md_results") or data.get("markdown") or "")
            self.last_object_call_info["finish_reason"] = data.get("finish_reason")
        else:
            text = self._call_image_prompt(image_path, (
                "Transcribe this single cropped table. Return ONLY one complete valid HTML table, "
                "all rows and cells, preserving rowspan and colspan and LaTeX formulas. "
                "No JSON, no summary, no invented columns. Close all HTML tags."
            ))
        self.last_object_call_info.update({"response_chars": len(text), "call_mode": "non_stream",
                                           "json_status": "html" if text.strip() else "empty"})
        text = text.strip()
        fenced = re.fullmatch(r"```(?:html)?\s*\n?(.*?)\n?```", text, flags=re.S | re.I)
        text = fenced.group(1).strip() if fenced else text
        if not re.search(r"<table\b", text, flags=re.I):
            self.last_object_call_info["json_status"] = "invalid" if text else "empty"
            return ""
        return text

    def parse_layout(
        self,
        image_path: str,
        return_crop_images: bool = False,
        need_layout_visualization: bool = False,
    ) -> Dict[str, Any]:
        self.ensure_enabled()
        if not self.use_layout_parsing:
            raise ValueError(f"{self.source} layout parsing mode is required")
        return self._call_layout_parsing_raw(
            image_path,
            return_crop_images=return_crop_images,
            need_layout_visualization=need_layout_visualization,
        )

    def ensure_enabled(self) -> None:
        if not self.enabled or (not self.use_layout_parsing and self._client is None):
            raise ValueError(f"{self.source} config is required for this mode")

    def _should_use_layout_parsing(self) -> bool:
        if self.mode in {"layout_parsing", "layout", "glm_ocr_maas", "maas"}:
            return True
        base = self.base_url.lower()
        if "layout_parsing" in base:
            return True
        if self.model == "glm-ocr":
            return True
        return False

    def _resolved_layout_url(self) -> str:
        url = (self.layout_url or self.base_url).rstrip("/")
        if url.endswith("/layout_parsing"):
            return url
        if url.endswith("/chat/completions"):
            url = url[: -len("/chat/completions")]
        if url.endswith("/v1"):
            url = url[: -len("/v1")]
        return f"{url}/layout_parsing"

    def _call_layout_parsing(self, image_path: str) -> OcrResult:
        return self._normalize_layout_parsing_response(self._call_layout_parsing_raw(image_path))

    def _call_layout_parsing_raw(
        self,
        image_path: str,
        return_crop_images: bool = False,
        need_layout_visualization: bool = False,
    ) -> Dict[str, Any]:
        with open(image_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")

        url = self._resolved_layout_url()
        payload = {
            "model": self.model,
            "file": self._data_uri_for_file(image_path, encoded),
            "return_crop_images": bool(return_crop_images),
            "need_layout_visualization": bool(need_layout_visualization),
        }
        headers = {
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
            **{str(k): str(v) for k, v in self.extra_headers.items()},
        }
        body = json.dumps(payload).encode("utf-8")
        last_err = None
        for attempt in range(self.max_retries + 1):
            retry_delay = 0.4 * (attempt + 1)
            try:
                t0 = time.time()
                request = urllib.request.Request(url, data=body, headers=headers, method="POST")
                with urllib.request.urlopen(request, timeout=self.timeout_sec) as response:
                    raw = response.read().decode("utf-8")
                elapsed = time.time() - t0
                logger.info(
                    "%s layout_parsing call ok: model=%s attempt=%s elapsed=%.2fs",
                    self.source,
                    self.model,
                    attempt + 1,
                    elapsed,
                )
                return json.loads(raw)
            except urllib.error.HTTPError as exc:
                error_body = exc.read().decode("utf-8", errors="replace")
                last_err = f"HTTP {exc.code}: {error_body}"
                retryable_overload = self._is_retryable_layout_overload(exc.code, error_body)
                logger.warning(
                    "%s layout_parsing call failed: model=%s attempt=%s/%s error=%s",
                    self.source,
                    self.model,
                    attempt + 1,
                    self.max_retries + 1,
                    last_err,
                )
                if (400 <= exc.code < 500 and not retryable_overload) or attempt >= self.max_retries:
                    break
                if retryable_overload:
                    retry_delay = 3.0 * (attempt + 1)
                    logger.warning(
                        "%s layout_parsing overloaded: waiting %.1fs before retry=%s/%s",
                        self.source,
                        retry_delay,
                        attempt + 1,
                        self.max_retries,
                    )
            except Exception as exc:
                last_err = repr(exc)
                logger.warning(
                    "%s layout_parsing call failed: model=%s attempt=%s/%s error=%s",
                    self.source,
                    self.model,
                    attempt + 1,
                    self.max_retries + 1,
                    last_err,
                )
                if attempt >= self.max_retries:
                    break
            time.sleep(retry_delay)
        raise RuntimeError(f"{self.source} layout_parsing call failed: {last_err}")

    @staticmethod
    def _is_retryable_layout_overload(status_code: int, error_body: str) -> bool:
        if status_code != 429:
            return False
        try:
            payload = json.loads(error_body)
        except (TypeError, ValueError):
            return False
        error = payload.get("error") if isinstance(payload, dict) else None
        codes = [payload.get("code")] if isinstance(payload, dict) else []
        if isinstance(error, dict):
            codes.append(error.get("code"))
        return any(str(code) == "1305" for code in codes)

    def _data_uri_for_file(self, image_path: str, encoded: str) -> str:
        suffix = Path(image_path).suffix.lower()
        mime = {
            ".pdf": "application/pdf",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
        }.get(suffix, "image/png")
        return f"data:{mime};base64,{encoded}"

    def _normalize_layout_parsing_response(self, data: Dict[str, Any]) -> OcrResult:
        markdown = str(data.get("md_results") or data.get("markdown") or "").strip()
        result = normalize_text_response(markdown, self.source) if markdown else OcrResult()
        result.raw = data
        result.markdown = result.markdown or markdown
        result.page_text = result.page_text or markdown

        for page in data.get("layout_details") or []:
            if not isinstance(page, list):
                continue
            for item in page:
                if not isinstance(item, dict):
                    continue
                label = str(item.get("label") or "").strip().lower()
                content = str(item.get("content") or "").strip()
                if not content:
                    continue
                element = OcrElement(kind=label, source=self.source, text=content, raw=item)
                if label == "table":
                    element.markdown = content
                    element.title = self._pick_layout_str(
                        item,
                        "table_title",
                        "tableName",
                        "table_name",
                        "caption",
                        "name",
                        "title",
                        "表名",
                    )
                    result.tables.append(element)
                elif label == "formula":
                    element.latex = content
                    result.formulas.append(element)
                elif label == "image":
                    element.description = content
                    element.caption = "Image"
                    result.figures.append(element)
        return result

    def _pick_layout_str(self, data: Dict[str, Any], *names: str) -> str:
        for name in names:
            value = data.get(name)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _call_image_prompt(self, image_path: str, prompt: str) -> str:
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
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                )
                elapsed = time.time() - t0
                logger.info(
                    "%s call ok: model=%s attempt=%s elapsed=%.2fs",
                    self.source,
                    self.model,
                    attempt + 1,
                    elapsed,
                )
                content = resp.choices[0].message.content if resp.choices else ""
                self.last_object_call_info = {
                    "finish_reason": getattr(resp.choices[0], "finish_reason", None) if resp.choices else None,
                    "requested_max_tokens": self.max_tokens,
                    "effective_max_tokens": self.max_tokens,
                }
                if isinstance(content, list):
                    return "\n".join([str(x.get("text") or "") for x in content if isinstance(x, dict)])
                return str(content or "")
            except Exception as exc:
                last_err = exc
                logger.warning(
                    "%s call failed: model=%s attempt=%s/%s error=%s",
                    self.source,
                    self.model,
                    attempt + 1,
                    self.max_retries + 1,
                    repr(exc),
                )
                if attempt >= self.max_retries:
                    break
                time.sleep(0.4 * (attempt + 1))
        raise RuntimeError(f"{self.source} call failed: {last_err}")

    def _default_prompt(self) -> str:
        return (
            "Extract OCR/layout from this PDF page. Return strict JSON only with keys: "
            "render, rag. render is markdown. rag.page_text is plain text. "
            "rag.elements has formulas, tables, figures arrays. "
            "Tables must be markdown when possible. Formulas must be LaTeX when possible. "
            "For figures, return only caption/layout hints, not semantic explanation. "
            "When layout geometry is available, use bbox [x0,y0,x1,y1] normalized to the full page image "
            "in the 0..1 range and set bbox_space to normalized_page. Table source_cells row 0 is the header "
            "row; set source_cell_row_offset to 1 and include row, col, rowspan, colspan, source_cell_index, "
            "confidence, and bbox for each reliably bounded source cell. Omit uncertain cell bboxes."
        ) + _description_language_instruction(self.description_language)
