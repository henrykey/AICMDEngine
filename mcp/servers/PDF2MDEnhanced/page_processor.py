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
            markdown = _clean_markdown(page.get_text("text") or "")
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
            structured = vlm.extract_region_structured(str(image_path))
            vlm_calls += 1
            rag_page_text = ""

    doc.close()

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
    formula_score = min(1.0, formula_hits / 40.0)

    table_line_hits = 0
    for line in text.splitlines():
        if re.search(r"\S+\s{2,}\S+\s{2,}\S+", line):
            table_line_hits += 1
        if "|" in line:
            table_line_hits += 1
    table_score = min(1.0, table_line_hits / 20.0)

    return {
        "text_chars": text_chars,
        "text_blocks": text_blocks,
        "image_area_ratio": round(image_area_ratio, 4),
        "drawing_density": round(drawing_density, 4),
        "noise_ratio": round(noise_ratio, 4),
        "formula_score": round(formula_score, 4),
        "table_score": round(table_score, 4),
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
    lines = [ln.rstrip() for ln in text.splitlines()]
    cleaned = [ln for ln in lines if not _is_header_footer_line(ln) and not _is_noise_figure_line(ln)]
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
    # Standalone page number.
    if re.match(r"^\d{1,4}$", t):
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


def _normalize_structured(value: Any) -> Dict[str, Any]:
    raw = value if isinstance(value, dict) else {}

    def _as_list(name: str) -> list[str]:
        v = raw.get(name)
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return []

    figures = _as_list("figures")
    figures = [f for f in figures if not _is_noise_figure_line(f"[FIGURE: {f}]")]

    return {
        "formulas": _as_list("formulas"),
        "tables": _normalize_table_candidates(_as_list("tables")),
        "figures": figures,
    }


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
        return f"{base}，主要维度包括：{'、'.join(dims)}"
    return base


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
        if re.match(r"^(表|Table)\s*[A-Za-z]?(?:\.\d+)+", t, flags=re.IGNORECASE):
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
