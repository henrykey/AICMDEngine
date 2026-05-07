from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from .ocr_models import OcrElement, OcrResult


def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except Exception:
        pass

    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def normalize_ocr_payload(payload: Any, source: str) -> OcrResult:
    data = payload if isinstance(payload, dict) else {}
    render = data.get("render") if isinstance(data.get("render"), str) else ""
    markdown = data.get("markdown") if isinstance(data.get("markdown"), str) else ""
    text = data.get("text") if isinstance(data.get("text"), str) else ""

    rag = data.get("rag") if isinstance(data.get("rag"), dict) else {}
    page_text = rag.get("page_text") if isinstance(rag.get("page_text"), str) else ""
    elements = data.get("elements") if isinstance(data.get("elements"), dict) else {}
    rag_elements = rag.get("elements") if isinstance(rag.get("elements"), dict) else {}
    merged_elements = {**rag_elements, **elements}

    return OcrResult(
        markdown=(render or markdown or text or "").strip(),
        page_text=(page_text or text or "").strip(),
        tables=_normalize_items(merged_elements.get("tables") or data.get("tables"), "table", source),
        formulas=_normalize_items(merged_elements.get("formulas") or data.get("formulas"), "formula", source),
        figures=_normalize_items(
            merged_elements.get("figures") or merged_elements.get("illustrations") or data.get("figures"),
            "figure",
            source,
        ),
        raw=data,
    )


def normalize_text_response(text: str, source: str) -> OcrResult:
    data = extract_json_object(text)
    if data:
        return normalize_ocr_payload(data, source)
    return OcrResult(markdown=(text or "").strip(), page_text=(text or "").strip(), raw={"text": text or ""})


def _normalize_items(value: Any, kind: str, source: str) -> List[OcrElement]:
    if not isinstance(value, list):
        return []
    out: List[OcrElement] = []
    for item in value:
        if isinstance(item, dict):
            markdown = _pick_str(item, "markdown", "table_markdown", "data")
            latex = _pick_str(item, "latex", "formula", "text")
            desc = _pick_str(item, "description", "semantic_summary", "summary")
            title = _pick_str(item, "title", "id", "name")
            caption = _pick_str(item, "caption", "label")
            context = _pick_str(item, "context", "surrounding_text")
            text = _pick_str(item, "text", "content")
            out.append(
                OcrElement(
                    kind=kind,
                    source=source,
                    text=text,
                    title=title,
                    markdown=markdown,
                    latex=latex,
                    caption=caption,
                    description=desc,
                    context=context,
                    raw=item,
                )
            )
        else:
            s = str(item or "").strip()
            if not s:
                continue
            if kind == "table":
                out.append(OcrElement(kind=kind, source=source, markdown=s, text=s))
            elif kind == "formula":
                out.append(OcrElement(kind=kind, source=source, latex=s, text=s))
            else:
                out.append(OcrElement(kind=kind, source=source, description=s, caption=s, text=s))
    return out


def _pick_str(data: Dict[str, Any], *names: str) -> str:
    for name in names:
        value = data.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if name == "data" and isinstance(value, list):
            return _table_data_to_markdown(value)
    return ""


def _table_data_to_markdown(rows: List[Any]) -> str:
    if not rows or not all(isinstance(row, list) for row in rows):
        return ""
    width = max((len(row) for row in rows), default=0)
    if width <= 1:
        return ""
    normalized = [[str(cell or "").strip() for cell in row] + [""] * (width - len(row)) for row in rows]
    header = normalized[0]
    body = normalized[1:]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    lines.extend("| " + " | ".join(row[:width]) + " |" for row in body)
    return "\n".join(lines).strip()
