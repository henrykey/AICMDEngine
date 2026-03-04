from __future__ import annotations

import base64
import json
import re
import time
from typing import Any, Dict, Optional


class DynamicVLMClient:
    def __init__(self, vlm_config: Optional[Dict[str, Any]]) -> None:
        cfg = vlm_config or {}
        self.provider = str(cfg.get("provider") or "").strip()
        self.model = str(cfg.get("model") or "").strip()
        self.api_key = str(cfg.get("api_key") or "").strip()
        self.base_url = str(cfg.get("base_url") or "").strip()
        self.timeout_sec = int(cfg.get("timeout_sec", 60))
        self.max_retries = int(cfg.get("max_retries", 2))
        self.temperature = float(cfg.get("temperature", 0.1))
        self.extra_headers = cfg.get("extra_headers") or {}

        self.enabled = bool(self.model and self.api_key and self.base_url)
        self._client = None
        if self.enabled:
            from openai import OpenAI

            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url, default_headers=self.extra_headers)

    def ensure_enabled(self) -> None:
        if not self.enabled or self._client is None:
            raise ValueError("vlm_config is required for this mode")

    def recognize_layout(self, image_path: str) -> Dict[str, Any]:
        prompt = (
            "Analyze page layout and return strict JSON with keys: "
            "page_type(header/footer/page_number/content_summary/confidence). "
            "page_type in [normal,toc,cover,blank]."
        )
        text = self._call_image_prompt(image_path, prompt, max_tokens=700)
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
        prompt = "Extract page content as clean markdown. Keep structure, formulas and tables where possible."
        return self._call_image_prompt(image_path, prompt, max_tokens=1600)

    def extract_region_structured(self, image_path: str) -> Dict[str, Any]:
        prompt = (
            "Extract formulas, tables and figure captions from this page and return strict JSON keys: "
            "formulas(list of latex strings), tables(list of markdown tables), figures(list of captions)."
        )
        text = self._call_image_prompt(image_path, prompt, max_tokens=1800)
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
                content = resp.choices[0].message.content if resp.choices else ""
                if isinstance(content, list):
                    return "\n".join([x.get("text", "") for x in content if isinstance(x, dict)])
                return content or ""
            except Exception as exc:
                last_err = exc
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
