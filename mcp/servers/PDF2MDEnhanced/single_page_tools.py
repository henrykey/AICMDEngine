from __future__ import annotations

import base64
import hashlib
import json
import re
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import fitz

from .ocr_clients import OpenAICompatibleOcrClient
from .ocr_clients.ocr_models import OcrElement, OcrResult
from .ocr_clients.ocr_normalizers import normalize_text_response
from .page_processor import _render_page_image, _routing_defaults, _table_to_markdown
from .vlm_client import DynamicVLMClient


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
PDF_EXTENSIONS = {".pdf"}


@dataclass
class SinglePageContext:
    input_type: str
    source_path: str
    image_path: str
    page_no: int
    page_text: str = ""
    native_tables: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.native_tables is None:
            self.native_tables = []


def extract_page_tables_direct(
    file_path: Optional[str] = None,
    file_data: Optional[str] = None,
    file_url: Optional[str] = None,
    page_no: int = 1,
    input_type: str = "auto",
    output_format: str = "json",
    describe: bool = True,
    ocr_config: Optional[Dict[str, Any]] = None,
    vlm_config: Optional[Dict[str, Any]] = None,
    routing_config: Optional[Dict[str, Any]] = None,
) -> str:
    result = _extract_single_page(
        tool="extract_page_tables",
        target="tables",
        file_path=file_path,
        file_data=file_data,
        file_url=file_url,
        page_no=page_no,
        input_type=input_type,
        describe=describe,
        ocr_config=ocr_config,
        vlm_config=vlm_config,
        routing_config=routing_config,
    )
    return _serialize_result(result, output_format)


def extract_page_formulas_direct(
    file_path: Optional[str] = None,
    file_data: Optional[str] = None,
    file_url: Optional[str] = None,
    page_no: int = 1,
    input_type: str = "auto",
    output_format: str = "json",
    describe: bool = True,
    ocr_config: Optional[Dict[str, Any]] = None,
    vlm_config: Optional[Dict[str, Any]] = None,
    routing_config: Optional[Dict[str, Any]] = None,
) -> str:
    result = _extract_single_page(
        tool="extract_page_formulas",
        target="formulas",
        file_path=file_path,
        file_data=file_data,
        file_url=file_url,
        page_no=page_no,
        input_type=input_type,
        describe=describe,
        ocr_config=ocr_config,
        vlm_config=vlm_config,
        routing_config=routing_config,
    )
    return _serialize_result(result, output_format)


def extract_page_figures_direct(
    file_path: Optional[str] = None,
    file_data: Optional[str] = None,
    file_url: Optional[str] = None,
    page_no: int = 1,
    input_type: str = "auto",
    output_format: str = "json",
    describe: bool = True,
    ocr_config: Optional[Dict[str, Any]] = None,
    vlm_config: Optional[Dict[str, Any]] = None,
    routing_config: Optional[Dict[str, Any]] = None,
) -> str:
    _ = describe
    result = _extract_single_page(
        tool="extract_page_figures",
        target="figures",
        file_path=file_path,
        file_data=file_data,
        file_url=file_url,
        page_no=page_no,
        input_type=input_type,
        describe=True,
        ocr_config=ocr_config,
        vlm_config=vlm_config,
        routing_config=routing_config,
    )
    return _serialize_result(result, output_format)


def extract_page_structured_direct(
    file_path: Optional[str] = None,
    file_data: Optional[str] = None,
    file_url: Optional[str] = None,
    page_no: int = 1,
    input_type: str = "auto",
    output_format: str = "json",
    describe: bool = True,
    ocr_config: Optional[Dict[str, Any]] = None,
    vlm_config: Optional[Dict[str, Any]] = None,
    routing_config: Optional[Dict[str, Any]] = None,
) -> str:
    result = _extract_single_page(
        tool="extract_page_structured",
        target="structured",
        file_path=file_path,
        file_data=file_data,
        file_url=file_url,
        page_no=page_no,
        input_type=input_type,
        describe=describe,
        ocr_config=ocr_config,
        vlm_config=vlm_config,
        routing_config=routing_config,
    )
    return _serialize_result(result, output_format)


def _extract_single_page(
    tool: str,
    target: str,
    file_path: Optional[str],
    file_data: Optional[str],
    file_url: Optional[str],
    page_no: int,
    input_type: str,
    describe: bool,
    ocr_config: Optional[Dict[str, Any]],
    vlm_config: Optional[Dict[str, Any]],
    routing_config: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    _validate_output_target(target)
    with tempfile.TemporaryDirectory(prefix="pdf2md_enh_single_page_") as work_dir:
        ctx = _prepare_context(
            Path(work_dir),
            file_path=file_path,
            file_data=file_data,
            file_url=file_url,
            page_no=page_no,
            input_type=input_type,
            routing_config=routing_config,
        )
        rc = _routing_defaults(_merge_routing_ocr_config(routing_config, ocr_config))
        glm = OpenAICompatibleOcrClient(rc.get("glm_ocr") or {}, source="glm_ocr")
        vlm = DynamicVLMClient(vlm_config or _vlm_ocr_config(ocr_config))
        warnings: List[str] = []
        model_calls = {"glm_ocr": 0, "vlm_ocr": 0}

        if target == "tables":
            items = _extract_tables(ctx, glm, vlm, describe, model_calls, warnings)
            return _base_result(tool, ctx, model_calls, warnings, items=items)
        if target == "formulas":
            items = _extract_formulas(ctx, glm, vlm, describe, model_calls, warnings)
            return _base_result(tool, ctx, model_calls, warnings, items=items)
        if target == "figures":
            items = _extract_figures(ctx, vlm, model_calls, warnings)
            return _base_result(tool, ctx, model_calls, warnings, items=items)

        tables = _extract_tables(ctx, glm, vlm, describe, model_calls, warnings, allow_native=True)
        formulas = _extract_formulas(ctx, glm, vlm, describe, model_calls, warnings)
        figures = _extract_figures(ctx, vlm, model_calls, warnings)
        figure_semantics_missing = any(
            item.startswith("vlm_ocr_unavailable_for_figure_description") or item.startswith("vlm_ocr_failed")
            for item in warnings
        )
        semantic_status = {
            "complete": not figure_semantics_missing,
            "missing": ["figure_description"] if figure_semantics_missing else [],
            "reason": "vlm_ocr_unavailable_or_failed" if figure_semantics_missing else "",
        }
        return {
            "tool": tool,
            "source": _source_payload(ctx),
            "tables": tables,
            "formulas": formulas,
            "figures": figures,
            "semantic_status": semantic_status,
            "model_calls": model_calls,
            "warnings": _dedupe(warnings),
        }


def _prepare_context(
    work_dir: Path,
    file_path: Optional[str],
    file_data: Optional[str],
    file_url: Optional[str],
    page_no: int,
    input_type: str,
    routing_config: Optional[Dict[str, Any]],
) -> SinglePageContext:
    source_path = _resolve_single_source(work_dir, file_path, file_data, file_url)
    inferred = _infer_input_type(source_path, input_type)
    if inferred == "image":
        return SinglePageContext(
            input_type="image",
            source_path=str(source_path),
            image_path=str(source_path),
            page_no=int(page_no or 1),
            page_text="",
            native_tables=[],
        )

    rc = _routing_defaults(routing_config)
    doc = fitz.open(str(source_path))
    try:
        if page_no < 1 or page_no > len(doc):
            raise ValueError(f"page_no out of range: {page_no} / {len(doc)}")
        page = doc[page_no - 1]
        image_path = _render_page_image(
            doc,
            page_no,
            work_dir,
            dpi=int(rc.get("render_dpi", 220)),
            rotate_deg=int(rc.get("render_rotate_deg", 0)),
        )
        return SinglePageContext(
            input_type="pdf",
            source_path=str(source_path),
            image_path=str(image_path),
            page_no=int(page_no),
            page_text=page.get_text("text") or "",
            native_tables=_native_table_markdowns(page),
        )
    finally:
        doc.close()


def _extract_tables(
    ctx: SinglePageContext,
    glm: OpenAICompatibleOcrClient,
    vlm: DynamicVLMClient,
    describe: bool,
    model_calls: Dict[str, int],
    warnings: List[str],
    allow_native: bool = True,
) -> List[Dict[str, Any]]:
    if allow_native and ctx.input_type == "pdf" and ctx.native_tables:
        return [_table_item("pymupdf", table, ctx.page_text, describe) for table in ctx.native_tables]

    if glm.enabled:
        try:
            model_calls["glm_ocr"] += 1
            result = glm.extract_page(ctx.image_path, prompt=_prompt_tables(ctx.page_text, describe))
            items = [_table_item("glm_ocr", item.markdown or item.text, ctx.page_text, describe, item) for item in result.tables]
            if items:
                return items
            warnings.append("glm_ocr_returned_no_tables")
        except Exception as exc:
            warnings.append(f"glm_ocr_failed: {exc}")

    if vlm.enabled:
        try:
            model_calls["vlm_ocr"] += 1
            result = _call_vlm_structured(vlm, ctx.image_path, _prompt_tables(ctx.page_text, describe))
            items = [_table_item("vlm_ocr", item.markdown or item.text, ctx.page_text, describe, item) for item in result.tables]
            if items:
                return items
            warnings.append("vlm_ocr_returned_no_tables")
        except Exception as exc:
            warnings.append(f"vlm_ocr_failed: {exc}")
    else:
        warnings.append("vlm_ocr_unavailable")
    return []


def _extract_formulas(
    ctx: SinglePageContext,
    glm: OpenAICompatibleOcrClient,
    vlm: DynamicVLMClient,
    describe: bool,
    model_calls: Dict[str, int],
    warnings: List[str],
) -> List[Dict[str, Any]]:
    if glm.enabled:
        try:
            model_calls["glm_ocr"] += 1
            result = glm.extract_page(ctx.image_path, prompt=_prompt_formulas(ctx.page_text, describe))
            items = [_formula_item("glm_ocr", item, ctx.page_text, describe) for item in result.formulas]
            if items:
                return items
            warnings.append("glm_ocr_returned_no_formulas")
        except Exception as exc:
            warnings.append(f"glm_ocr_failed: {exc}")

    if vlm.enabled:
        try:
            model_calls["vlm_ocr"] += 1
            result = _call_vlm_structured(vlm, ctx.image_path, _prompt_formulas(ctx.page_text, describe))
            items = [_formula_item("vlm_ocr", item, ctx.page_text, describe) for item in result.formulas]
            if items:
                return items
            warnings.append("vlm_ocr_returned_no_formulas")
        except Exception as exc:
            warnings.append(f"vlm_ocr_failed: {exc}")
    else:
        warnings.append("vlm_ocr_unavailable")
    return []


def _extract_figures(
    ctx: SinglePageContext,
    vlm: DynamicVLMClient,
    model_calls: Dict[str, int],
    warnings: List[str],
) -> List[Dict[str, Any]]:
    if not vlm.enabled:
        warnings.append("vlm_ocr_unavailable_for_figure_description")
        return []
    try:
        model_calls["vlm_ocr"] += 1
        result = _call_vlm_structured(vlm, ctx.image_path, _prompt_figures(ctx.page_text))
        items = [_figure_item(item, ctx.page_text) for item in result.figures]
        if items:
            return items
        warnings.append("vlm_ocr_returned_no_figures")
    except Exception as exc:
        warnings.append(f"vlm_ocr_failed: {exc}")
    return []


def _call_vlm_structured(vlm: DynamicVLMClient, image_path: str, prompt: str) -> OcrResult:
    text = vlm._call_image_prompt(image_path, prompt, max_tokens=min(vlm.max_tokens, 4096))
    return normalize_text_response(text, "vlm_ocr")


def _native_table_markdowns(page: fitz.Page) -> List[str]:
    try:
        finder = page.find_tables()
        tables = list(finder.tables) if finder else []
    except Exception:
        tables = []
    out = []
    for table in tables:
        markdown = _table_to_markdown(table)
        if markdown.strip():
            out.append(markdown)
    return out


def _table_item(
    source: str,
    markdown: str,
    page_text: str,
    describe: bool,
    raw_item: Optional[OcrElement] = None,
) -> Dict[str, Any]:
    table_md = str(markdown or "").strip()
    title = (raw_item.title if raw_item else "") or _find_table_title(page_text) or _table_title_from_markdown(table_md)
    desc = (raw_item.description if raw_item else "") if describe else ""
    if describe and not desc:
        desc = _describe_table(title, table_md, page_text)
    return {
        "source": source,
        "title": title,
        "markdown": table_md,
        "description": desc,
        "context": (raw_item.context if raw_item else "") or _near_context(page_text, title),
    }


def _formula_item(source: str, item: OcrElement, page_text: str, describe: bool) -> Dict[str, Any]:
    latex = str(item.latex or item.text or "").strip()
    context = item.context or _formula_context(page_text)
    desc = item.description if describe else ""
    if describe and not desc:
        desc = context[:180] if context else "Formula extracted from the selected page."
    return {
        "source": source,
        "latex": latex,
        "description": desc,
        "variables": (item.raw.get("variables") or _variables_context(page_text)) if isinstance(item.raw, dict) else _variables_context(page_text),
        "context": context,
    }


def _figure_item(item: OcrElement, page_text: str) -> Dict[str, Any]:
    desc = str(item.description or item.text or item.caption or "").strip()
    caption = item.caption or _figure_caption(desc) or _figure_caption(page_text)
    labels = item.raw.get("labels", []) if isinstance(item.raw, dict) else []
    if not isinstance(labels, list):
        labels = []
    labels = [str(x).strip() for x in labels if str(x).strip()] or _figure_labels(desc)
    return {
        "source": "vlm_ocr",
        "caption": caption,
        "type": str(item.raw.get("type") or _figure_type(desc)) if isinstance(item.raw, dict) else _figure_type(desc),
        "description": desc,
        "labels": labels,
        "context": item.context or _near_context(page_text, caption),
    }


def _base_result(
    tool: str,
    ctx: SinglePageContext,
    model_calls: Dict[str, int],
    warnings: List[str],
    items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "tool": tool,
        "source": _source_payload(ctx),
        "items": items,
        "model_calls": model_calls,
        "warnings": _dedupe(warnings),
    }


def _source_payload(ctx: SinglePageContext) -> Dict[str, Any]:
    return {
        "input_type": ctx.input_type,
        "page_no": ctx.page_no,
        "source_sha1": _file_sha1(ctx.source_path),
    }


def _serialize_result(result: Dict[str, Any], output_format: str) -> str:
    fmt = str(output_format or "json").strip().lower()
    if fmt == "json":
        return json.dumps(result, ensure_ascii=False)
    if fmt == "markdown":
        return _result_to_markdown(result)
    raise ValueError("output_format must be json or markdown")


def _result_to_markdown(result: Dict[str, Any]) -> str:
    tool = result.get("tool")
    page_no = (result.get("source") or {}).get("page_no", 1)
    if tool == "extract_page_structured":
        parts = [f"# Page {page_no} Structured Elements"]
        parts.extend(_tables_markdown(result.get("tables") or []))
        parts.extend(_formulas_markdown(result.get("formulas") or []))
        parts.extend(_figures_markdown(result.get("figures") or []))
        return "\n\n".join([p for p in parts if p]).strip()

    title = {
        "extract_page_tables": "Tables",
        "extract_page_formulas": "Formulas",
        "extract_page_figures": "Figures",
    }.get(str(tool), "Elements")
    items = result.get("items") or []
    parts = [f"# Page {page_no} {title}"]
    if tool == "extract_page_tables":
        parts.extend(_tables_markdown(items))
    elif tool == "extract_page_formulas":
        parts.extend(_formulas_markdown(items))
    elif tool == "extract_page_figures":
        parts.extend(_figures_markdown(items))
    if not items:
        parts.append("_No items extracted._")
    return "\n\n".join([p for p in parts if p]).strip()


def _tables_markdown(items: List[Dict[str, Any]]) -> List[str]:
    out = []
    for idx, item in enumerate(items, 1):
        title = item.get("title") or f"Table {idx}"
        desc = item.get("description") or ""
        table = item.get("markdown") or ""
        out.append(f"## {title}\n\n{desc}\n\n{table}".strip())
    return out


def _formulas_markdown(items: List[Dict[str, Any]]) -> List[str]:
    out = []
    for idx, item in enumerate(items, 1):
        desc = item.get("description") or ""
        latex = item.get("latex") or ""
        variables = item.get("variables") or ""
        block = f"## Formula {idx}\n\n{desc}\n\n$$\n{latex}\n$$"
        if variables:
            block += f"\n\n{variables}"
        out.append(block.strip())
    return out


def _figures_markdown(items: List[Dict[str, Any]]) -> List[str]:
    out = []
    for idx, item in enumerate(items, 1):
        title = item.get("caption") or f"Figure {idx}"
        labels = item.get("labels") or []
        label_line = f"Labels: {', '.join(labels)}" if labels else ""
        out.append(
            f"## {title}\n\nType: {item.get('type') or 'unknown'}\n\n{item.get('description') or ''}\n\n{label_line}".strip()
        )
    return out


def _resolve_single_source(
    work_dir: Path,
    file_path: Optional[str],
    file_data: Optional[str],
    file_url: Optional[str],
) -> Path:
    source_count = sum([bool(file_path), bool(file_data), bool(file_url)])
    if source_count != 1:
        raise ValueError("exactly one source is required: file_path, file_data, or file_url")
    if file_path:
        path = Path(file_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"file_path does not exist: {path}")
        return path
    if file_data:
        raw = base64.b64decode(file_data)
        ext = _extension_from_bytes(raw)
        path = work_dir / f"single_page_source{ext}"
        path.write_bytes(raw)
        return path
    assert file_url is not None
    parsed = urllib.parse.urlparse(file_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("file_url must use http or https")
    with urllib.request.urlopen(file_url, timeout=120) as response:
        raw = response.read()
    ext = Path(parsed.path).suffix.lower() or _extension_from_bytes(raw)
    if ext not in IMAGE_EXTENSIONS and ext not in PDF_EXTENSIONS:
        ext = _extension_from_bytes(raw)
    path = work_dir / f"single_page_source{ext}"
    path.write_bytes(raw)
    return path


def _infer_input_type(path: Path, requested: str) -> str:
    value = str(requested or "auto").strip().lower()
    if value in {"pdf", "image"}:
        return value
    if value != "auto":
        raise ValueError("input_type must be auto, pdf, or image")
    suffix = path.suffix.lower()
    if suffix in PDF_EXTENSIONS:
        return "pdf"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    raise ValueError(f"cannot infer input_type from file extension: {suffix}")


def _extension_from_bytes(raw: bytes) -> str:
    if raw.startswith(b"%PDF"):
        return ".pdf"
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if raw.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        return ".webp"
    if raw.startswith(b"BM"):
        return ".bmp"
    if raw.startswith(b"II*\x00") or raw.startswith(b"MM\x00*"):
        return ".tiff"
    return ".bin"


def _merge_routing_ocr_config(routing_config: Optional[Dict[str, Any]], ocr_config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged = dict(routing_config or {})
    if ocr_config:
        merged["ocr_config"] = ocr_config
    return merged


def _vlm_ocr_config(ocr_config: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(ocr_config, dict):
        return None
    cfg = ocr_config.get("vlm_ocr")
    if isinstance(cfg, dict) and cfg.get("enabled", True):
        return cfg
    return None


def _prompt_tables(page_text: str, describe: bool) -> str:
    return (
        "Extract tables only from this single page image. Ignore formulas except formulas inside table cells. "
        "Ignore figures and diagrams. Return strict JSON only: "
        "{\"tables\":[{\"title\":\"\",\"markdown\":\"\",\"description\":\"\",\"context\":\"\"}],\"formulas\":[],\"figures\":[]}.\n"
        f"Descriptions required: {bool(describe)}.\n"
        f"Text-layer context, if useful:\n{_trim_context(page_text)}"
    )


def _prompt_formulas(page_text: str, describe: bool) -> str:
    return (
        "Extract formulas only from this single page image. Ignore tables and figures. "
        "Return formulas as LaTeX and include visible variable explanations. Return strict JSON only: "
        "{\"formulas\":[{\"latex\":\"\",\"description\":\"\",\"variables\":\"\",\"context\":\"\"}],\"tables\":[],\"figures\":[]}.\n"
        f"Descriptions required: {bool(describe)}.\n"
        f"Text-layer context, if useful:\n{_trim_context(page_text)}"
    )


def _prompt_figures(page_text: str) -> str:
    return (
        "Extract figures and technical diagrams only from this single page image. Ignore tables and formulas. "
        "Describe the visual semantics, labels, caption, and figure type. Return strict JSON only: "
        "{\"figures\":[{\"caption\":\"\",\"type\":\"schematic|chart|diagram|figure|unknown\",\"description\":\"\",\"labels\":[],\"context\":\"\"}],\"tables\":[],\"formulas\":[]}.\n"
        f"Text-layer context, if useful:\n{_trim_context(page_text)}"
    )


def _validate_output_target(target: str) -> None:
    if target not in {"tables", "formulas", "figures", "structured"}:
        raise ValueError(f"unsupported target: {target}")


def _trim_context(text: str, limit: int = 1800) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(value) <= limit:
        return value
    return value[:limit].rstrip()


def _find_table_title(page_text: str) -> str:
    for line in str(page_text or "").splitlines():
        t = line.strip()
        if re.match(r"^(表|Table)\s*", t, flags=re.IGNORECASE):
            return t[:120]
    return ""


def _table_title_from_markdown(markdown: str) -> str:
    rows = [ln for ln in str(markdown or "").splitlines() if "|" in ln]
    if not rows:
        return ""
    cells = [c.strip() for c in rows[0].strip("|").split("|") if c.strip()]
    return " / ".join(cells[:3])[:120]


def _describe_table(title: str, table_md: str, page_text: str) -> str:
    cols, rows = _table_shape(table_md)
    headers = _table_headers(table_md)
    if title:
        prefix = f"{title}。"
    else:
        prefix = "Table extracted from the selected page."
    if headers:
        return f"{prefix} Contains about {rows} rows and {cols} columns. Fields include {', '.join(headers[:8])}."
    context = _near_context(page_text, title)
    if context:
        return context[:180]
    return f"{prefix} Contains about {rows} rows and {cols} columns."


def _table_shape(table_md: str) -> tuple[int, int]:
    rows = [ln for ln in str(table_md or "").splitlines() if "|" in ln]
    if not rows:
        return 0, 0
    widths = [len([c for c in row.strip("|").split("|")]) for row in rows]
    return max(widths or [0]), len(rows)


def _table_headers(table_md: str) -> List[str]:
    for line in str(table_md or "").splitlines():
        if "|" not in line:
            continue
        if re.match(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$", line):
            continue
        return [c.strip() for c in line.strip("|").split("|") if c.strip()]
    return []


def _formula_context(page_text: str) -> str:
    lines = [ln.strip() for ln in str(page_text or "").splitlines() if ln.strip()]
    for idx, line in enumerate(lines):
        if "式中" in line or re.search(r"按.*式|公式|计算式", line):
            start = max(0, idx - 2)
            end = min(len(lines), idx + 5)
            return " ".join(lines[start:end])[:300]
    return _trim_context(page_text, 240)


def _variables_context(page_text: str) -> str:
    lines = [ln.strip() for ln in str(page_text or "").splitlines() if ln.strip()]
    for idx, line in enumerate(lines):
        if "式中" in line:
            return " ".join(lines[idx : idx + 5])[:300]
    return ""


def _figure_caption(text: str) -> str:
    m = re.search(r"(图\s*\d+(?:[.-]\d+)?[^，。;\n]*)", str(text or ""))
    return m.group(1).strip() if m else ""


def _figure_type(text: str) -> str:
    low = str(text or "").lower()
    if "schematic" in low or "示意" in str(text or ""):
        return "schematic"
    if "chart" in low or "curve" in low or "图表" in str(text or ""):
        return "chart"
    if "diagram" in low or "cross-section" in low or "剖面" in str(text or ""):
        return "diagram"
    if text:
        return "figure"
    return "unknown"


def _figure_labels(text: str) -> List[str]:
    labels = re.findall(r"\b[A-Z][A-Za-z0-9_./-]{0,12}\b", str(text or ""))
    labels.extend(re.findall(r"[A-Za-z]\s*[≥≤=]\s*[\d.]+[A-Za-z]*", str(text or "")))
    return _dedupe([x.strip() for x in labels if x.strip()])[:12]


def _near_context(page_text: str, anchor: str) -> str:
    lines = [ln.strip() for ln in str(page_text or "").splitlines() if ln.strip()]
    if not lines:
        return ""
    if anchor:
        for idx, line in enumerate(lines):
            if anchor in line:
                start = max(0, idx - 2)
                end = min(len(lines), idx + 3)
                return " ".join(lines[start:end])[:300]
    return " ".join(lines[:3])[:300]


def _file_sha1(path: str) -> str:
    data = Path(path).read_bytes()
    return hashlib.sha1(data).hexdigest()


def _dedupe(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for item in items:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out
