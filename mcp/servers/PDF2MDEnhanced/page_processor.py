from __future__ import annotations

import hashlib
import json
import logging
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import fitz

from .vlm_client import DynamicVLMClient

logger = logging.getLogger(__name__)


def process_page(
    source_path: str,
    page_no: int,
    policy: str,
    vlm_config: Optional[Dict[str, Any]],
    routing_config: Optional[Dict[str, Any]],
    prev_context: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    rc = _routing_defaults(routing_config)
    table_placeholders: list[str] = []
    source_page_no = int(rc.get("source_page_no", 0) or 0)
    display_page_no = source_page_no if source_page_no > 0 else int(page_no)

    doc = fitz.open(source_path)
    if page_no < 1 or page_no > len(doc):
        doc.close()
        raise ValueError(f"page_no out of range: {page_no} / {len(doc)}")

    page = doc[page_no - 1]
    metrics = _collect_metrics(page)
    mode, reasons = _decide_mode(policy, metrics, rc)
    logger.info(
        "process_page decision: page_no=%s mode=%s reasons=%s text_chars=%s image_ratio=%s formula_score=%s table_score=%s",
        page_no,
        mode,
        reasons,
        metrics.get("text_chars"),
        metrics.get("image_area_ratio"),
        metrics.get("formula_score"),
        metrics.get("table_score"),
    )

    with tempfile.TemporaryDirectory(prefix="pdf2md_enh_page_") as work_dir:
        image_path = _render_page_image(
            doc,
            page_no,
            Path(work_dir),
            dpi=rc["render_dpi"],
            rotate_deg=rc["render_rotate_deg"],
        )

        vlm = DynamicVLMClient(vlm_config)
        logger.info(
            "process_page vlm_client: enabled=%s provider=%s model=%s base_url=%s timeout=%s max_retries=%s",
            vlm.enabled,
            vlm.provider,
            vlm.model,
            vlm.base_url,
            vlm.timeout_sec,
            vlm.max_retries,
        )
        vlm_calls = 0

        layout_probe = None
        if rc.get("debug_layout_probe"):
            try:
                layout_probe = vlm.recognize_layout(str(image_path))
            except Exception as exc:
                layout_probe = {"error": str(exc)}

        if mode == "DIRECT":
            markdown = _build_direct_markdown(page)
            structured = {"formulas": [], "tables": [], "figures": []}
            rag_page_text = ""
        elif mode == "FULL_VLM":
            rag_page_text = ""
            try:
                dual = vlm.full_page_dual_output(str(image_path))
                markdown = _clean_markdown(dual.get("render") or "")
                rag_obj = dual.get("rag") or {}
                rag_page_text = str(rag_obj.get("page_text") or "").strip()
                structured = _normalize_structured(rag_obj.get("elements"))
                vlm_calls += 1
                # Some models return syntactically valid dual JSON but empty render.
                # Treat as recoverable and trigger markdown fallback when enabled.
                if not markdown.strip():
                    if rc.get("full_vlm_retry_markdown", False):
                        markdown = _clean_markdown(vlm.full_page_markdown(str(image_path)))
                        vlm_calls += 1
                    if not markdown.strip():
                        raise RuntimeError("full_vlm_empty_render")
            except Exception as err:
                logger.warning("FULL_VLM dual-output failed, fallback to split calls: %r", err)
                # Default strategy: one VLM call per page in FULL_VLM.
                # If dual-output parsing fails, avoid second VLM call by default.
                markdown = ""
                if rc.get("full_vlm_retry_markdown", False):
                    markdown = _clean_markdown(vlm.full_page_markdown(str(image_path)))
                    vlm_calls += 1
                # Optional legacy split behavior for debugging only.
                if rc.get("full_vlm_split_extract", False):
                    structured = vlm.extract_region_structured(str(image_path))
                    vlm_calls += 1
                else:
                    structured = {"formulas": [], "tables": [], "figures": []}
                # Do not silently return empty success pages.
                if not markdown.strip():
                    raise RuntimeError("full_vlm_no_render_recovered")
        else:  # REGION_VLM
            markdown = _clean_markdown(page.get_text("text") or "")
            structured = _normalize_structured(vlm.extract_region_structured(str(image_path)))
            vlm_calls += 1
            markdown = _merge_region_vlm_markdown(markdown, structured)
            rag_page_text = ""

    doc.close()

    markdown = _rebuild_render_tables_from_structured(markdown, structured)
    if rc.get("render_cleanup_with_llm", True) and _has_table_residual_noise(markdown) and vlm.enabled:
        try:
            cleaned = _clean_markdown(vlm.cleanup_markdown_table_noise(markdown))
            if cleaned and _extract_markdown_tables(cleaned):
                markdown = cleaned
                vlm_calls += 1
        except Exception as exc:
            logger.warning("render cleanup with llm failed: %r", exc)
    markdown, table_placeholders = _replace_large_tables_with_placeholders(markdown, display_page_no, rc)
    current_section = _extract_section(markdown) or (prev_context or {}).get("current_section")
    next_context = {
        "current_section": current_section,
        "carry_over_text": markdown[-240:] if markdown else "",
        "open_table": None,
        "open_formula": None,
    }

    # Table reliability strategy:
    # prefer parsing from render markdown; fallback to VLM tables; final fallback to placeholders.
    structured["tables"] = _select_rag_tables(markdown, structured.get("tables") or [])
    rag_content = _build_rag_content(markdown, structured, rag_page_text=rag_page_text)
    table_source = _detect_table_source(markdown, structured)

    rag_obj = {
        "content": rag_content,
        "elements": structured,
    }
    if _should_emit_chunks(rc):
        rag_obj["chunks"] = _build_chunks(rag_content, chunk_size=rc["chunk_size"])

    result = {
        "task_page_id": hashlib.sha1(f"{source_path}:{page_no}".encode("utf-8")).hexdigest()[:16],
        "page_no": page_no,
        "decision": {
            "mode": mode,
            "reasons": reasons,
            "metrics": metrics,
            "vlm_calls": vlm_calls,
            "source_page_no": display_page_no,
            "table_source": table_source,
            "table_placeholder_count": len(table_placeholders),
            "layout_probe": layout_probe,
        },
        "render": {"markdown": markdown},
        "rag": rag_obj,
        "elements": {
            "tables": structured.get("tables", []),
            "formulas": structured.get("formulas", []),
            "figures": structured.get("figures", []),
        },
        "next_context": next_context,
        "page_type": "normal",
    }
    return result


def _routing_defaults(cfg: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    c = cfg or {}
    return {
        "text_chars_min": int(c.get("text_chars_min", 80)),
        "image_area_ratio_full_vlm": float(c.get("image_area_ratio_full_vlm", 0.55)),
        "noise_ratio_full_vlm": float(c.get("noise_ratio_full_vlm", 0.30)),
        "formula_score_region_vlm": float(c.get("formula_score_region_vlm", 0.12)),
        "table_score_region_vlm": float(c.get("table_score_region_vlm", 0.20)),
        "render_dpi": int(c.get("render_dpi", 220)),
        "render_rotate_deg": int(c.get("render_rotate_deg", 0)),
        "source_page_no": int(c.get("source_page_no", 0) or 0),
        "chunk_size": int(c.get("chunk_size", 700)),
        "enable_chunks": bool(c.get("enable_chunks", False)),
        "chunk_policy": str(c.get("chunk_policy", "disabled")),
        "task_total_pages": int(c.get("__task_total_pages", 1)),
        "debug_layout_probe": bool(c.get("debug_layout_probe", False)),
        "full_vlm_split_extract": bool(c.get("full_vlm_split_extract", False)),
        # Default ON: complex pages often return invalid/empty dual JSON.
        # Markdown retry avoids hard-failing pages when render can still be recovered.
        "full_vlm_retry_markdown": bool(c.get("full_vlm_retry_markdown", True)),
        "render_cleanup_with_llm": bool(c.get("render_cleanup_with_llm", True)),
        "large_table_placeholder_enabled": bool(c.get("large_table_placeholder_enabled", True)),
        "large_table_min_cols": int(c.get("large_table_min_cols", 12)),
        "large_table_min_rows": int(c.get("large_table_min_rows", 16)),
        "large_table_min_cells": int(c.get("large_table_min_cells", 180)),
    }


def _collect_metrics(page: fitz.Page) -> Dict[str, Any]:
    page_area = float(page.rect.width * page.rect.height) or 1.0
    text = page.get_text("text") or ""
    text_chars = len(re.sub(r"\s+", "", text))
    text_blocks = len(page.get_text("blocks") or [])

    image_area = 0.0
    for img in page.get_images(full=True):
        xref = img[0]
        try:
            rects = page.get_image_rects(xref)
            image_area += sum(float(r.width * r.height) for r in rects)
        except Exception:
            continue

    image_area_ratio = max(0.0, min(1.0, image_area / page_area))

    drawings = page.get_drawings() or []
    drawing_density = len(drawings) / max(page_area, 1.0) * 100000.0

    noise_chars = len(re.findall(r"[\uFFFD�]", text))
    noise_ratio = noise_chars / max(len(text), 1)

    formula_hits = len(re.findall(r"[=∑∫√^_±≤≥≈πλμΔ]\s*", text))
    formula_block_hits = 0
    try:
        raw = page.get_text("dict") or {}
        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue
            line_texts = []
            for line in block.get("lines", []):
                spans = [str(span.get("text") or "").strip() for span in line.get("spans", [])]
                joined = " ".join([s for s in spans if s]).strip()
                if joined:
                    line_texts.append(joined)
            if not line_texts:
                continue
            short_lines = sum(1 for item in line_texts if len(re.sub(r"\s+", "", item)) <= 3)
            symbolic_hits = sum(
                len(re.findall(r"[=∑∫√^_±≤≥≈πλμΔση\[\]\(\)/]", item))
                for item in line_texts
            )
            if short_lines >= 4 and symbolic_hits >= 5:
                formula_block_hits += 1
    except Exception:
        formula_block_hits = 0

    formula_score = min(1.0, (formula_hits + formula_block_hits * 10) / 40.0)

    table_line_hits = 0
    for line in text.splitlines():
        if re.search(r"\S+\s{2,}\S+\s{2,}\S+", line):
            table_line_hits += 1
        if "|" in line:
            table_line_hits += 1
    table_score = min(1.0, table_line_hits / 20.0)
    native_table_count = 0
    try:
        finder = page.find_tables()
        native_table_count = len(list(finder.tables)) if finder else 0
    except Exception:
        native_table_count = 0

    return {
        "text_chars": text_chars,
        "text_blocks": text_blocks,
        "image_area_ratio": round(image_area_ratio, 4),
        "drawing_density": round(drawing_density, 4),
        "noise_ratio": round(noise_ratio, 4),
        "formula_score": round(formula_score, 4),
        "formula_block_hits": formula_block_hits,
        "table_score": round(table_score, 4),
        "native_table_count": native_table_count,
    }


def _decide_mode(policy: str, m: Dict[str, Any], c: Dict[str, Any]) -> Tuple[str, list[str]]:
    if policy == "force_direct":
        return "DIRECT", ["policy_force_direct"]
    if policy == "force_vlm":
        return "FULL_VLM", ["policy_force_vlm"]

    reasons: list[str] = []
    if m["text_chars"] < c["text_chars_min"] and m["image_area_ratio"] > c["image_area_ratio_full_vlm"]:
        reasons.extend(["text_chars_low", "image_ratio_high"])
        return "FULL_VLM", reasons
    if m["noise_ratio"] > c["noise_ratio_full_vlm"]:
        reasons.append("noise_ratio_high")
        return "FULL_VLM", reasons
    if m["formula_score"] >= c["formula_score_region_vlm"]:
        reasons.append("formula_score_high")
        return "REGION_VLM", reasons
    if m["table_score"] >= c["table_score_region_vlm"]:
        reasons.append("table_score_high")
        return "REGION_VLM", reasons

    return "DIRECT", ["text_layer_reliable"]


def _render_page_image(
    doc: fitz.Document,
    page_no: int,
    out_dir: Path,
    dpi: int = 220,
    rotate_deg: int = 0,
) -> Path:
    out = out_dir / f"page_{page_no}.png"
    page = doc[page_no - 1]
    if int(rotate_deg or 0) == 0:
        page.get_pixmap(dpi=dpi).save(str(out))
    else:
        # PyMuPDF positive prerotate rotates counter-clockwise.
        # We keep this explicit knob for deterministic per-document control.
        mat = fitz.Matrix(dpi / 72.0, dpi / 72.0).prerotate(int(rotate_deg))
        page.get_pixmap(matrix=mat).save(str(out))
    return out


def _build_direct_markdown(page: fitz.Page) -> str:
    table_items = _extract_direct_table_items(page)
    table_rects = [item["bbox"] for item in table_items]
    blocks = page.get_text("blocks") or []
    items: list[tuple[float, float, str]] = []

    for block in blocks:
        if len(block) < 5:
            continue
        x0, y0, x1, y1, text = block[:5]
        raw_text = str(text or "").strip()
        if not raw_text:
            continue
        rect = fitz.Rect(x0, y0, x1, y1)
        if _is_noise_block(raw_text, rect, page.rect):
            continue
        if any(_overlap_ratio(rect, table_rect) >= 0.45 for table_rect in table_rects):
            continue
        cleaned = _clean_markdown(_trim_section_tail(raw_text))
        if not cleaned:
            continue
        items.append((float(y0), float(x0), cleaned))

    for item in table_items:
        items.append((float(item["bbox"].y0), float(item["bbox"].x0), item["markdown"]))

    parts: list[str] = []
    for _, _, text in sorted(items, key=lambda x: (x[0], x[1])):
        if not text:
            continue
        if parts and parts[-1] == text:
            continue
        parts.append(text)

    merged = "\n\n".join(parts)
    return _clean_markdown(merged)


def _clean_markdown(text: str) -> str:
    text = text.replace("\r\n", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    text = _unwrap_render_json(text)
    # Strip one outer markdown code fence if model wrapped full answer in ```markdown ... ```
    m = re.match(r"^```[a-zA-Z0-9_-]*\n([\s\S]*?)\n```$", text)
    if m:
        text = m.group(1).strip()
    # Also handle broken/unclosed fences defensively.
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        while lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    text = _strip_layout_noise_lines(text)
    return text


def _extract_direct_table_items(page: fitz.Page) -> list[Dict[str, Any]]:
    try:
        finder = page.find_tables()
        tables = list(finder.tables) if finder else []
    except Exception:
        tables = []

    items: list[Dict[str, Any]] = []
    for table in tables:
        markdown = _table_to_markdown(table)
        if not markdown.strip():
            continue
        items.append({"bbox": fitz.Rect(table.bbox), "markdown": markdown})
    return items


def _table_to_markdown(table: Any) -> str:
    try:
        rows = table.extract() or []
    except Exception:
        rows = []
    if not rows:
        return ""

    normalized: list[list[str]] = []
    width = max((len(row) for row in rows if isinstance(row, list)), default=0)
    if width <= 1:
        return ""

    for row in rows:
        if not isinstance(row, list):
            continue
        cells = [_clean_table_cell_text(cell) for cell in row]
        if len(cells) < width:
            cells.extend([""] * (width - len(cells)))
        normalized.append(cells[:width])

    normalized = [row for row in normalized if any(cell for cell in row)]
    if len(normalized) < 2:
        return ""

    if _looks_like_spurious_table_header(normalized[0]):
        normalized = normalized[1:]
    if len(normalized) < 2:
        return ""

    if len(normalized) >= 3 and _looks_like_header_row(normalized[0]) and _looks_like_header_row(normalized[1]):
        header = _merge_header_rows(normalized[0], normalized[1])
        body = normalized[2:]
    else:
        header = normalized[0]
        body = normalized[1:]

    header = [cell or f"Col{i + 1}" for i, cell in enumerate(header)]
    body = [row[: len(header)] + [""] * max(0, len(header) - len(row)) for row in body if any(cell for cell in row)]
    if not body:
        return ""

    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * len(header)) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(row[: len(header)]) + " |")
    return "\n".join(lines).strip()


def _clean_table_cell_text(value: Any) -> str:
    text = str(value or "").replace("\r", "\n").strip()
    if not text:
        return ""
    parts = [part.strip() for part in text.splitlines() if part.strip()]
    if not parts:
        return ""

    meaningful_exists = any(len(part) >= 3 for part in parts)
    kept: list[str] = []
    for part in parts:
        if re.fullmatch(r"[A-Za-z]{1,3}", part):
            continue
        if re.fullmatch(r"[\W_]{1,3}", part):
            continue
        if meaningful_exists and len(part) == 1 and re.fullmatch(r"[\u4e00-\u9fff]", part):
            continue
        if meaningful_exists and len(re.sub(r"\s+", "", part)) <= 3 and not re.search(r"\d", part):
            if sum(1 for ch in part if "\u4e00" <= ch <= "\u9fff") <= 1:
                continue
        kept.append(part)

    fallback = [
        part
        for part in parts
        if not re.fullmatch(r"[A-Za-z]{1,3}", part)
        and not re.fullmatch(r"[\W_]{1,2}", part)
    ]
    merged = " ".join(kept or fallback or parts)
    merged = re.sub(r"\s+", " ", merged).strip()
    merged = re.sub(r"^[A-Za-z]\s+", "", merged)
    return merged


def _looks_like_spurious_table_header(row: list[str]) -> bool:
    joined = " ".join(row)
    has_placeholder = any(re.fullmatch(r"col\d+", cell.strip(), flags=re.IGNORECASE) for cell in row if cell.strip())
    return has_placeholder or ("表" in joined and any("Col" in cell for cell in row))


def _looks_like_header_row(row: list[str]) -> bool:
    non_empty = [cell for cell in row if cell]
    if not non_empty:
        return False
    digit_cells = sum(1 for cell in non_empty if re.search(r"\d", cell))
    return digit_cells <= max(1, len(non_empty) // 3)


def _merge_header_rows(row1: list[str], row2: list[str]) -> list[str]:
    expanded = list(row1)
    carry = ""
    for idx in range(len(expanded) - 1, -1, -1):
        if expanded[idx]:
            carry = expanded[idx]
        elif carry:
            expanded[idx] = carry
    expanded = _forward_fill(expanded)

    merged: list[str] = []
    for a, b in zip(expanded, row2):
        a = str(a or "").strip()
        b = str(b or "").strip()
        if b and (not a or a.lower().startswith("col") or a in {"安全系数", "安全系数 "}):
            merged.append(b)
            continue
        if a and b and a != b:
            generic_headers = {"安全系数", "材料", "热处理状态", "直径", "厚度"}
            if a in generic_headers and len(b) > len(a):
                merged.append(b)
                continue
        parts = []
        for cell in (a, b):
            if cell and cell not in parts:
                parts.append(cell)
        merged.append(" ".join(parts).strip())
    return merged


def _forward_fill(values: list[str]) -> list[str]:
    out: list[str] = []
    last = ""
    for value in values:
        value = str(value or "").strip()
        if value:
            last = value
            out.append(value)
        else:
            out.append(last)
    return out


def _is_noise_block(text: str, rect: fitz.Rect, page_rect: fitz.Rect) -> bool:
    cleaned = str(text or "").strip()
    if not cleaned:
        return True
    if _contains_header_footer_artifact(cleaned):
        return True
    if _is_header_footer_line(cleaned):
        return True
    if rect.width >= page_rect.width * 0.8 and rect.height >= page_rect.height * 0.35:
        return True
    return False


def _overlap_ratio(a: fitz.Rect, b: fitz.Rect) -> float:
    inter = a & b
    if inter.is_empty:
        return 0.0
    denom = max(a.get_area(), 1.0)
    return float(inter.get_area() / denom)


def _trim_section_tail(text: str) -> str:
    lines = str(text or "").splitlines()
    if not lines:
        return ""
    trimmed: list[str] = []
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if idx > 0 and re.match(r"^\d+(?:\.\d+){1,}\s+", stripped):
            break
        trimmed.append(line)
    return "\n".join(trimmed).strip()


def _unwrap_render_json(text: str) -> str:
    """
    Some models occasionally return JSON {"render":"...","rag":...} even when
    markdown-only is expected. Unwrap render field defensively.
    """
    s = (text or "").strip()
    if not s or not s.startswith("{"):
        return s

    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            render = obj.get("render")
            if isinstance(render, str) and render.strip():
                return render.strip()
    except Exception:
        pass

    m = re.search(r'"render"\s*:\s*"((?:\\.|[^"\\])*)"', s, re.S)
    if m:
        raw = m.group(1)
        try:
            decoded = json.loads(f'"{raw}"')
            if isinstance(decoded, str) and decoded.strip():
                return decoded.strip()
        except Exception:
            pass
    # Truncated JSON fallback: recover prefix payload after {"render":" ...
    prefix = '{"render":"'
    if s.startswith(prefix):
        tail = s[len(prefix):]
        for sep in ('","rag":', '","elements":', '"}'):
            i = tail.find(sep)
            if i >= 0:
                tail = tail[:i]
                break
        tail = tail.strip().rstrip('"')
        if tail:
            try:
                decoded = json.loads(f'"{tail}"')
                if isinstance(decoded, str) and decoded.strip():
                    return decoded.strip()
            except Exception:
                # Best-effort unescape for malformed/truncated json strings.
                decoded = (
                    tail.replace("\\r\\n", "\n")
                    .replace("\\n", "\n")
                    .replace("\\t", "\t")
                    .replace('\\"', '"')
                    .replace("\\\\", "\\")
                ).strip()
                if decoded:
                    return decoded
    return s


def _extract_section(markdown: str) -> Optional[str]:
    for line in markdown.splitlines():
        m = re.match(r"^\s*(\d+(?:\.\d+)*)\s+", line)
        if m:
            return m.group(1)
    return None


def _merge_region_vlm_markdown(markdown: str, structured: Dict[str, Any]) -> str:
    text = markdown or ""
    formulas = _dedupe_formulas_against_markdown(
        [str(x).strip() for x in (structured.get("formulas") or []) if str(x).strip()],
        text,
    )
    if not formulas:
        return markdown
    if not _should_append_formulas_to_region_render(text, structured):
        return markdown
    if re.search(r"\$[^$\n]+\$|\$\$[\s\S]+?\$\$", markdown or ""):
        return markdown

    formula_block = "\n\n".join([f"$${formula}$$" for formula in formulas])
    text = _replace_formula_fragments(text)
    if "式中" in text:
        return text.replace("式中", f"{formula_block}\n\n式中", 1)
    return (text.rstrip() + "\n\n" + formula_block).strip()


def _dedupe_formulas_against_markdown(formulas: list[str], markdown: str) -> list[str]:
    text = str(markdown or "")
    if not formulas or not text:
        return formulas
    compact_text = _latex_compact(text)
    out: list[str] = []
    for formula in formulas:
        compact_formula = _latex_compact(formula)
        if compact_formula and compact_formula in compact_text:
            continue
        out.append(formula)
    return _unique_keep_order(out)


def _latex_compact(text: str) -> str:
    s = str(text or "")
    s = s.replace("\\,", "")
    s = s.replace("\\ ", "")
    s = s.replace("\\mathrm{~h}", "\\mathrm{h}")
    s = re.sub(r"\s+", "", s)
    return s


def _should_append_formulas_to_region_render(markdown: str, structured: Dict[str, Any]) -> bool:
    text = str(markdown or "")
    if not text.strip():
        return False
    if structured.get("tables"):
        return False
    if "式中" in text:
        return True
    if re.search(r"\(\d+-\d+\)", text):
        return True
    if _looks_like_formula_fragment_page(text):
        return True
    return False


def _looks_like_formula_fragment_page(markdown: str) -> bool:
    lines = [ln.strip() for ln in str(markdown or "").splitlines() if ln.strip()]
    if not lines:
        return False
    short_formulaish = 0
    for line in lines:
        if _is_formula_fragment_line(line):
            short_formulaish += 1
    return short_formulaish >= 6


def _replace_formula_fragments(text: str) -> str:
    lines = (text or "").splitlines()
    if not lines:
        return text
    out: list[str] = []
    i = 0
    while i < len(lines):
        if _is_formula_fragment_line(lines[i]):
            j = i
            fragment_count = 0
            while j < len(lines) and _is_formula_fragment_line(lines[j]):
                fragment_count += 1
                j += 1
            label = lines[j].strip() if j < len(lines) and re.search(r"^\(\d+-\d+\)$", lines[j].strip()) else ""
            if fragment_count >= 4 and label:
                out.append(label)
                i = j + 1
                continue
        out.append(lines[i])
        i += 1
    merged = "\n".join(out)
    merged = re.sub(r"\n{3,}", "\n\n", merged)
    return merged.strip()


def _is_formula_fragment_line(line: str) -> bool:
    t = (line or "").strip()
    if not t:
        return False
    if re.search(r"[\u4e00-\u9fff]", t):
        return False
    if len(t) > 20:
        return False
    return bool(re.fullmatch(r"[\[\]A-Za-z0-9σηΣΠΤτσpPtT=／/\.\-\s]+", t))


def _build_rag_content(markdown: str, structured: Dict[str, Any], rag_page_text: str = "") -> str:
    base = _strip_layout_noise_lines(rag_page_text.strip() or markdown.strip())
    parts = [base] if base else []

    formulas = structured.get("formulas") or []
    if formulas:
        parts.append("[FORMULAS]\n" + "\n".join([str(x).strip() for x in formulas if str(x).strip()]))

    tables = structured.get("tables") or []
    if tables:
        parts.append("[TABLES]\n" + "\n\n".join([str(x).strip() for x in tables if str(x).strip()]))

    figures = structured.get("figures") or []
    if figures:
        parts.append("[FIGURES]\n" + "\n".join([str(x).strip() for x in figures if str(x).strip()]))

    return "\n\n".join([p for p in parts if p])


def _strip_layout_noise_lines(text: str) -> str:
    if not text:
        return text
    lines = [_clean_inline_artifacts(ln.rstrip()) for ln in text.splitlines()]
    cleaned = [
        ln
        for ln in lines
        if not _is_header_footer_line(ln)
        and not _is_noise_figure_line(ln)
        and not _is_noise_text_line(ln)
        and not _is_formula_noise_line(ln)
    ]
    out = "\n".join(cleaned).strip()
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out


def _is_header_footer_line(line: str) -> bool:
    t = (line or "").strip()
    if not t:
        return False
    # Typical standards header: GB/T 150.1—2024
    if re.match(r"^[A-Z]{1,6}\s*/?\s*[A-Z]?\s*\d+(?:\.\d+)?\s*[—-]\s*\d{4}$", t):
        return True
    if re.match(r"^(?:[A-Z]{1,6}\s*/?\s*[A-Z]?\s*\d+(?:\.\d+)?|TSG\s*\d+)\s*[—-]\s*\d{4}\b", t):
        return True
    # Standalone page number.
    if re.match(r"^\d{1,4}$", t):
        return True
    if re.match(r"^[—-]\s*\d{1,4}\s*[—-]$", t):
        return True
    return False


def _is_noise_figure_line(line: str) -> bool:
    t = (line or "").strip()
    if not t:
        return False
    low = t.lower()
    if "[figure:" not in low:
        return False
    noise_terms = (
        "watermark",
        "overlay",
        "logo",
        "seal",
        "stamp",
        "背景水印",
        "水印",
        "table with",
        "table of",
        "tabular data",
    )
    return any(k in low for k in noise_terms)


def _is_noise_text_line(line: str) -> bool:
    t = (line or "").strip()
    if not t:
        return False
    if _contains_header_footer_artifact(t):
        return True
    low = t.lower()
    if "http://" in low or "https://" in low or "www." in low:
        return True
    if "aqsiq.gov.cn" in low:
        return True
    if "国家质监监督检验检疫总局" in t:
        return True
    return False


def _contains_header_footer_artifact(text: str) -> bool:
    t = str(text or "").strip()
    if not t:
        return False
    low = t.lower()
    if "aqsiq.gov.cn" in low:
        return True
    if "国家质监监督检验检疫总局" in t:
        return True
    if "特种设备安全技术规范" in t and re.search(r"\bTSG\s*\d+\s*[—-]\s*\d{4}\b", t):
        return True
    if re.search(r"[—-]\s*\d{1,4}\s*[—-]", t):
        compact = re.sub(r"\s+", "", t)
        if re.fullmatch(r"[—-]\d{1,4}[—-]", compact):
            return True
    return False


def _clean_inline_artifacts(line: str) -> str:
    text = str(line or "")
    if not text:
        return ""
    text = re.sub(r"\[\s*\]", "", text)
    text = re.sub(r"\bTSG\s*\d+\s*[—-]\s*\d{4}\b", "", text, flags=re.IGNORECASE)
    text = text.replace("特种设备安全技术规范", "")
    text = text.replace("国家质监监督检验检疫总局", "")
    text = re.sub(r"https?://\S+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bwww\.\S+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[—-]\s*\d{1,4}\s*[—-]", "", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def _is_formula_noise_line(line: str) -> bool:
    t = (line or "").strip()
    if not t:
        return False
    if re.search(r"[\u4e00-\u9fff]", t):
        return False
    compact = re.sub(r"\s+", "", t)
    if len(compact) > 8:
        return False
    return compact in {
        "T",
        "t",
        "p",
        "σ",
        "η",
        "=",
        "Tσ",
        "tσ",
        "pσ",
        "σ／σ",
    }


def _normalize_structured(value: Any) -> Dict[str, Any]:
    raw = value if isinstance(value, dict) else {}

    def _as_list(name: str) -> list[str]:
        v = raw.get(name)
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return []

    figures = _as_list("figures")
    figures = [f for f in figures if not _is_noise_figure_line(f"[FIGURE: {f}]")]
    tables = _normalize_table_candidates(_as_list("tables"))
    formulas = _filter_formula_candidates(_as_list("formulas"), tables)

    return {
        "formulas": formulas,
        "tables": tables,
        "figures": figures,
    }


def _filter_formula_candidates(formulas: list[str], tables: list[str]) -> list[str]:
    if not formulas:
        return []
    table_text = "\n".join([str(t or "") for t in tables]).replace(" ", "")
    out: list[str] = []
    for formula in formulas:
        f = str(formula or "").strip()
        if not f:
            continue
        compact = re.sub(r"\s+", "", f)
        if not compact:
            continue
        if table_text and compact in table_text and _looks_like_table_formula_field(compact):
            continue
        if compact in {"R_m", "R_D", "R_n", "R_eL", "R_p1.0", "R_p0.2"}:
            continue
        out.append(f)
    return _unique_keep_order(out)


def _looks_like_table_formula_field(compact: str) -> bool:
    if len(compact) <= 24:
        return True
    if re.fullmatch(r"R_[A-Za-z0-9\.\{\}\\]+", compact):
        return True
    if re.fullmatch(r"n_[A-Za-z0-9\{\}\\]+.?[≥≤=].+", compact):
        return True
    if "1000h" in compact or "0.01%" in compact:
        return True
    return False


def _normalize_table_candidates(vlm_tables: list[str]) -> list[str]:
    out: list[str] = []
    for t in vlm_tables:
        s = str(t or "").strip()
        if not s:
            continue
        if s.startswith("{") and s.endswith("}"):
            try:
                import ast

                obj = ast.literal_eval(s)
                if isinstance(obj, dict):
                    header = obj.get("header") or obj.get("columns") or []
                    rows = obj.get("rows") or obj.get("raw_array") or []
                    if isinstance(header, list) and header:
                        lines = ["| " + " | ".join([str(x).strip() for x in header]) + " |"]
                        lines.append("| " + " | ".join(["---"] * len(header)) + " |")
                        if isinstance(rows, list):
                            for row in rows:
                                if isinstance(row, list):
                                    cells = [str(x).strip() for x in row]
                                    if len(cells) < len(header):
                                        cells = cells + [""] * (len(header) - len(cells))
                                    lines.append("| " + " | ".join(cells[: len(header)]) + " |")
                        s = "\n".join(lines).strip()
            except Exception:
                pass
        s = _normalize_markdown_table_text(s)
        if s:
            out.append(s)
    return out


def _detect_table_source(markdown: str, structured: Dict[str, Any]) -> str:
    if _extract_table_placeholders(markdown):
        return "placeholder"
    parsed = _extract_markdown_tables(markdown)
    if parsed:
        return "render_markdown"
    if structured.get("tables"):
        first = str((structured.get("tables") or [""])[0])
        if first.startswith("[TABLE_PLACEHOLDER]"):
            return "placeholder"
        return "vlm"
    return "none"


def _select_rag_tables(markdown: str, vlm_tables: list[str]) -> list[str]:
    placeholders = _extract_table_placeholders(markdown)
    if placeholders:
        return placeholders
    parsed = _extract_markdown_tables(markdown)
    if parsed:
        return parsed
    if vlm_tables:
        return [str(x).strip() for x in vlm_tables if str(x).strip()]
    anchors = _extract_table_anchors(markdown)
    return [f"[TABLE_PLACEHOLDER] {a}: table structure unavailable; see original page." for a in anchors]


def _rebuild_render_tables_from_structured(markdown: str, structured: Dict[str, Any]) -> str:
    text = (markdown or "").strip()
    if not text:
        return text
    if _extract_markdown_tables(text):
        return text

    tables = _usable_structured_tables(structured.get("tables") or [])
    if not tables:
        return text

    lines = text.splitlines()
    anchors = _extract_table_anchors(text)
    inserted = 0

    for idx, table_md in enumerate(tables):
        anchor = anchors[idx] if idx < len(anchors) else ""
        if anchor:
            pos = _find_anchor_insert_pos(lines, anchor)
            if pos >= 0:
                prune_end = _find_fragment_block_end(lines, pos, table_md)
                if prune_end > pos:
                    lines[pos:prune_end] = []
                    pos = _find_anchor_insert_pos(lines, anchor)
                block = ["", table_md, ""]
                lines[pos:pos] = block
                inserted += 1
                continue
        lines.extend(["", table_md, ""])
        inserted += 1

    if inserted <= 0:
        return text
    merged = "\n".join(lines)
    merged = re.sub(r"\n{3,}", "\n\n", merged).strip()
    merged = _cleanup_fragments_before_tables(merged)
    return merged


def _usable_structured_tables(vlm_tables: list[str]) -> list[str]:
    out: list[str] = []
    for item in vlm_tables:
        s = _normalize_markdown_table_text(str(item or "").strip())
        if not s:
            continue
        if s.startswith("[TABLE_PLACEHOLDER]"):
            continue
        if not _table_looks_like_markdown(s):
            continue
        out.append(s)
    return out


def _table_looks_like_markdown(text: str) -> bool:
    rows = _extract_markdown_tables(text)
    if rows:
        return True
    lines = [ln.strip() for ln in str(text or "").splitlines() if ln.strip()]
    if len(lines) < 2:
        return False
    if "|" not in lines[0] or "|" not in lines[1]:
        return False
    return bool(re.match(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$", lines[1]))


def _normalize_markdown_table_text(table_text: str) -> str:
    text = str(table_text or "").strip()
    if not text or "|" not in text:
        return text

    rows: list[list[str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or "|" not in line:
            continue
        if re.match(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$", line):
            continue
        rows.append(_split_markdown_row(line))

    if len(rows) < 2:
        return text

    width = max((len(r) for r in rows), default=0)
    if width <= 1:
        return text

    normalized: list[list[str]] = []
    for row in rows:
        cells = [str(c or "").strip() for c in row]
        if len(cells) < width:
            cells.extend([""] * (width - len(cells)))
        normalized.append(cells[:width])

    normalized = [row for row in normalized if any(cell for cell in row)]
    if len(normalized) < 2:
        return text

    if _looks_like_spurious_table_header(normalized[0]):
        normalized = normalized[1:]
    if len(normalized) < 2:
        return text

    if len(normalized) >= 3 and _looks_like_header_row(normalized[0]) and _looks_like_header_row(normalized[1]):
        header = _merge_header_rows(normalized[0], normalized[1])
        body = normalized[2:]
    else:
        header = normalized[0]
        body = normalized[1:]

    header = [cell or f"Col{i + 1}" for i, cell in enumerate(header)]
    body = [row[: len(header)] + [""] * max(0, len(header) - len(row)) for row in body if any(cell for cell in row)]
    if not body:
        return text

    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * len(header)) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(row[: len(header)]) + " |")
    return "\n".join(lines).strip()


def _find_anchor_insert_pos(lines: list[str], anchor: str) -> int:
    needle = (anchor or "").strip()
    if not needle:
        return -1
    needle_norm = re.sub(r"\s+", "", needle)
    for idx, line in enumerate(lines):
        line_stripped = line.strip()
        if line_stripped == needle:
            return idx + 1
        if re.sub(r"\s+", "", line_stripped) == needle_norm:
            return idx + 1
    return -1


def _find_fragment_block_end(lines: list[str], start: int, table_md: str) -> int:
    table_tokens = _table_fragment_tokens(table_md)
    idx = start
    while idx < len(lines):
        line = lines[idx]
        stripped = line.strip()
        if not stripped:
            idx += 1
            continue
        if _is_stop_line_for_fragment_cleanup(stripped):
            break
        if _looks_like_table_fragment_line(stripped, table_tokens):
            idx += 1
            continue
        break
    return idx


def _table_fragment_tokens(table_md: str) -> set[str]:
    tokens: set[str] = set()
    for line in str(table_md or "").splitlines():
        if "|" not in line:
            continue
        for cell in _split_markdown_row(line):
            text = re.sub(r"<br>", " ", str(cell or ""), flags=re.IGNORECASE)
            parts = [p for p in re.split(r"[\s\(\)（）,，;；:/]+", text) if p]
            for part in parts:
                clean = part.strip().lower()
                if len(clean) >= 2:
                    tokens.add(clean)
    return tokens


def _is_stop_line_for_fragment_cleanup(line: str) -> bool:
    if re.match(r"^(表|Table)\s*", line, flags=re.IGNORECASE):
        return True
    if re.match(r"^\d+(?:\.\d+){1,}\s*", line):
        return True
    if re.match(r"^注\s*\d*", line):
        return True
    if "|" in line:
        return True
    return False


def _looks_like_table_fragment_line(line: str, table_tokens: set[str]) -> bool:
    compact = re.sub(r"\s+", "", line)
    if not compact:
        return False
    if re.fullmatch(r"(?:[\u4e00-\u9fff]\s*){2,12}", line):
        return True
    if len(compact) <= 12:
        return True
    if re.fullmatch(r"[\[\]\(\)A-Za-z0-9_\.\-≥≤=×%/\\]+", compact):
        return True
    lowered = line.lower()
    overlap = sum(1 for tok in table_tokens if tok and tok in lowered)
    if overlap >= 2:
        return True
    if len(compact) <= 24 and overlap >= 1:
        return True
    return False


def _cleanup_fragments_before_tables(markdown: str) -> str:
    lines = (markdown or "").splitlines()
    if not lines:
        return markdown

    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        out.append(lines[i])
        if not re.match(r"^(表|Table)\s*", lines[i].strip(), flags=re.IGNORECASE):
            i += 1
            continue

        j = i + 1
        fragment_start = j
        while j < n and not (lines[j].strip().startswith("|") and j + 1 < n and lines[j + 1].strip().startswith("|")):
            if _is_stop_line_for_fragment_cleanup(lines[j].strip()):
                break
            j += 1

        if j < n and lines[j].strip().startswith("|") and fragment_start < j:
            sample_end = j
            while sample_end < n and lines[sample_end].strip().startswith("|"):
                sample_end += 1
            table_tokens = _table_fragment_tokens("\n".join(lines[j:sample_end]))
            if any(_looks_like_table_fragment_line(lines[k].strip(), table_tokens) for k in range(fragment_start, j) if lines[k].strip()):
                while out and not out[-1].strip():
                    out.pop()
                i = j
                continue

        i += 1

    merged = "\n".join(out)
    merged = re.sub(r"\n{3,}", "\n\n", merged).strip()
    return merged


def _has_table_residual_noise(markdown: str) -> bool:
    lines = (markdown or "").splitlines()
    if not lines or not _extract_markdown_tables(markdown):
        return False

    noisy_hits = 0
    seen_table = False
    current_table_tokens: set[str] = set()
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if line.startswith("|") and i + 1 < n and lines[i + 1].strip().startswith("|"):
            seen_table = True
            j = i
            while j < n and lines[j].strip().startswith("|"):
                j += 1
            current_table_tokens = _table_fragment_tokens("\n".join(lines[i:j]))
            i = j
            continue
        if seen_table and not _is_stop_line_for_fragment_cleanup(line) and _looks_like_table_fragment_line(line, current_table_tokens):
            noisy_hits += 1
            if noisy_hits >= 4:
                return True
        i += 1
    return False


def _extract_markdown_tables(markdown: str) -> list[str]:
    lines = (markdown or "").splitlines()
    out: list[str] = []
    i = 0
    n = len(lines)
    sep_re = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
    while i < n - 1:
        if "|" in lines[i] and sep_re.match(lines[i + 1] or ""):
            start = i
            j = i + 2
            while j < n and "|" in (lines[j] or ""):
                j += 1
            block = "\n".join([ln.rstrip() for ln in lines[start:j] if ln.strip()]).strip()
            if block:
                out.append(block)
            i = j
            continue
        i += 1
    return out


def _extract_markdown_tables_with_spans(markdown: str) -> list[tuple[int, int, str]]:
    lines = (markdown or "").splitlines()
    out: list[tuple[int, int, str]] = []
    i = 0
    n = len(lines)
    sep_re = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
    while i < n - 1:
        if "|" in lines[i] and sep_re.match(lines[i + 1] or ""):
            start = i
            j = i + 2
            while j < n and "|" in (lines[j] or ""):
                j += 1
            block = "\n".join([ln.rstrip() for ln in lines[start:j] if ln.strip()]).strip()
            if block:
                out.append((start, j, block))
            i = j
            continue
        i += 1
    return out


def _replace_large_tables_with_placeholders(markdown: str, page_no: int, rc: Dict[str, Any]) -> tuple[str, list[str]]:
    if not markdown or not rc.get("large_table_placeholder_enabled", True):
        return markdown, []

    markdown, latex_placeholders = _replace_latex_tabular_with_placeholders(markdown, page_no)
    lines = (markdown or "").splitlines()
    blocks = _extract_markdown_tables_with_spans(markdown)
    if not blocks:
        return markdown, latex_placeholders

    replacements: list[tuple[int, int, str]] = []
    placeholders: list[str] = list(latex_placeholders)
    unnamed_idx = 0

    for start, end, block in blocks:
        col_count, row_count = _table_shape(block)
        cell_count = col_count * row_count
        compacted_numeric = _is_compacted_numeric_table(block)
        is_large = (
            col_count >= int(rc.get("large_table_min_cols", 12))
            or row_count >= int(rc.get("large_table_min_rows", 16))
            or cell_count >= int(rc.get("large_table_min_cells", 180))
            or compacted_numeric
        )
        if not is_large:
            continue

        anchor = _find_table_anchor(lines, start)
        if not anchor:
            unnamed_idx += 1
            anchor = f"未命名表{unnamed_idx}"
        semantic_desc = _build_table_semantic_desc(anchor, block, lines, start)
        placeholder = (
            f"[TABLE_PLACEHOLDER] {anchor}（页号: {page_no}）："
            f"{semantic_desc}（约{row_count}行×{col_count}列）；关键数值请回看原PDF本页。"
        )
        block_md = (
            f"### {anchor}（页号: {page_no}）\n"
            f"该表为大表/横向表，已省略表体，仅保留语义占位。\n"
            f"语义说明：{semantic_desc}\n"
            f"字段维度约为 {row_count} 行 × {col_count} 列，关键数值请回看原PDF本页。\n"
            f"{placeholder}"
        )
        replacements.append((start, end, block_md))
        placeholders.append(placeholder)

    if not replacements:
        return markdown, []

    for start, end, repl in sorted(replacements, key=lambda x: x[0], reverse=True):
        lines[start:end] = [repl]

    merged = "\n".join(lines)
    merged = re.sub(r"\n{3,}", "\n\n", merged).strip()
    return merged, placeholders


def _table_shape(table_markdown: str) -> tuple[int, int]:
    rows = []
    for ln in (table_markdown or "").splitlines():
        t = (ln or "").strip()
        if not t or "|" not in t:
            continue
        rows.append(_split_markdown_row(t))
    if not rows:
        return 0, 0
    col_count = max((len(r) for r in rows), default=0)
    row_count = len(rows)
    return col_count, row_count


def _is_compacted_numeric_table(table_markdown: str) -> bool:
    """
    Detect markdown tables where many temperature/data columns collapse into a
    single cell (common OCR/VLM artifact), e.g. "≤20 100 150 200 ...".
    """
    for ln in (table_markdown or "").splitlines():
        t = (ln or "").strip()
        if not t or "|" not in t:
            continue
        if re.search(r"(?:\d+\s+){7,}\d+", t):
            return True
    return False


def _replace_latex_tabular_with_placeholders(markdown: str, page_no: int) -> tuple[str, list[str]]:
    lines = (markdown or "").splitlines()
    if not lines:
        return markdown, []
    replacements: list[tuple[int, int, str]] = []
    placeholders: list[str] = []
    i = 0
    unnamed = 0
    n = len(lines)
    while i < n:
        t = (lines[i] or "").strip()
        if "\\begin{tabular}" not in t:
            i += 1
            continue
        start = i
        j = i + 1
        while j < n and "\\end{tabular}" not in (lines[j] or ""):
            j += 1
        end = min(n, j + 1) if j < n else n
        block = "\n".join(lines[start:end])
        col_count = t.count("|c")
        row_count = len(re.findall(r"\\\\", block))
        anchor = _find_table_anchor(lines, start)
        if not anchor:
            unnamed += 1
            anchor = f"未命名表{unnamed}"
        semantic_desc = _build_table_semantic_desc(anchor, block, lines, start)
        placeholder = (
            f"[TABLE_PLACEHOLDER] {anchor}（页号: {page_no}）："
            f"{semantic_desc}（检测到LaTeX表格块，约{max(1, row_count)}行×{max(1, col_count)}列）；关键数值请回看原PDF本页。"
        )
        repl = (
            f"### {anchor}（页号: {page_no}）\n"
            "该表为大表/横向表（LaTeX表格块），已省略表体，仅保留语义占位。\n"
            f"语义说明：{semantic_desc}\n"
            f"字段维度约为 {max(1, row_count)} 行 × {max(1, col_count)} 列，关键数值请回看原PDF本页。\n"
            f"{placeholder}"
        )
        replacements.append((start, end, repl))
        placeholders.append(placeholder)
        i = end

    if not replacements:
        return markdown, []

    for start, end, repl in sorted(replacements, key=lambda x: x[0], reverse=True):
        lines[start:end] = [repl]
    merged = "\n".join(lines)
    merged = re.sub(r"\n{3,}", "\n\n", merged).strip()
    return merged, placeholders


def _split_markdown_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _build_table_semantic_desc(anchor: str, table_block: str, lines: list[str], table_start: int) -> str:
    a = (anchor or "").strip()
    ctx = _nearby_context(lines, table_start)
    sig = f"{a}\n{ctx}\n{table_block[:800]}"
    if re.search(r"许用应力|allowable stress|应力", sig, flags=re.IGNORECASE):
        base = "该表用于给出材料在不同工况下的许用应力对照"
    elif re.search(r"成分|化学|composition", sig, flags=re.IGNORECASE):
        base = "该表用于给出材料化学成分及限值对照"
    elif re.search(r"尺寸|公差|厚度|直径", sig, flags=re.IGNORECASE):
        base = "该表用于给出尺寸范围与对应参数对照"
    else:
        base = "该表用于给出多维条件下的参数对照"

    dims = []
    if re.search(r"温度|℃", sig):
        dims.append("温度")
    if re.search(r"厚度|mm", sig, flags=re.IGNORECASE):
        dims.append("厚度")
    if re.search(r"牌号|数字代号|material|grade", sig, flags=re.IGNORECASE):
        dims.append("材料牌号")
    if re.search(r"标准|GB/?T|ASME|ASTM", sig, flags=re.IGNORECASE):
        dims.append("材料标准")
    if re.search(r"Rm|ReL|Rp0\\.2|强度", sig, flags=re.IGNORECASE):
        dims.append("强度指标")

    head_tokens = _header_tokens(table_block)
    if head_tokens:
        dims.extend([t for t in head_tokens if t not in dims])
    dims = [_normalize_dim_token(x) for x in dims]
    dims = _unique_keep_order([x for x in dims if x])[:6]
    if dims:
        usage = _build_table_usage_hint(dims)
        return f"{base}，主要维度包括：{'、'.join(dims)}。{usage}"
    return f"{base}。可结合表题与页号回查原文获取完整数值。"


def _nearby_context(lines: list[str], table_start: int) -> str:
    picked = []
    for i in range(max(0, table_start - 6), table_start):
        t = (lines[i] or "").strip()
        if not t or "|" in t or t.startswith("#") or t.startswith("[TABLE_PLACEHOLDER]"):
            continue
        picked.append(t)
    return " ".join(picked[:3])


def _header_tokens(table_block: str) -> list[str]:
    rows = []
    for ln in (table_block or "").splitlines():
        t = (ln or "").strip()
        if not t or "|" not in t:
            continue
        if re.match(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$", t):
            continue
        rows.append(_split_markdown_row(t))
    if not rows:
        return []
    cand = rows[0]
    out = []
    for c in cand:
        x = (c or "").strip()
        if not x:
            continue
        # Drop latex/control artifacts.
        if "\\" in x or "{" in x or "}" in x:
            continue
        if x.lower() in {"c", "l", "r"}:
            continue
        if len(x) <= 1:
            continue
        if re.fullmatch(r"[\d\s\.\-~≤≥%/]+", x):
            continue
        if len(x) > 24:
            continue
        out.append(x)
    return _unique_keep_order(out)


def _unique_keep_order(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for x in items:
        k = (x or "").strip()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(k)
    return out


def _normalize_dim_token(token: str) -> str:
    t = (token or "").strip()
    if not t:
        return ""
    # Remove residual latex fragments.
    t = re.sub(r"\\[A-Za-z]+\{?.*", "", t).strip()
    if not t:
        return ""
    t = t.replace("统一数", "统一数字代号").replace("字代号", "统一数字代号")
    t = t.replace("钢板", "材料标准") if t == "钢板" else t
    # Keep only meaningful Chinese/english terms.
    if len(t) <= 1:
        return ""
    if re.fullmatch(r"[\W_]+", t):
        return ""
    return t


def _build_table_usage_hint(dims: list[str]) -> str:
    d = [x for x in (dims or []) if x]
    if not d:
        return "可结合表题与页号回查原文获取完整数值。"
    if "温度" in d and "厚度" in d:
        return "可按温度与厚度定位目标单元，再结合材料牌号或标准读取对应参数。"
    if "材料牌号" in d and "材料标准" in d:
        return "可先按材料牌号与材料标准筛选，再按其余维度查取目标参数。"
    return f"可按{'、'.join(d[:3])}逐步定位目标参数，并回看原PDF核对细节。"


def _find_table_anchor(lines: list[str], table_start: int) -> str:
    for i in range(table_start - 1, max(-1, table_start - 13), -1):
        if i < 0:
            break
        t = (lines[i] or "").strip()
        if not t:
            continue
        if "|" in t or t.startswith("[TABLE_PLACEHOLDER]"):
            continue
        if re.match(r"^(表|Table)\s*", t, flags=re.IGNORECASE):
            return t[:120]
        if t.startswith("#"):
            return t.lstrip("#").strip()[:120]
    return ""


def _extract_table_placeholders(markdown: str) -> list[str]:
    out: list[str] = []
    for ln in (markdown or "").splitlines():
        t = (ln or "").strip()
        if t.startswith("[TABLE_PLACEHOLDER]"):
            out.append(t)
    return out


def _extract_table_anchors(markdown: str) -> list[str]:
    anchors: list[str] = []
    for ln in (markdown or "").splitlines():
        t = ln.strip()
        if not t:
            continue
        if re.match(r"^(表|Table)\s*[A-Za-z]?(?:(?:[.\-]\d+)+|\d+(?:[.\-]\d+)*)", t, flags=re.IGNORECASE):
            anchors.append(t[:120])
    seen = set()
    uniq = []
    for a in anchors:
        if a not in seen:
            seen.add(a)
            uniq.append(a)
    return uniq


def _should_emit_chunks(rc: Dict[str, Any]) -> bool:
    if not rc.get("enable_chunks", False):
        return False
    policy = str(rc.get("chunk_policy", "disabled")).strip().lower()
    total_pages = int(rc.get("task_total_pages", 1))
    if policy == "single_page_dev":
        return total_pages == 1
    if policy == "multi_page_batch":
        return total_pages > 1
    return False


def _build_chunks(text: str, chunk_size: int = 700) -> list[dict[str, Any]]:
    if not text:
        return []

    chunks: list[dict[str, Any]] = []
    i = 0
    while i < len(text):
        j = min(len(text), i + chunk_size)
        part = text[i:j].strip()
        if part:
            chunks.append({"chunk_id": f"c{len(chunks)}", "content": part, "token_estimate": max(1, len(part) // 4)})
        i = j
    return chunks
