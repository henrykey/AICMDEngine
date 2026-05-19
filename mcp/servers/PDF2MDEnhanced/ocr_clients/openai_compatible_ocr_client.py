from __future__ import annotations

import base64
import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from .ocr_models import OcrElement, OcrResult
from .ocr_normalizers import normalize_text_response

logger = logging.getLogger(__name__)


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
        self.mode = str(cfg.get("mode") or cfg.get("api_type") or cfg.get("endpoint_type") or "").strip().lower()
        self.layout_url = str(cfg.get("layout_url") or cfg.get("api_url") or "").strip()
        self.use_layout_parsing = self._should_use_layout_parsing()
        self.enabled = bool(cfg.get("enabled", False) and self.model and self.api_key and self.base_url)
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
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **{str(k): str(v) for k, v in self.extra_headers.items()},
        }
        body = json.dumps(payload).encode("utf-8")
        last_err = None
        for attempt in range(self.max_retries + 1):
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
                logger.warning(
                    "%s layout_parsing call failed: model=%s attempt=%s/%s error=%s",
                    self.source,
                    self.model,
                    attempt + 1,
                    self.max_retries + 1,
                    last_err,
                )
                if 400 <= exc.code < 500 or attempt >= self.max_retries:
                    break
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
            time.sleep(0.4 * (attempt + 1))
        raise RuntimeError(f"{self.source} layout_parsing call failed: {last_err}")

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
            "For figures, return only caption/layout hints, not semantic explanation."
        )
