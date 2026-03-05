from __future__ import annotations

import hashlib
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
        image_path = _render_page_image(doc, page_no, Path(work_dir), dpi=rc["render_dpi"])

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
        else:  # REGION_VLM
            markdown = _clean_markdown(page.get_text("text") or "")
            structured = vlm.extract_region_structured(str(image_path))
            vlm_calls += 1
            rag_page_text = ""

    doc.close()

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
            "table_source": table_source,
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
        "chunk_size": int(c.get("chunk_size", 700)),
        "enable_chunks": bool(c.get("enable_chunks", False)),
        "chunk_policy": str(c.get("chunk_policy", "disabled")),
        "task_total_pages": int(c.get("__task_total_pages", 1)),
        "debug_layout_probe": bool(c.get("debug_layout_probe", False)),
        "full_vlm_split_extract": bool(c.get("full_vlm_split_extract", False)),
        "full_vlm_retry_markdown": bool(c.get("full_vlm_retry_markdown", False)),
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


def _render_page_image(doc: fitz.Document, page_no: int, out_dir: Path, dpi: int = 220) -> Path:
    out = out_dir / f"page_{page_no}.png"
    page = doc[page_no - 1]
    page.get_pixmap(dpi=dpi).save(str(out))
    return out


def _clean_markdown(text: str) -> str:
    text = text.replace("\r\n", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    # Strip one outer markdown code fence if model wrapped full answer in ```markdown ... ```
    m = re.match(r"^```[a-zA-Z0-9_-]*\n([\s\S]*?)\n```$", text)
    if m:
        text = m.group(1).strip()
    text = _strip_layout_noise_lines(text)
    return text


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
    cleaned = [ln for ln in lines if not _is_header_footer_line(ln)]
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


def _normalize_structured(value: Any) -> Dict[str, Any]:
    raw = value if isinstance(value, dict) else {}

    def _as_list(name: str) -> list[str]:
        v = raw.get(name)
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return []

    return {
        "formulas": _as_list("formulas"),
        "tables": _normalize_table_candidates(_as_list("tables")),
        "figures": _as_list("figures"),
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
