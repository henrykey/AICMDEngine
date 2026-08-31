from __future__ import annotations

import re
from html.parser import HTMLParser

from typing import Any, Dict, List, Optional, Tuple


LAYOUT_VERSION = "pdf2md-layout-ledger-v1"
CANONICAL_TYPES = ("text", "table", "figure", "formula", "unknown")
TEXT_LAYOUT_TYPES = {
    "text",
    "title",
    "doc_title",
    "para_title",
    "paragraph_title",
    "section_title",
    "section_header",
    "paragraph",
    "caption",
    "table_caption",
    "figure_caption",
    "formula_caption",
    "header",
    "page_header",
    "footer",
    "page_footer",
    "footnote",
    "page_number",
    "reference",
    "list",
    "list_item",
    "section",
}
FIGURE_LAYOUT_TYPES = {"image", "image_body", "figure", "illustration", "chart", "diagram"}


def failed_layout_outcome(code: str) -> Dict[str, Any]:
    return {
        "layout_status": "FAILED",
        "layout_error": code,
        "layout": [],
        "blocks": [],
        "payloads": {"tables": [], "formulas": [], "figures": []},
        "markdown": "",
        "unmatched_recovery_refs": [],
    }


def blank_layout_outcome() -> Dict[str, Any]:
    return {
        "layout_status": "EXTRACTED",
        "layout_error": "",
        "layout": [],
        "blocks": [],
        "payloads": {"tables": [], "formulas": [], "figures": []},
        "markdown": "",
        "unmatched_recovery_refs": [],
    }


def build_layout_outcome(
    raw: Dict[str, Any],
    page_no: int,
    fallback_width: float,
    fallback_height: float,
) -> Dict[str, Any]:
    markdown = str(raw.get("md_results") or raw.get("markdown") or "").strip()
    page_width, page_height = _page_dimensions(raw, fallback_width, fallback_height)
    blocks = _normalize_blocks(raw, page_width, page_height)
    if not blocks:
        result = failed_layout_outcome("layout_returned_no_blocks")
        result["markdown"] = markdown
        return result

    layout: List[Dict[str, Any]] = []
    payloads: Dict[str, List[Dict[str, Any]]] = {"tables": [], "formulas": [], "figures": []}
    for reading_order, block in enumerate(blocks, 1):
        object_type = canonical_layout_type(block.get("layout_type"))
        layout_id = f"p{page_no}-o{reading_order:03d}-{object_type}"
        content = str(block.get("content") or "").strip()
        entry = {
            "layout_id": layout_id,
            "source_block_index": block.get("source_block_index"),
            "type": object_type,
            "layout_type": block.get("layout_type") or "unknown",
            "reading_order": reading_order,
            "bbox": block.get("bbox") or [],
            "bbox_space": "normalized_page",
            "status": "FAILED",
            "review_required": True,
            "content": content,
            "payload_ref": None,
            "error": None,
        }
        error = _entry_error(entry, str(block.get("bbox_error") or ""))
        if error:
            entry["error"] = error
        else:
            payload = _payload_from_entry(entry, block)
            if payload is None:
                entry["error"] = _error(f"layout_{object_type}_content_missing", "layout_content", True)
            else:
                entry["status"] = "EXTRACTED"
                entry["review_required"] = False
                if object_type != "text":
                    payloads[_collection_for_type(object_type)].append(payload)
        layout.append(entry)

    return {
        "layout_status": "EXTRACTED",
        "layout_error": "",
        "layout": layout,
        "blocks": blocks,
        "payloads": payloads,
        "markdown": markdown or _markdown_from_layout(layout),
        "unmatched_recovery_refs": [],
    }


def recovery_blocks(outcome: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {
            "layout_id": item["layout_id"],
            "source_block_index": item.get("source_block_index"),
            "type": item["type"],
            "reading_order": item["reading_order"],
            "bbox": item.get("bbox") or [],
            "bbox_space": "normalized_page",
            "content": item.get("content") or "",
        }
        for item in outcome.get("layout") or []
        if item.get("type") in {"table", "figure", "formula"}
        and item.get("status") == "FAILED"
        and ((item.get("error") or {}).get("stage") == "layout_content")
    ]


def apply_recovered_payloads(outcome: Dict[str, Any], recovered: Any) -> None:
    raw = recovered if isinstance(recovered, dict) else {}
    layout = outcome.get("layout") or []
    used_layout_ids: set[str] = set()
    unmatched: List[str] = list(outcome.get("unmatched_recovery_refs") or [])
    for object_type, collection in (("table", "tables"), ("formula", "formulas"), ("figure", "figures")):
        values = raw.get(collection)
        if not isinstance(values, list):
            continue
        for index, candidate in enumerate(values):
            if not isinstance(candidate, dict):
                unmatched.append(f"{collection}:{index}")
                continue
            entry = _match_recovery_entry(layout, candidate, object_type, used_layout_ids)
            if entry is None:
                unmatched.append(_recovery_ref(candidate, collection, index))
                continue
            payload = _recovered_payload(entry, candidate)
            if payload is None:
                continue
            outcome["payloads"][collection].append(payload)
            entry["status"] = "EXTRACTED"
            entry["review_required"] = False
            entry["content"] = _payload_content(object_type, payload)
            entry["error"] = None
            used_layout_ids.add(str(entry["layout_id"]))
    outcome["unmatched_recovery_refs"] = _unique(unmatched)


def reconcile_layout(
    layout_status: str,
    layout: List[Dict[str, Any]],
    output_elements: Dict[str, Any],
    unmatched_recovery_refs: Optional[List[str]] = None,
) -> Dict[str, Any]:
    if layout_status != "EXTRACTED":
        return {
            "identified": None,
            "extracted": 0,
            "failed": None,
            "by_type": {},
            "unmatched_layout_ids": [],
            "unmatched_payload_layout_ids": list(unmatched_recovery_refs or []),
            "duplicate_layout_ids": [],
            "review_required_layout_ids": [],
            "accounted_for": False,
            "complete": False,
        }

    payload_refs: Dict[str, List[Tuple[str, int]]] = {}
    unmatched_payloads: List[str] = list(unmatched_recovery_refs or [])
    valid_layout_ids = {str(item.get("layout_id") or "") for item in layout}
    for collection in ("tables", "formulas", "figures"):
        values = output_elements.get(collection)
        if not isinstance(values, list):
            continue
        for index, payload in enumerate(values):
            layout_id = str(payload.get("layout_id") or "") if isinstance(payload, dict) else ""
            if not layout_id or layout_id not in valid_layout_ids:
                unmatched_payloads.append(layout_id or f"{collection}:{index}")
                continue
            payload_refs.setdefault(layout_id, []).append((collection, index))

    duplicate_ids = sorted(layout_id for layout_id, refs in payload_refs.items() if len(refs) > 1)
    unmatched_layout_ids: List[str] = []
    for item in layout:
        layout_id = str(item.get("layout_id") or "")
        refs = payload_refs.get(layout_id, [])
        if item.get("type") in {"table", "figure", "formula"} and item.get("status") == "EXTRACTED":
            if len(refs) == 1:
                collection, index = refs[0]
                item["payload_ref"] = {"collection": collection, "index": index}
            else:
                unmatched_layout_ids.append(layout_id)
                item["status"] = "FAILED"
                item["review_required"] = True
                item["payload_ref"] = None
                item["error"] = _error(
                    "layout_payload_missing" if not refs else "layout_payload_ambiguous",
                    "reconciliation",
                    True,
                )
        elif refs:
            unmatched_payloads.append(layout_id)

    by_type = {
        name: {"identified": 0, "extracted": 0, "failed": 0}
        for name in CANONICAL_TYPES
        if any(item.get("type") == name for item in layout)
    }
    terminal = True
    for item in layout:
        object_type = str(item.get("type") or "unknown")
        stats = by_type.setdefault(object_type, {"identified": 0, "extracted": 0, "failed": 0})
        stats["identified"] += 1
        status = item.get("status")
        if status == "EXTRACTED":
            item["review_required"] = False
            stats["extracted"] += 1
        elif status == "FAILED":
            item["review_required"] = True
            stats["failed"] += 1
        else:
            terminal = False

    identified = len(layout)
    extracted = sum(1 for item in layout if item.get("status") == "EXTRACTED")
    failed = sum(1 for item in layout if item.get("status") == "FAILED")
    accounted_for = bool(
        terminal
        and identified == extracted + failed
        and not unmatched_layout_ids
        and not unmatched_payloads
        and not duplicate_ids
    )
    return {
        "identified": identified,
        "extracted": extracted,
        "failed": failed,
        "by_type": by_type,
        "unmatched_layout_ids": sorted(_unique(unmatched_layout_ids)),
        "unmatched_payload_layout_ids": sorted(_unique(unmatched_payloads)),
        "duplicate_layout_ids": duplicate_ids,
        "review_required_layout_ids": sorted(
            str(item.get("layout_id") or "")
            for item in layout
            if item.get("status") == "FAILED" or item.get("review_required") is True
        ),
        "accounted_for": accounted_for,
        "complete": accounted_for and failed == 0,
    }


def canonical_layout_type(value: Any) -> str:
    label = str(value or "unknown").strip().lower()
    if label in {"table", "table_body"}:
        return "table"
    if label in {"formula", "equation", "display_formula", "inline_formula"}:
        return "formula"
    if label in FIGURE_LAYOUT_TYPES:
        return "figure"
    if label in TEXT_LAYOUT_TYPES:
        return "text"
    return "unknown"


def _normalize_blocks(raw: Dict[str, Any], page_width: float, page_height: float) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []
    for page in raw.get("layout_details") or []:
        if not isinstance(page, list):
            continue
        for item in page:
            if not isinstance(item, dict):
                continue
            source_bbox = item.get("bbox_2d") if item.get("bbox_2d") is not None else item.get("bbox")
            normalized_bbox = _normalize_bbox(source_bbox, page_width, page_height)
            blocks.append(
                {
                    "source_block_index": item.get("index"),
                    "layout_type": str(item.get("label") or item.get("type") or "unknown").strip().lower(),
                    "bbox": normalized_bbox,
                    "bbox_error": "" if normalized_bbox else _bbox_error_code(source_bbox),
                    "content": str(item.get("content") or ""),
                    "raw": item,
                }
            )
    return blocks


def _page_dimensions(raw: Dict[str, Any], fallback_width: float, fallback_height: float) -> Tuple[float, float]:
    data_info = raw.get("data_info") if isinstance(raw.get("data_info"), dict) else {}
    width = _positive_number(
        data_info.get("width")
        or data_info.get("image_width")
        or raw.get("page_width")
        or raw.get("image_width")
        or fallback_width
    )
    height = _positive_number(
        data_info.get("height")
        or data_info.get("image_height")
        or raw.get("page_height")
        or raw.get("image_height")
        or fallback_height
    )
    return width or 1.0, height or 1.0


def _normalize_bbox(value: Any, page_width: float, page_height: float) -> List[float]:
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        return []
    try:
        coords = [float(value[index]) for index in range(4)]
    except (TypeError, ValueError):
        return []
    if all(0.0 <= coord <= 1.0 for coord in coords):
        normalized = coords
    else:
        normalized = [
            coords[0] / page_width,
            coords[1] / page_height,
            coords[2] / page_width,
            coords[3] / page_height,
        ]
    if not (
        0.0 <= normalized[0] < normalized[2] <= 1.0
        and 0.0 <= normalized[1] < normalized[3] <= 1.0
    ):
        return []
    return [round(coord, 6) for coord in normalized]


def _entry_error(entry: Dict[str, Any], bbox_error: str) -> Optional[Dict[str, Any]]:
    if not entry.get("bbox"):
        return _error(bbox_error or "layout_bbox_missing", "layout_normalization", False)
    if entry.get("type") == "unknown":
        return _error("unsupported_layout_type", "layout_normalization", False)
    if not str(entry.get("content") or "").strip():
        object_type = str(entry.get("type") or "unknown")
        return _error(f"layout_{object_type}_content_missing", "layout_content", object_type != "text")
    if entry.get("type") == "table" and _html_table_incomplete(str(entry.get("content") or "")):
        return _error("layout_table_content_incomplete", "layout_content", True)
    return None


def _html_table_incomplete(content: str) -> bool:
    opening = re.search(r"<table\b", content, flags=re.IGNORECASE)
    if opening is None:
        return False
    return re.search(r"</table\s*>", content[opening.end() :], flags=re.IGNORECASE) is None


def _payload_from_entry(entry: Dict[str, Any], block: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    object_type = str(entry.get("type") or "")
    content = str(entry.get("content") or "").strip()
    if object_type == "text":
        return {"text": content}
    common = _payload_common(entry)
    raw = block.get("raw") if isinstance(block.get("raw"), dict) else {}
    if object_type == "table":
        return {
            **common,
            "title": _first_text(raw, "table_title", "tableName", "table_name", "caption", "title"),
            "markdown": content,
            "description": _first_text(raw, "description", "semanticDesc", "summary"),
            "context": _first_text(raw, "context", "surrounding_text"),
        }
    if object_type == "formula":
        return {
            **common,
            "latex": content,
            "description": _first_text(raw, "description", "semanticDesc", "summary"),
            "variables": _first_text(raw, "variables"),
            "context": _first_text(raw, "context", "surrounding_text"),
        }
    if object_type == "figure":
        caption = _first_text(raw, "caption", "capture", "figureName", "name", "title")
        return {
            **common,
            "caption": caption,
            "description": _first_text(raw, "description", "semanticDesc", "summary") or content,
            "type": _first_text(raw, "figure_type", "type") or "figure",
            "labels": raw.get("labels") if isinstance(raw.get("labels"), list) else [],
            "context": _first_text(raw, "context", "surrounding_text"),
        }
    return None


def _recovered_payload(entry: Dict[str, Any], candidate: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    object_type = str(entry.get("type") or "")
    common = _payload_common(entry)
    if object_type == "table":
        markdown = _first_text(candidate, "markdown", "table_markdown", "content", "text")
        if not markdown or _html_table_incomplete(markdown):
            return None
        return {
            **candidate,
            **common,
            "source": _first_text(candidate, "source") or "glm_ocr_layout+vlm_ocr",
            "markdown": markdown,
            "title": _first_text(candidate, "title", "table_title", "tableName", "table_name"),
        }
    if object_type == "formula":
        latex = _first_text(candidate, "latex", "formula", "content", "text")
        if not latex:
            return None
        return {
            **candidate,
            **common,
            "source": _first_text(candidate, "source") or "glm_ocr_layout+vlm_ocr",
            "latex": latex,
        }
    if object_type == "figure":
        description = _first_text(candidate, "description", "semanticDesc", "summary")
        caption = _first_text(candidate, "caption", "capture", "figureName", "name", "title")
        if not (description or caption):
            return None
        return {
            **candidate,
            **common,
            "source": _first_text(candidate, "source") or "glm_ocr_layout+vlm_ocr",
            "caption": caption,
            "description": description or caption,
        }
    return None


def validate_recovered_object(block: Dict[str, Any], candidate: Any) -> Tuple[str, Dict[str, Any]]:
    """Validate a crop response without modifying content or leaking it in diagnostics."""
    if not isinstance(candidate, dict):
        return "response_invalid", {"candidate_chars": 0}
    if not candidate:
        return "response_empty", {"candidate_chars": 0}
    kind = block.get("type")
    value = candidate.get({"table": "markdown", "formula": "latex", "figure": "description"}.get(kind, ""))
    content = value.strip() if isinstance(value, str) else ""
    shape: Dict[str, Any] = {"candidate_chars": len(content)}
    if kind == "table":
        for tag in ("table", "tr", "td", "th"):
            shape[f"{tag}_open_count"] = len(re.findall(rf"<{tag}\b[^>]*>", content, re.IGNORECASE))
            shape[f"{tag}_close_count"] = len(re.findall(rf"</{tag}\s*>", content, re.IGNORECASE))
    if candidate.get("layout_id") != block.get("layout_id"):
        return "layout_id_mismatch", shape
    if candidate.get("type") != kind:
        return "object_type_mismatch", shape
    if candidate.get("status") != "EXTRACTED" or candidate.get("complete") is not True:
        return "provider_reported_incomplete", shape
    if not content or content.strip("[]()<> \n\t").lower() in {"unreadable", "unknown", "n/a", "null", "none"}:
        return f"{kind}_content_empty", shape
    if kind == "table":
        if shape["table_open_count"]:
            if _html_table_incomplete(content):
                return "table_html_unclosed", shape
            if shape["table_open_count"] != 1:
                return "table_count_invalid", shape
            parser = _TableStructureParser()
            try:
                parser.feed(content)
                parser.close()
            except Exception:
                return "table_html_invalid", shape
            if parser.invalid or parser.stack:
                return "table_html_invalid", shape
            if not shape["tr_open_count"] or not (shape["td_open_count"] + shape["th_open_count"]):
                return "table_cells_missing", shape
        else:
            lines = [line.strip() for line in content.splitlines() if line.strip()]
            rows = [re.split(r"(?<!\\)\|", line.strip("|")) for line in lines]
            if (len(rows) < 2 or not all("|" in line for line in lines)
                    or not all(re.fullmatch(r"\s*:?-{3,}:?\s*", cell) for cell in rows[1])
                    or any(len(row) != len(rows[0]) for row in rows)):
                return "table_markdown_invalid", shape
    elif kind == "formula":
        depth = 0
        for brace in re.findall(r"(?<!\\)[{}]", content):
            depth += 1 if brace == "{" else -1
            if depth < 0:
                return "formula_unbalanced", shape
        environments: List[str] = []
        for action, name in re.findall(r"\\(begin|end)\{([^}]+)\}", content):
            if action == "begin":
                environments.append(name)
            elif not environments or environments.pop() != name:
                return "formula_unbalanced", shape
        if depth or environments:
            return "formula_unbalanced", shape
    elif kind == "figure":
        if re.fullmatch(r"(?:fig(?:ure)?\.?|图)\s*[\w.-]+", content, re.IGNORECASE):
            return "figure_content_empty", shape
    else:
        return "unsupported_object_type", shape
    return "", shape


class _TableStructureParser(HTMLParser):
    """Reject incomplete/misnested table structure; never auto-close model output."""
    parents = {
        "table": {None}, "thead": {"table"}, "tbody": {"table"}, "tfoot": {"table"},
        "tr": {"table", "thead", "tbody", "tfoot"}, "td": {"tr"}, "th": {"tr"},
        "caption": {"table"}, "colgroup": {"table"},
    }

    def __init__(self) -> None:
        super().__init__()
        self.stack: List[str] = []
        self.invalid = False

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in {"script", "iframe", "object", "embed", "img", "svg", "style", "link", "meta"}:
            self.invalid = True
        if any(name.lower().startswith("on") for name, _ in attrs):
            self.invalid = True
        if tag in self.parents:
            parent = self.stack[-1] if self.stack else None
            if parent not in self.parents[tag]:
                self.invalid = True
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in self.parents:
            if not self.stack or self.stack[-1] != tag:
                self.invalid = True
            else:
                self.stack.pop()

    def handle_startendtag(self, tag: str, attrs: Any) -> None:
        if tag in self.parents:
            self.invalid = True
        else:
            self.handle_starttag(tag, attrs)


def _payload_common(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "source": "glm_ocr_layout",
        "layout_id": entry["layout_id"],
        "source_block_index": entry.get("source_block_index"),
        "reading_order": entry["reading_order"],
        "bbox": entry.get("bbox") or [],
        "bbox_space": "normalized_page",
        "status": "EXTRACTED",
    }


def _match_recovery_entry(
    layout: List[Dict[str, Any]],
    candidate: Dict[str, Any],
    object_type: str,
    used_layout_ids: set[str],
) -> Optional[Dict[str, Any]]:
    candidates = [
        item
        for item in layout
        if item.get("type") == object_type
        and item.get("status") == "FAILED"
        and str(item.get("layout_id") or "") not in used_layout_ids
    ]
    layout_id = str(candidate.get("layout_id") or "")
    if layout_id:
        for item in candidates:
            if str(item.get("layout_id")) == layout_id:
                return item
        return None
    source_index = candidate.get("source_block_index", candidate.get("block_index", candidate.get("index")))
    if source_index is not None:
        for item in candidates:
            if str(item.get("source_block_index")) == str(source_index):
                return item
        return None
    bbox = candidate.get("bbox")
    if isinstance(bbox, list) and len(bbox) == 4:
        for item in candidates:
            if _bbox_close(item.get("bbox") or [], bbox):
                return item
    return None


def _bbox_close(left: List[Any], right: List[Any]) -> bool:
    if len(left) != 4 or len(right) != 4:
        return False
    try:
        return all(abs(float(a) - float(b)) <= 0.001 for a, b in zip(left, right))
    except (TypeError, ValueError):
        return False


def _bbox_error_code(value: Any) -> str:
    if value is None or value == []:
        return "layout_bbox_missing"
    return "layout_bbox_invalid"


def _payload_content(object_type: str, payload: Dict[str, Any]) -> str:
    if object_type == "table":
        return str(payload.get("markdown") or "")
    if object_type == "formula":
        return str(payload.get("latex") or "")
    return str(payload.get("description") or payload.get("caption") or "")


def _collection_for_type(object_type: str) -> str:
    return {"table": "tables", "formula": "formulas", "figure": "figures"}[object_type]


def _markdown_from_layout(layout: List[Dict[str, Any]]) -> str:
    return "\n\n".join(
        str(item.get("content") or "").strip()
        for item in layout
        if str(item.get("content") or "").strip()
    )


def _error(code: str, stage: str, retryable: bool) -> Dict[str, Any]:
    return {"code": code, "stage": stage, "retryable": retryable}


def _first_text(data: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _positive_number(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if number > 0 else 0.0


def _recovery_ref(candidate: Dict[str, Any], collection: str, index: int) -> str:
    return str(
        candidate.get("layout_id")
        or candidate.get("source_block_index")
        or candidate.get("block_index")
        or f"{collection}:{index}"
    )


def _unique(values: List[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out
