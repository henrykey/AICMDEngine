from __future__ import annotations

import re
import copy
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
        # Complete source HTML is stronger structural evidence than a formula label.
        content = str(block.get("content") or "").strip()
        if object_type == "formula" and re.fullmatch(r"(?is)<table\b[^>]*>.*</table>", content):
            parser = _TableStructureParser()
            parser.feed(content)
            if not parser.invalid and not parser.stack and len(re.findall(r"(?i)<table\b", content)) == 1:
                object_type = "table"
        if object_type == "formula" and is_formula_body_text(block.get("content"), block.get("layout_type")):
            object_type = "text"
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
        if object_type == "table":
            entry["title"] = _table_caption_before(block, layout)
        error = _entry_error(entry, str(block.get("bbox_error") or ""))
        if error:
            entry["error"] = error
            if object_type == "figure" and error["code"] == "layout_figure_content_missing":
                # Geometry establishes an object even when its semantics still need recovery.
                payloads["figures"].append({**_payload_from_entry(entry, block),
                    "status": "FAILED", "content_status": "geometry_only",
                    "description": "", "semantic_summary": "", "semantic_status": "missing",
                    "missing_fields": ["description"]})
        else:
            if object_type == "table":
                _normalize_table_math(entry)
                if entry["content"] != content:
                    markdown = markdown.replace(content, entry["content"])
            payload = _payload_from_entry(entry, block)
            if payload is None:
                entry["error"] = _error(f"layout_{object_type}_content_missing", "layout_content", True)
            else:
                entry["status"] = "EXTRACTED"
                entry["review_required"] = bool(entry.get("manualReviewRequired"))
                if object_type != "text":
                    payloads[_collection_for_type(object_type)].append(payload)
        layout.append(entry)

    _bind_formula_numbers(payloads["formulas"], blocks, markdown)

    return {
        "layout_status": "EXTRACTED",
        "layout_error": "",
        "source_page_width": page_width,
        "source_page_height": page_height,
        "source_bbox_space": "pixel_page",
        "source_page_index": 0,
        "layout": layout,
        "blocks": blocks,
        "payloads": payloads,
        "markdown": markdown or _markdown_from_layout(layout),
        "unmatched_recovery_refs": [],
    }


# Only explicit equation labels, never prose references or inferred sequences.
_FORMULA_NUMBER = r"[A-Za-z]?\s*[-.]?\s*\d+(?:\s*[-.]\s*\d+)*"
_NUMBER_SUFFIX = re.compile(
    rf"(?:\\tag\*?\{{\s*({_FORMULA_NUMBER})\s*\}}|"
    rf"[（(]\s*(?:\\text\{{\s*)?({_FORMULA_NUMBER})(?:\s*\}})?\s*[）)])\s*$"
)
_MATH_BLOCK = re.compile(r"\$\$[\s\S]*?\$\$|(?<!\$)\$(?!\$)[^\n$]+\$(?!\$)|\\\[[\s\S]*?\\\]")


def _formula_label(text: str) -> Tuple[str, str]:
    # Work on a comparison copy; the original LaTeX is never rewritten.
    text = text.strip()
    for left, right in (("$$", "$$"), ("$", "$"), (r"\[", r"\]")):
        if text.startswith(left) and text.endswith(right):
            text = text[len(left):-len(right)].strip()
            break
    match = _NUMBER_SUFFIX.search(text)
    if not match:
        return text, ""
    body = text[:match.start()].strip()
    if match.group(2) and body and (
        not text[match.start()-1].isspace() or body[-1] in "=+-*/^_<>,"
    ):
        return text, ""
    body = re.sub(r"(?:\\(?:quad|qquad)|\\[,;! ])\s*$", "", body).strip()
    return body, re.sub(r"\s+", "", match.group(1) or match.group(2))


def _formula_key(text: str) -> str:
    body, _ = _formula_label(text)
    body, _ = _formula_label(body)
    return re.sub(r"\s+", "", body)


def _bind_formula_numbers(formulas: List[Dict[str, Any]], blocks: List[Dict[str, Any]], markdown: str) -> None:
    """Recover labels from the same OCR response, with unique content/geometry binding."""
    numbered_math: Dict[str, List[str]] = {}
    for match in _MATH_BLOCK.finditer(markdown):
        math = match.group()
        _, number = _formula_label(math)
        if not number:
            # An outside label must immediately follow the closing math delimiter.
            suffix = re.match(rf"[ \t]*([（(]\s*{_FORMULA_NUMBER}\s*[）)])", markdown[match.end():])
            if suffix:
                _, number = _formula_label(suffix.group(1))
        key = _formula_key(math)
        numbered_math.setdefault(key, []).append(number)

    keys = [_formula_key(str(f.get("latex") or "")) for f in formulas]
    right_labels: Dict[int, List[str]] = {}
    for block in blocks:
        if canonical_layout_type(block.get("layout_type")) != "text":
            continue
        body, number = _formula_label(str(block.get("content") or ""))
        box = block.get("bbox") or []
        if body or not number or len(box) != 4:
            continue
        matches = []
        for i, formula in enumerate(formulas):
            bounds = formula.get("bbox") or []
            if len(bounds) != 4 or box[0] < bounds[2]:
                continue
            overlap = min(box[3], bounds[3]) - max(box[1], bounds[1])
            if overlap >= 0.5 * min(box[3] - box[1], bounds[3] - bounds[1]):
                matches.append(i)
        if len(matches) == 1:
            right_labels.setdefault(matches[0], []).append(number)

    for i, formula in enumerate(formulas):
        if formula.get("formula_no"):
            continue
        _, own_number = _formula_label(str(formula.get("latex") or ""))
        candidates = [own_number] if own_number else []
        numbers = numbered_math.get(keys[i], [])
        if keys.count(keys[i]) == 1 and len(numbers) == 1 and numbers[0]:
            candidates.append(numbers[0])
        candidates.extend(right_labels.get(i, []))
        if candidates and len(set(candidates)) == 1:
            formula["formula_no"] = candidates[0]


def _table_caption_before(block: Dict[str, Any], preceding: List[Dict[str, Any]]) -> str:
    """Bind only an adjacent caption above this table, never across another object."""
    bbox = block.get("bbox") or []
    for item in reversed(preceding):
        if item.get("type") != "text":
            break
        text = str(item.get("content") or "").strip()
        if not text:
            continue
        caption_bbox = item.get("bbox") or []
        is_caption = item.get("layout_type") == "table_caption" or re.match(
            r"^(?:表\s*[A-Za-z0-9０-９]|Table\s+[A-Za-z0-9])", text, re.IGNORECASE
        )
        if (is_caption and len(bbox) == len(caption_bbox) == 4
                and caption_bbox[3] <= bbox[1]
                and min(caption_bbox[2], bbox[2]) > max(caption_bbox[0], bbox[0])):
            return text
        break
    return ""


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
        and ((item.get("status") == "FAILED"
              and (item.get("error") or {}).get("stage") == "layout_content")
             or "table_math_delimiter_unresolved" in item.get("warnings", []))
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
            if object_type == "figure":
                payload.pop("content_status", None)
            if object_type == "formula" and is_formula_body_text(payload.get("latex")):
                # A recovered variable explanation belongs to body text, not an object array.
                entry["type"] = "text"
            else:
                existing = outcome["payloads"][collection]
                retained = [i for i, value in enumerate(existing)
                            if value.get("layout_id") == entry["layout_id"]
                            and (value.get("content_status") == "geometry_only"
                                 or (object_type == "table" and "table_math_delimiter_unresolved" in entry.get("warnings", [])))]
                if len(retained) == 1:
                    existing[retained[0]] = payload
                else:
                    existing.append(payload)
            entry["status"] = "EXTRACTED"
            entry["review_required"] = False
            original_content = str(entry.get("content") or "")
            entry["content"] = _payload_content(object_type, payload)
            if object_type == "table":
                if "table_math_delimiter_unresolved" in entry.get("warnings", []):
                    entry["warnings"] = [w for w in entry["warnings"] if w != "table_math_delimiter_unresolved"]
                    if not entry["warnings"]:
                        entry.pop("degraded", None)
                        entry.pop("manualReviewRequired", None)
                _normalize_table_math(entry)
                payload["markdown"] = entry["content"]
                payload.update(_table_math_metadata(entry))
                markdown = str(outcome.get("markdown") or "")
                if original_content and original_content != entry["content"] and original_content in markdown:
                    outcome["markdown"] = markdown.replace(original_content, entry["content"], 1)
            entry["error"] = None
            used_layout_ids.add(str(entry["layout_id"]))
    outcome["unmatched_recovery_refs"] = _unique(unmatched)


def _validated_cell_figure_ids(output_elements, layout):
    """Derived figures belong to a validated table cell, not a second page layout block."""
    payloads = copy.deepcopy(output_elements)
    attach_object_relationships(payloads, None)
    table_ids = [item.get("layout_id") for item in layout
                 if item.get("type") == "table" and item.get("status") == "EXTRACTED"]
    figures = payloads.get("figures", [])
    accepted = set()
    for figure in figures:
        identity = figure.get("layout_id")
        declared = figure.get("cell_image_source") or {}
        relation = figure.get("parent_relation") or {}
        asset = figure.get("image_asset") or {}
        if (figure.get("source") != "source_cell_image_region" or not identity
                or sum(f.get("layout_id") == identity for f in figures) != 1
                or relation.get("status") != "resolved"
                or any(declared.get(key) != relation.get(key) for key in ("table_layout_id", "cell_source"))
                or table_ids.count(declared.get("table_layout_id")) != 1
                or asset.get("status") != "available" or asset.get("layout_id") != identity):
            continue
        matches = []
        for table in payloads.get("tables", []):
            if table.get("layout_id") != declared.get("table_layout_id"):
                continue
            for cell in table.get("source_cells", []):
                cell_ref = f"r{cell.get('row')}c{cell.get('col')}"
                for region in cell.get("image_regions", []):
                    expected = f"{table['layout_id']}:{cell_ref}:image:{region.get('image_id')}"
                    if (identity == expected and cell_ref == declared.get("cell_source")
                            and region.get("bbox") == figure.get("bbox")
                            and region.get("bbox_space") == "normalized_page"):
                        matches.append(expected)
        if len(matches) == 1:
            accepted.add(identity)
    return accepted


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
    cell_figure_ids = _validated_cell_figure_ids(output_elements, layout)
    for collection in ("tables", "formulas", "figures"):
        values = output_elements.get(collection)
        if not isinstance(values, list):
            continue
        for index, payload in enumerate(values):
            layout_id = str(payload.get("layout_id") or "") if isinstance(payload, dict) else ""
            if collection == "figures" and layout_id in cell_figure_ids and layout_id not in valid_layout_ids:
                continue
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
            retained_figure = (item.get("type") == "figure" and item.get("status") == "FAILED"
                               and (item.get("error") or {}).get("code") == "layout_figure_content_missing"
                               and len(refs) == 1 and refs[0][0] == "figures")
            if retained_figure:
                collection, index = refs[0]
                payload = output_elements[collection][index]
                retained_figure = (payload.get("content_status") == "geometry_only"
                                   and payload.get("bbox") == item.get("bbox")
                                   and payload.get("bbox_space") == "normalized_page"
                                   and (payload.get("semantic_status") == "missing"
                                        or (payload.get("semantic_status") == "complete"
                                            and bool(str(payload.get("description") or "").strip()))))
            if retained_figure:
                item["payload_ref"] = {"collection": collection, "index": index}
                asset = payload.get("image_asset") or {}
                if asset.get("status") == "available" and asset.get("layout_id") == layout_id:
                    # A page-owned crop completes source coverage, independently of its description.
                    item["status"] = "EXTRACTED"
                    item["error"] = None
                    if payload.get("semantic_status") == "complete" and not payload.get("missing_fields"):
                        item["review_required"] = False
                    payload["status"] = "EXTRACTED"
            else:
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
            item["review_required"] = bool(item.get("manualReviewRequired"))
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
        "complete": accounted_for and failed == 0 and not any(item.get("review_required") for item in layout),
    }


def is_formula_body_text(content: Any, layout_type: Any = "") -> bool:
    """Demote explicit inline math, variable atoms and definition prose; keep main equations."""
    if str(layout_type or "").lower() == "inline_formula":
        return True
    text = str(content or "").strip()
    if not text:
        return False  # unknown content still needs the existing structural recovery
    text = re.sub(r"\\[()[\]]|\$", "", text).strip()
    text = re.sub(r"\\(?:mathrm|mathbf|mathit|text)\{([^{}]*)\}", r"\1", text).strip()
    if re.fullmatch(r"(?:Pa|kPa|MPa|GPa|mm|cm|kg|kN|Hz|rad|mol)", text):
        return True
    if re.match(r"(?i)^(?:式中|其中|注[:：]|where\b)", text):
        return True
    atom = r"(?:\\(?:Delta|delta)\s*)?(?:\\[A-Za-z]+|[A-Za-z\u0370-\u03ff])(?:\s*[_^]\s*(?:\{[^{}]+\}|[A-Za-z0-9]))*"
    if re.fullmatch(atom, text):
        return True
    # A symbol followed by prose is a definition, unlike F=ma or a standalone integral.
    return bool(re.match(
        rf"(?i)^{atom}\s*(?:[—–:：]+\s*|(?:为|表示|是)\s*|(?:is|denotes|represents)\s+).+", text
    ))


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
    if entry.get("type") == "table" and _markdown_table_has_synthetic_columns(str(entry.get("content") or "")):
        return _error("layout_table_synthetic_columns", "layout_content", True)
    return None


def _html_table_incomplete(content: str) -> bool:
    opening = re.search(r"<table\b", content, flags=re.IGNORECASE)
    if opening is None:
        return False
    return re.search(r"</table\s*>", content[opening.end() :], flags=re.IGNORECASE) is None


def _markdown_table_has_synthetic_columns(content: str) -> bool:
    """Reject a generated run such as Col3, Col4 that masks a missing table schema."""
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if len(lines) < 2 or "|" not in lines[0]:
        return False
    headers = [cell.strip() for cell in re.split(r"(?<!\\)\|", lines[0].strip("|"))]
    run = 0
    for header in headers:
        if re.fullmatch(r"(?:col|column)[ _-]?\d+", header, flags=re.IGNORECASE):
            run += 1
            if run >= 2:
                return True
        else:
            run = 0
    return False


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
            **_table_math_metadata(entry),
            # Preserve supplied cell evidence through the layout route. Coordinates
            # retain their declared space; no bounds or confidence are invented.
            **{key: raw[key] for key in (
                "source_cells", "cell_status", "source_cell_row_offset", "contains_images", "image_unresolved"
            ) if key in raw},
            # A layout-bound caption is the only reliable title source.  Model/raw
            # metadata may belong to a preceding table on the same page.
            "title": entry.get("title") or "",
            "markdown": content,
            "description": _first_text(raw, "description", "semanticDesc", "summary"),
            "context": _first_text(raw, "context", "surrounding_text"),
        }
    if object_type == "formula":
        return {
            **common,
            "latex": content,
            "formula_name": _first_text(raw, "formula_name", "name", "title"),
            "formula_no": _first_text(raw, "formula_no", "number"),
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
            "title": entry.get("title") or "",
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
                shape["table_unsafe_tags"] = sorted(set(re.findall(
                    r"<(script|iframe|object|embed|img|svg|style|link|meta)\b", content, re.IGNORECASE)))
                shape["table_unclosed_structure"] = bool(parser.stack)
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
        probe = {"content": content}
        _normalize_table_math(probe)
        if "table_math_delimiter_unresolved" in probe.get("warnings", []):
            return "table_math_delimiter_unresolved", shape
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


def _table_math_metadata(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {key: entry[key] for key in (
        "original_content", "warnings", "degraded", "manualReviewRequired"
    ) if key in entry}


def _normalize_math_cell(cell: str) -> Tuple[str, bool]:
    # Escaped dollars are text. Match runs so a stray $$ is never treated as $.
    dollars = [m for m in re.finditer(r"\$+", cell)
               if (len(cell[:m.start()]) - len(cell[:m.start()].rstrip("\\"))) % 2 == 0]
    if not dollars:
        return cell, False
    if len(dollars) == 1 and dollars[0].group() == "$":
        text = cell.strip()
        body = text[1:] if text.startswith("$") else text[:-1] if text.endswith("$") else ""
        # A complete simple scalar with an explicit script is unambiguous here;
        # prose, HTML, commands, incomplete braces and bare currency are not.
        atom = r"(?:\d+(?:\.\d+)?|[A-Za-z])"
        script = r"[_^](?:\{[A-Za-z0-9*†‡]+\}|[A-Za-z0-9*†‡])"
        if re.fullmatch(rf"[≤≥<>+−-]?{atom}(?:[~～+−-]{atom})*(?:{script})+", body):
            return cell.replace(text, "$" + body + "$", 1), False
    # Leave ordinary prices alone, including prices in prose.
    if not re.search(r"[_^{}]", cell) and all(
        m.group() == "$" and re.match(r"\d+(?:[.,]\d+)*(?:\b|$)", cell[m.end():])
        for m in dollars
    ):
        return cell, False
    valid = len(dollars) % 2 == 0 and all(
        left.group() == right.group() and len(left.group()) <= 2
        and cell[left.end():right.start()].strip()
        for left, right in zip(dollars[::2], dollars[1::2])
    )
    if valid:
        for left, right in zip(dollars[::2], dollars[1::2]):
            reason, _ = validate_recovered_object({"layout_id": "cell", "type": "formula"},
                {"layout_id": "cell", "type": "formula", "status": "EXTRACTED", "complete": True,
                 "latex": cell[left.end():right.start()]})
            if reason:
                valid = False
                break
    return cell, not valid


def _normalize_table_math(entry: Dict[str, Any]) -> None:
    original = str(entry.get("content") or "")
    if "$" not in original:
        return
    parser = _TableMathParser(original)
    parser.feed(original)
    parser.close()
    # Reuse structural validation; never let malformed/nested HTML join cells.
    if parser.invalid or parser.stack or not parser.spans:
        return
    content = original
    review = False
    for start, end in reversed(parser.spans):
        normalized, unresolved = _normalize_math_cell(original[start:end])
        content = content[:start] + normalized + content[end:]
        review = review or unresolved
    if content != original or review:
        entry.setdefault("original_content", original)
        entry["content"] = content
        entry["warnings"] = [*entry.get("warnings", []),
                             "table_math_delimiter_unresolved" if review else "table_math_delimiter_repaired"]
        if review:
            entry["degraded"] = True
            entry["manualReviewRequired"] = True
            entry["review_required"] = True


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


class _TableMathParser(_TableStructureParser):
    """Locate cell interiors without reserializing tags, attributes or entities."""

    def __init__(self, content: str) -> None:
        super().__init__()
        self.line_offsets = [0, *[m.end() for m in re.finditer("\n", content)]]
        self.spans: List[Tuple[int, int]] = []
        self.cell_start = 0

    def _offset(self) -> int:
        line, column = self.getpos()
        return self.line_offsets[line - 1] + column

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        super().handle_starttag(tag, attrs)
        if tag in {"td", "th"}:
            self.cell_start = self._offset() + len(self.get_starttag_text())

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"}:
            self.spans.append((self.cell_start, self._offset()))
        super().handle_endtag(tag)


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
        and (item.get("status") == "FAILED" or "table_math_delimiter_unresolved" in item.get("warnings", []))
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



def reliable_normalized_bbox(item):
    bbox = item.get("bbox")
    return (item.get("bbox_space") == "normalized_page" and isinstance(bbox, list) and len(bbox) == 4
            and all(isinstance(x, (int, float)) and not isinstance(x, bool) and 0 <= x <= 1 for x in bbox)
            and bbox[0] < bbox[2] and bbox[1] < bbox[3])


def attach_object_relationships(payloads, page_no):
    """Only unique geometric containment establishes parent/cell identity."""
    def contains(parent, child):
        a, b = parent["bbox"], child["bbox"]
        return a[0] <= b[0] and a[1] <= b[1] and a[2] >= b[2] and a[3] >= b[3]
    tables = [t for t in payloads.get("tables", []) if t.get("layout_id") and reliable_normalized_bbox(t)]
    for item in payloads.get("formulas", []) + payloads.get("figures", []):
        relation = {"status": "unresolved", "page_no": page_no, "bbox_space": "normalized_page"}
        item["parent_relation"] = relation
        if not reliable_normalized_bbox(item):
            relation["reason"] = "unreliable_object_bbox"
            continue
        parents = [t for t in tables if contains(t, item)]
        if len(parents) != 1:
            relation["reason"] = "ambiguous_parent_table" if parents else "no_containing_table"
            continue
        table = parents[0]
        relation["table_layout_id"] = table["layout_id"]
        cells = [c for c in table.get("source_cells", []) if reliable_normalized_bbox(c) and contains(c, item)
                 and all(isinstance(c.get(k), int) and not isinstance(c[k], bool) and c[k] >= 0 for k in ("row", "col"))]
        if len(cells) != 1:
            relation["reason"] = "ambiguous_parent_cell" if cells else "missing_cell_geometry"
            continue
        cell = cells[0]
        relation.update(status="resolved", cell_source=f"r{cell['row']}c{cell['col']}", evidence="unique_bbox_containment")



def contained_table_formulas(table, sources):
    """Bind delimited formulas inside each source cell, never across cells."""
    formulas, evidence = [], {}
    for ref, cell in sources.items():
        raw = cell.get("raw_html", "")
        for match in _MATH_BLOCK.finditer(raw):
            _, number = _formula_label(match.group())
            evidence[ref] = {"raw_html": raw}
            formulas.append({"parent_table_layout_id": table["layout_id"], "cell_source": ref,
                             "source_ref": f"{table['layout_id']}:{ref}:{match.start()}:{match.end()}",
                             "source_field": "raw_html", "start": match.start(), "end": match.end(),
                             "latex": match.group(), "formula_no": number, "formula_name": "",
                             "description": "", "semantic_status": "missing",
                             "missing_fields": ["formula_name", "description"]})
    return formulas, evidence
