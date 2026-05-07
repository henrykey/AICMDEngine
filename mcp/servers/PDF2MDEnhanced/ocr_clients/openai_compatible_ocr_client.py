from __future__ import annotations

import base64
import logging
import time
from typing import Any, Dict, Optional

from .ocr_models import OcrResult
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
        self.enabled = bool(cfg.get("enabled", False) and self.model and self.api_key and self.base_url)
        self._client = None
        if self.enabled:
            from openai import OpenAI

            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url, default_headers=self.extra_headers)

    def extract_page(self, image_path: str, prompt: Optional[str] = None) -> OcrResult:
        self.ensure_enabled()
        text = self._call_image_prompt(image_path, prompt or self._default_prompt())
        return normalize_text_response(text, self.source)

    def ensure_enabled(self) -> None:
        if not self.enabled or self._client is None:
            raise ValueError(f"{self.source} config is required for this mode")

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
