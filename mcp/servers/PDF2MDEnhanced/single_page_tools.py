from __future__ import annotations

import base64
import hashlib
import html
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


def analyze_page_layout_direct(
    file_path: Optional[str] = None,
    file_data: Optional[str] = None,
    file_url: Optional[str] = None,
    page_no: int = 1,
    input_type: str = "auto",
    output_format: str = "json",
    ocr_config: Optional[Dict[str, Any]] = None,
    routing_config: Optional[Dict[str, Any]] = None,
    return_crop_images: bool = False,
    need_layout_visualization: bool = False,
) -> str:
    result = _analyze_single_page_layout(
        file_path=file_path,
        file_data=file_data,
        file_url=file_url,
        page_no=page_no,
        input_type=input_type,
        ocr_config=ocr_config,
        routing_config=routing_config,
        return_crop_images=return_crop_images,
        need_layout_visualization=need_layout_visualization,
    )
    return _serialize_result(result, output_format)


def extract_page_layout_enhanced_direct(
    file_path: Optional[str] = None,
    file_data: Optional[str] = None,
    file_url: Optional[str] = None,
    page_no: int = 1,
    input_type: str = "auto",
    output_format: str = "json",
    ocr_config: Optional[Dict[str, Any]] = None,
    vlm_config: Optional[Dict[str, Any]] = None,
    routing_config: Optional[Dict[str, Any]] = None,
    storage_config: Optional[Dict[str, Any]] = None,
    image_prefix: str = "figures",
) -> str:
    _ = storage_config
    _ = image_prefix
    result = _extract_layout_enhanced(
        file_path=file_path,
        file_data=file_data,
        file_url=file_url,
        page_no=page_no,
        input_type=input_type,
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
            return _extract_formula_page_result(ctx, glm, vlm, describe, model_calls, warnings)
        if target == "figures":
            return _extract_figure_page_result(ctx, vlm, model_calls, warnings)

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


def _analyze_single_page_layout(
    file_path: Optional[str],
    file_data: Optional[str],
    file_url: Optional[str],
    page_no: int,
    input_type: str,
    ocr_config: Optional[Dict[str, Any]],
    routing_config: Optional[Dict[str, Any]],
    return_crop_images: bool,
    need_layout_visualization: bool,
) -> Dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="pdf2md_enh_layout_") as work_dir:
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
        warnings: List[str] = []
        model_calls = {"glm_ocr": 0, "vlm_ocr": 0}
        markdown = ""
        blocks: List[Dict[str, Any]] = []
        raw: Dict[str, Any] = {}
        if not glm.enabled:
            warnings.append("glm_ocr_unavailable_for_layout_analysis")
        else:
            try:
                model_calls["glm_ocr"] += 1
                raw = glm.parse_layout(
                    ctx.image_path,
                    return_crop_images=return_crop_images,
                    need_layout_visualization=need_layout_visualization,
                )
                markdown = str(raw.get("md_results") or raw.get("markdown") or "").strip()
                blocks = _layout_blocks_from_raw(raw)
            except Exception as exc:
                warnings.append(f"glm_ocr_failed: {exc}")

        return {
            "tool": "analyze_page_layout",
            "source": _source_payload(ctx),
            "markdown": markdown,
            "blocks": blocks,
            "summary": _layout_summary(blocks),
            "layout_visualization": raw.get("layout_visualization") or [],
            "data_info": raw.get("data_info") or {},
            "model_calls": model_calls,
            "warnings": _dedupe(warnings),
        }


def _extract_layout_enhanced(
    file_path: Optional[str],
    file_data: Optional[str],
    file_url: Optional[str],
    page_no: int,
    input_type: str,
    ocr_config: Optional[Dict[str, Any]],
    vlm_config: Optional[Dict[str, Any]],
    routing_config: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="pdf2md_enh_layout_enh_") as work_dir:
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
        raw: Dict[str, Any] = {}
        markdown = ""
        blocks: List[Dict[str, Any]] = []
        if not glm.enabled:
            warnings.append("glm_ocr_unavailable_for_layout_enhanced")
        else:
            try:
                model_calls["glm_ocr"] += 1
                raw = glm.parse_layout(ctx.image_path)
                markdown = str(raw.get("md_results") or raw.get("markdown") or "").strip()
                blocks = _layout_blocks_from_raw(raw)
            except Exception as exc:
                warnings.append(f"glm_ocr_failed: {exc}")

        figures = _figures_from_layout_blocks(blocks)
        if figures:
            figures = _enhance_layout_figures_with_vlm(ctx, figures, blocks, vlm, model_calls, warnings)

        return {
            "tool": "extract_page_layout_enhanced",
            "source": _source_payload(ctx),
            "markdown": markdown,
            "blocks": blocks,
            "tables": _tables_from_layout_blocks(blocks),
            "formulas": _formulas_from_layout_blocks(blocks),
            "figures": figures,
            "summary": _layout_summary(blocks),
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
            if not items:
                recovered = _recover_table_from_result(result)
                if recovered:
                    items = [_table_item("glm_ocr", recovered, ctx.page_text, describe)]
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
            if not items:
                recovered = _recover_table_from_result(result)
                if recovered:
                    items = [_table_item("vlm_ocr", recovered, ctx.page_text, describe)]
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
            items = _formula_items_from_result("glm_ocr", result, ctx.page_text, describe)
            if items:
                return items
            warnings.append("glm_ocr_returned_no_formulas")
        except Exception as exc:
            warnings.append(f"glm_ocr_failed: {exc}")

    if vlm.enabled:
        try:
            model_calls["vlm_ocr"] += 1
            result = _call_vlm_structured(vlm, ctx.image_path, _prompt_formulas(ctx.page_text, describe))
            items = _formula_items_from_result("vlm_ocr", result, ctx.page_text, describe)
            if items:
                return items
            warnings.append("vlm_ocr_returned_no_formulas")
        except Exception as exc:
            warnings.append(f"vlm_ocr_failed: {exc}")
    else:
        warnings.append("vlm_ocr_unavailable")
    return []


def _extract_formula_page_result(
    ctx: SinglePageContext,
    glm: OpenAICompatibleOcrClient,
    vlm: DynamicVLMClient,
    describe: bool,
    model_calls: Dict[str, int],
    warnings: List[str],
) -> Dict[str, Any]:
    page_markdown = ""
    items: List[Dict[str, Any]] = []
    if glm.enabled:
        try:
            model_calls["glm_ocr"] += 1
            result = glm.extract_page(ctx.image_path, prompt=_prompt_formula_page(ctx.page_text, describe))
            page_markdown = _normalize_page_markdown(result.markdown or result.page_text)
            if not page_markdown and result.formulas:
                page_markdown = _formula_page_markdown_from_items(result.formulas)
            items = _formula_items_from_markdown("glm_ocr", page_markdown, describe)
            if not items:
                items = _formula_items_from_result("glm_ocr", result, ctx.page_text, describe)
            if page_markdown or items:
                return _formula_page_result(ctx, model_calls, warnings, page_markdown, items)
            warnings.append("glm_ocr_returned_no_formula_markdown")
        except Exception as exc:
            warnings.append(f"glm_ocr_failed: {exc}")

    if vlm.enabled:
        try:
            model_calls["vlm_ocr"] += 1
            result = _call_vlm_structured(vlm, ctx.image_path, _prompt_formula_page(ctx.page_text, describe))
            page_markdown = _normalize_page_markdown(result.markdown or result.page_text)
            if not page_markdown and result.formulas:
                page_markdown = _formula_page_markdown_from_items(result.formulas)
            items = _formula_items_from_markdown("vlm_ocr", page_markdown, describe)
            if not items:
                items = _formula_items_from_result("vlm_ocr", result, ctx.page_text, describe)
            if page_markdown or items:
                return _formula_page_result(ctx, model_calls, warnings, page_markdown, items)
            warnings.append("vlm_ocr_returned_no_formula_markdown")
        except Exception as exc:
            warnings.append(f"vlm_ocr_failed: {exc}")
    else:
        warnings.append("vlm_ocr_unavailable")

    return _formula_page_result(ctx, model_calls, warnings, page_markdown, items)


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


def _extract_figure_page_result(
    ctx: SinglePageContext,
    vlm: DynamicVLMClient,
    model_calls: Dict[str, int],
    warnings: List[str],
) -> Dict[str, Any]:
    page_markdown = ""
    items: List[Dict[str, Any]] = []
    if not vlm.enabled:
        warnings.append("vlm_ocr_unavailable_for_figure_description")
        return _figure_page_result(ctx, model_calls, warnings, page_markdown, items)
    try:
        model_calls["vlm_ocr"] += 1
        result = _call_vlm_structured(vlm, ctx.image_path, _prompt_figure_page(ctx.page_text))
        page_markdown = _normalize_page_markdown(result.markdown or result.page_text)
        items = [_figure_item(item, ctx.page_text or page_markdown) for item in result.figures]
        if not page_markdown and items:
            page_markdown = _figure_page_markdown_from_items(items)
        if page_markdown or items:
            return _figure_page_result(ctx, model_calls, warnings, page_markdown, items)
        warnings.append("vlm_ocr_returned_no_figure_markdown")
    except Exception as exc:
        warnings.append(f"vlm_ocr_failed: {exc}")
    return _figure_page_result(ctx, model_calls, warnings, page_markdown, items)


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
    table_md = _normalize_table_output(str(markdown or "").strip())
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


def _formula_items_from_result(source: str, result: OcrResult, fallback_page_text: str, describe: bool) -> List[Dict[str, Any]]:
    page_text = result.page_text or result.markdown or fallback_page_text
    blocks = _formula_blocks(page_text)
    items: List[Dict[str, Any]] = []
    for idx, item in enumerate(result.formulas):
        enriched = item
        if idx < len(blocks):
            before, _formula, after = blocks[idx]
            context = item.context or _trim_formula_context(before, after)
            variables = ""
            if isinstance(item.raw, dict):
                variables = str(item.raw.get("variables") or "").strip()
            variables = variables or _extract_formula_variables(after)
            description = item.description or _formula_description_from_before(before)
            raw = dict(item.raw or {})
            if variables:
                raw["variables"] = variables
            enriched = OcrElement(
                kind=item.kind,
                source=item.source,
                text=item.text,
                title=item.title,
                markdown=item.markdown,
                latex=item.latex,
                caption=item.caption,
                description=description,
                context=context,
                raw=raw,
            )
        items.append(_formula_item(source, enriched, page_text, describe))
    return items


def _formula_items_from_markdown(source: str, markdown: str, describe: bool) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for before, formula, after in _formula_blocks(markdown):
        raw = {"variables": _extract_formula_variables(after)}
        item = OcrElement(
            kind="formula",
            source=source,
            latex=formula,
            description=_formula_description_from_before(before),
            context=_trim_formula_context(before, after),
            raw=raw,
        )
        items.append(_formula_item(source, item, markdown, describe))
    return items


def _formula_page_result(
    ctx: SinglePageContext,
    model_calls: Dict[str, int],
    warnings: List[str],
    markdown: str,
    items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "tool": "extract_page_formulas",
        "source": _source_payload(ctx),
        "markdown": markdown,
        "items": items,
        "model_calls": model_calls,
        "warnings": _dedupe(warnings),
    }


def _formula_page_markdown_from_items(items: List[OcrElement]) -> str:
    parts = []
    for item in items:
        desc = str(item.description or "").strip()
        latex = _ensure_latex_block(str(item.latex or item.text or "").strip())
        variables = str(item.raw.get("variables") or "") if isinstance(item.raw, dict) else ""
        parts.append("\n\n".join(part for part in [desc, latex, variables] if part))
    return "\n\n".join(parts).strip()


def _ensure_latex_block(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("$$") and text.endswith("$$"):
        return text
    return f"$$\n{text}\n$$"


def _normalize_page_markdown(markdown: str) -> str:
    value = str(markdown or "").strip()
    if not value:
        return ""
    value = re.sub(r"(?m)^\s*```(?:markdown|md)?\s*$", "", value)
    value = re.sub(r"(?m)^\s*```\s*$", "", value)
    return value.strip()


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


def _figure_page_result(
    ctx: SinglePageContext,
    model_calls: Dict[str, int],
    warnings: List[str],
    markdown: str,
    items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "tool": "extract_page_figures",
        "source": _source_payload(ctx),
        "markdown": markdown,
        "items": items,
        "model_calls": model_calls,
        "warnings": _dedupe(warnings),
    }


def _figure_page_markdown_from_items(items: List[Dict[str, Any]]) -> str:
    return "\n\n".join(_figures_markdown(items)).strip()


def _layout_blocks_from_raw(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []
    for page_idx, page in enumerate(raw.get("layout_details") or [], 1):
        if not isinstance(page, list):
            continue
        for item in page:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "unknown").strip().lower() or "unknown"
            bbox = item.get("bbox_2d") or []
            if not isinstance(bbox, list):
                bbox = []
            blocks.append(
                {
                    "page": page_idx,
                    "index": item.get("index"),
                    "type": label,
                    "bbox": bbox[:4],
                    "content": str(item.get("content") or ""),
                    "width": item.get("width"),
                    "height": item.get("height"),
                    "raw": item,
                }
            )
    return blocks


def _layout_summary(blocks: List[Dict[str, Any]]) -> Dict[str, Any]:
    counts: Dict[str, int] = {}
    for block in blocks:
        typ = str(block.get("type") or "unknown")
        counts[typ] = counts.get(typ, 0) + 1
    has_table = counts.get("table", 0) > 0
    has_formula = counts.get("formula", 0) > 0
    has_image = counts.get("image", 0) > 0
    has_text = counts.get("text", 0) > 0
    semantic_types = [name for name, flag in [("table", has_table), ("formula", has_formula), ("image", has_image)] if flag]
    if len(semantic_types) > 1:
        dominant = "mixed"
        recommended = "extract_page_structured"
    elif has_table:
        dominant = "table"
        recommended = "extract_page_tables"
    elif has_formula:
        dominant = "formula"
        recommended = "extract_page_formulas"
    elif has_image:
        dominant = "image"
        recommended = "extract_page_figures"
    elif has_text:
        dominant = "text"
        recommended = "none"
    else:
        dominant = "unknown"
        recommended = "extract_page_structured"
    return {
        "block_counts": counts,
        "dominant_type": dominant,
        "has_text": has_text,
        "has_table": has_table,
        "has_formula": has_formula,
        "has_image": has_image,
        "recommended_tool": recommended,
    }


def _tables_from_layout_blocks(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    tables: List[Dict[str, Any]] = []
    for block in blocks:
        if str(block.get("type") or "").lower() != "table":
            continue
        markdown = _normalize_table_output(str(block.get("content") or "").strip())
        if not markdown:
            continue
        tables.append(
            {
                "source": "glm_ocr_layout",
                "title": _table_title_from_markdown(markdown) or f"Table {len(tables) + 1}",
                "markdown": markdown,
                "description": "",
                "context": "",
                "block_index": block.get("index"),
                "bbox": block.get("bbox") or [],
            }
        )
    return tables


def _formulas_from_layout_blocks(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    formulas: List[Dict[str, Any]] = []
    for block in blocks:
        if str(block.get("type") or "").lower() != "formula":
            continue
        latex = str(block.get("content") or "").strip()
        if not latex:
            continue
        formulas.append(
            {
                "source": "glm_ocr_layout",
                "latex": _ensure_latex_block(latex),
                "description": "",
                "variables": "",
                "context": "",
                "block_index": block.get("index"),
                "bbox": block.get("bbox") or [],
            }
        )
    return formulas


def _figures_from_layout_blocks(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    figures: List[Dict[str, Any]] = []
    for block in blocks:
        if str(block.get("type") or "").lower() != "image":
            continue
        content = str(block.get("content") or "").strip()
        figures.append(
            {
                "source": "glm_ocr_layout",
                "caption": _figure_caption(content) or f"Figure {len(figures) + 1}",
                "type": "figure",
                "description": content,
                "labels": [],
                "context": "",
                "block_index": block.get("index"),
                "bbox": block.get("bbox") or [],
            }
        )
    return figures


def _enhance_layout_figures_with_vlm(
    ctx: SinglePageContext,
    figures: List[Dict[str, Any]],
    blocks: List[Dict[str, Any]],
    vlm: DynamicVLMClient,
    model_calls: Dict[str, int],
    warnings: List[str],
) -> List[Dict[str, Any]]:
    if not figures:
        return figures
    if not vlm.enabled:
        warnings.append("vlm_ocr_unavailable_for_layout_figure_description")
        return figures

    try:
        model_calls["vlm_ocr"] += 1
        result = _call_vlm_structured(vlm, ctx.image_path, _prompt_layout_figures(blocks, ctx.page_text))
    except Exception as exc:
        warnings.append(f"vlm_ocr_failed: {exc}")
        return figures

    by_index: Dict[str, OcrElement] = {}
    by_bbox: Dict[str, OcrElement] = {}
    for item in result.figures:
        raw = item.raw if isinstance(item.raw, dict) else {}
        block_index = raw.get("block_index") or raw.get("index")
        if block_index is not None:
            by_index[str(block_index)] = item
        bbox = raw.get("bbox")
        if isinstance(bbox, list):
            by_bbox[_bbox_key(bbox)] = item

    enhanced: List[Dict[str, Any]] = []
    for figure in figures:
        item = by_index.get(str(figure.get("block_index"))) or by_bbox.get(_bbox_key(figure.get("bbox") or []))
        if not item:
            enhanced.append(figure)
            continue
        enriched = dict(figure)
        detail = _figure_item(item, ctx.page_text)
        enriched.update(
            {
                "source": "glm_ocr_layout+vlm_ocr",
                "caption": detail.get("caption") or enriched.get("caption"),
                "type": detail.get("type") or enriched.get("type"),
                "description": detail.get("description") or enriched.get("description"),
                "labels": detail.get("labels") or enriched.get("labels") or [],
                "context": detail.get("context") or enriched.get("context") or "",
            }
        )
        enhanced.append(enriched)

    if all(not str(item.get("description") or "").strip() for item in enhanced):
        warnings.append("vlm_ocr_returned_no_layout_figure_descriptions")
    return enhanced


def _bbox_key(bbox: Any) -> str:
    if not isinstance(bbox, list):
        return ""
    return ",".join(str(x) for x in bbox[:4])


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
    if tool == "analyze_page_layout":
        parts = [f"# Page {page_no} Layout"]
        summary = result.get("summary") or {}
        counts = summary.get("block_counts") or {}
        parts.append(
            "\n".join(
                [
                    f"Recommended tool: `{summary.get('recommended_tool') or 'none'}`",
                    f"Dominant type: `{summary.get('dominant_type') or 'unknown'}`",
                    f"Block counts: `{json.dumps(counts, ensure_ascii=False)}`",
                ]
            )
        )
        markdown = str(result.get("markdown") or "").strip()
        if markdown:
            parts.append("## Markdown\n\n" + markdown)
        blocks = result.get("blocks") or []
        if blocks:
            lines = ["## Blocks", "", "| index | type | bbox | preview |", "| --- | --- | --- | --- |"]
            for block in blocks:
                preview = re.sub(r"\s+", " ", str(block.get("content") or "")).strip()[:80].replace("|", "\\|")
                lines.append(f"| {block.get('index')} | {block.get('type')} | {block.get('bbox')} | {preview} |")
            parts.append("\n".join(lines))
        return "\n\n".join([p for p in parts if p]).strip()

    if tool == "extract_page_layout_enhanced":
        parts = [f"# Page {page_no} Enhanced Layout Extraction"]
        summary = result.get("summary") or {}
        counts = summary.get("block_counts") or {}
        parts.append(
            "\n".join(
                [
                    f"Recommended tool: `{summary.get('recommended_tool') or 'none'}`",
                    f"Dominant type: `{summary.get('dominant_type') or 'unknown'}`",
                    f"Block counts: `{json.dumps(counts, ensure_ascii=False)}`",
                ]
            )
        )
        markdown = str(result.get("markdown") or "").strip()
        if markdown:
            parts.append("## Page Markdown\n\n" + markdown)
        blocks = result.get("blocks") or []
        if blocks:
            lines = ["## Layout Blocks", "", "| index | type | bbox | preview |", "| --- | --- | --- | --- |"]
            for block in blocks:
                preview = re.sub(r"\s+", " ", str(block.get("content") or "")).strip()[:80].replace("|", "\\|")
                lines.append(f"| {block.get('index')} | {block.get('type')} | {block.get('bbox')} | {preview} |")
            parts.append("\n".join(lines))
        return "\n\n".join([p for p in parts if p]).strip()

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
        page_markdown = str(result.get("markdown") or "").strip()
        if page_markdown:
            parts.append(page_markdown)
        else:
            parts.extend(_formulas_markdown(items))
    elif tool == "extract_page_figures":
        page_markdown = str(result.get("markdown") or "").strip()
        if page_markdown:
            parts.append(page_markdown)
        else:
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
        "识别截图中的表格内容，输出严格 JSON，不要输出 Markdown、HTML 或解释。\n"
        "请按表格网格线逐行逐列读取，不能按文本连续顺序重排。\n"
        "规则：\n"
        "1. 识别表名。\n"
        "2. 分离行标题、列分组标题、列标题；行标题不要混入列标题。\n"
        "3. 如果有多级表头，保留最上层列分组标题。\n"
        "4. 数据区按行输出，每行必须包含所有列标题对应的字段。\n"
        "5. 空白单元格必须输出字符串 \"n/a\"，不能省略，不能输出空字符串。\n"
        "6. 禁止因为空白单元格导致后续数值左移。\n"
        "7. 单元格数字必须按图中原样抄录，不要根据相邻数字推断或修正。\n"
        "8. 看不清的单元格输出 \"n/a\"，不要猜。\n"
        "9. 输出前自检：每行字段集合必须完全一致，且包含所有列标题。\n"
        "JSON schema："
        "{\"表名\":\"\",\"行标题\":\"\",\"列分组标题\":\"\",\"列标题\":[],\"数据\":[{\"行标题值\":\"\",\"列1\":\"\",\"列2\":\"\"}]}。\n"
        f"是否需要语义描述：{bool(describe)}。\n"
        f"可用的文本层上下文：\n{_trim_context(page_text)}"
    )


def _prompt_formulas(page_text: str, describe: bool) -> str:
    return (
        "Extract formulas only from this single page image. Ignore tables and figures. "
        "Return formulas as LaTeX and include visible variable explanations. Return strict JSON only: "
        "{\"formulas\":[{\"latex\":\"\",\"description\":\"\",\"variables\":\"\",\"context\":\"\"}],\"tables\":[],\"figures\":[]}.\n"
        f"Descriptions required: {bool(describe)}.\n"
        f"Text-layer context, if useful:\n{_trim_context(page_text)}"
    )


def _prompt_formula_page(page_text: str, describe: bool) -> str:
    return (
        "识别这张单页图片中的公式页内容，只关注公式、公式标题、公式前后说明、式中变量说明和相关正文。"
        "忽略表格和图的结构化抽取。请按页面自然阅读顺序输出 Markdown，尽量保持原有层级、段落顺序和公式位置。"
        "所有公式必须转换为 LaTeX，并用 $$...$$ 块包裹。"
        "如果输入只是局部公式截图，也按同样规则返回该局部的 Markdown。"
        "不要输出 JSON，不要额外解释。\n"
        f"是否需要保留说明文字：{bool(describe)}。\n"
        f"可用的文本层上下文：\n{_trim_context(page_text)}"
    )


def _prompt_figures(page_text: str) -> str:
    return (
        "Extract figures and technical diagrams only from this single page image. Ignore tables and formulas. "
        "Describe the visual semantics, labels, caption, and figure type. Return strict JSON only: "
        "{\"figures\":[{\"caption\":\"\",\"type\":\"schematic|chart|diagram|figure|unknown\",\"description\":\"\",\"labels\":[],\"context\":\"\"}],\"tables\":[],\"formulas\":[]}.\n"
        f"Text-layer context, if useful:\n{_trim_context(page_text)}"
    )


def _prompt_figure_page(page_text: str) -> str:
    return (
        "识别这张单页图片中的含插图页面内容，只关注正文、图题、图注、插图位置和插图语义描述。"
        "忽略表格和公式的结构化抽取。请按页面自然阅读顺序输出严格 JSON："
        "{\"markdown\":\"整页Markdown，保留正文顺序，并在插图位置写图题和图描述\","
        "\"figures\":[{\"caption\":\"\",\"type\":\"schematic|chart|diagram|figure|unknown\","
        "\"description\":\"\",\"labels\":[],\"context\":\"\"}],\"tables\":[],\"formulas\":[]}。"
        "Markdown 中的每个插图应包含图题和简洁但具体的图像描述。"
        f"可用的文本层上下文：\n{_trim_context(page_text)}"
    )


def _prompt_layout_figures(blocks: List[Dict[str, Any]], page_text: str) -> str:
    image_blocks = [
        {
            "block_index": block.get("index"),
            "bbox": block.get("bbox") or [],
            "content": str(block.get("content") or "")[:300],
        }
        for block in blocks
        if str(block.get("type") or "").lower() == "image"
    ]
    context_blocks = [
        {
            "index": block.get("index"),
            "type": block.get("type"),
            "bbox": block.get("bbox") or [],
            "content": str(block.get("content") or "")[:300],
        }
        for block in blocks
        if str(block.get("type") or "").lower() in {"text", "title", "caption"}
    ][:12]
    return (
        "这是一张已经做过版面识别的单页图片。请只描述给定 image blocks 对应位置中的插图/示意图/图表，"
        "不要重新抽取表格、公式或正文。你会看到整页图片，请根据每个 block 的 bbox 定位图像区域并生成语义描述。\n"
        "必须严格按 JSON 返回："
        "{\"figures\":[{\"block_index\":1,\"bbox\":[0,0,1,1],\"caption\":\"\","
        "\"type\":\"schematic|chart|diagram|figure|unknown\",\"description\":\"\","
        "\"labels\":[],\"context\":\"\"}],\"tables\":[],\"formulas\":[]}。\n"
        "要求：每个输入 image block 最多返回一个对应 figure；block_index 和 bbox 必须原样保留；"
        "description 要说明图中表达的对象、结构关系、关键标注和可读文字。\n"
        f"image blocks:\n{json.dumps(image_blocks, ensure_ascii=False)}\n"
        f"nearby text/layout context:\n{json.dumps(context_blocks, ensure_ascii=False)}\n"
        f"text-layer context:\n{_trim_context(page_text)}"
    )


def _validate_output_target(target: str) -> None:
    if target not in {"tables", "formulas", "figures", "structured"}:
        raise ValueError(f"unsupported target: {target}")


def _recover_table_markdown(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    markdown = _extract_first_markdown_table(value)
    if markdown:
        return markdown
    return _html_table_to_markdown(value)


def _recover_table_from_result(result: OcrResult) -> str:
    raw = result.raw if isinstance(result.raw, dict) else {}
    candidates = [
        result.markdown,
        result.page_text,
        raw.get("text"),
        raw.get("content"),
        raw.get("response"),
        raw.get("message"),
    ]
    for candidate in candidates:
        if isinstance(candidate, dict):
            candidate = candidate.get("content") or candidate.get("text")
        recovered = _recover_table_markdown(str(candidate or ""))
        if recovered:
            return recovered
    return ""


def _normalize_table_output(table_md: str) -> str:
    value = str(table_md or "").strip()
    if "<table" in value.lower():
        return _fill_empty_html_table_cells(value)
    return value


def _fill_empty_html_table_cells(table_html: str) -> str:
    def repl(match: re.Match[str]) -> str:
        tag = match.group(1)
        attrs = match.group(2) or ""
        body = match.group(3) or ""
        visible = _clean_html_cell(body)
        if visible == "n/a":
            return f"<{tag}{attrs}>n/a</{tag}>"
        return match.group(0)

    return re.sub(r"(?is)<(td|th)\b([^>]*)>(.*?)</\1>", repl, str(table_html or ""))


def _extract_first_markdown_table(text: str) -> str:
    lines = str(text or "").splitlines()
    blocks: List[List[str]] = []
    current: List[str] = []
    for line in lines:
        if "|" in line:
            current.append(line.strip())
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    for block in blocks:
        if len(block) >= 2 and any(re.search(r"\|\s*:?-{3,}:?\s*\|", row) for row in block):
            return "\n".join(block).strip()
    return ""


def _html_table_to_markdown(text: str) -> str:
    if "<table" not in str(text or "").lower():
        return ""
    match = re.search(r"(?is)<table\b[^>]*>.*?</table>", text)
    table = match.group(0) if match else text
    grid: List[List[str]] = []
    row_index = 0
    for row_match in re.finditer(r"(?is)<tr\b[^>]*>(.*?)</tr>", table):
        while len(grid) <= row_index:
            grid.append([])
        row = grid[row_index]
        col_index = 0
        for cell_match in re.finditer(r"(?is)<(td|th)\b([^>]*)>(.*?)</\1>", row_match.group(1)):
            while col_index < len(row) and row[col_index] is not None:
                col_index += 1
            attrs = cell_match.group(2)
            cell_text = _clean_html_cell(cell_match.group(3))
            rowspan = max(1, _html_int_attr(attrs, "rowspan"))
            colspan = max(1, _html_int_attr(attrs, "colspan"))
            for r in range(rowspan):
                while len(grid) <= row_index + r:
                    grid.append([])
                target = grid[row_index + r]
                _ensure_row_width(target, col_index + colspan)
                for c in range(colspan):
                    target[col_index + c] = cell_text if r == 0 and c == 0 else "n/a"
            col_index += colspan
        row_index += 1
    normalized = [
        [cell if cell is not None else "n/a" for cell in row]
        for row in grid
        if any(str(cell or "").strip() for cell in row)
    ]
    if not normalized:
        return ""
    width = max(len(row) for row in normalized)
    for row in normalized:
        _ensure_row_width(row, width)
    lines = [
        "| " + " | ".join(_escape_markdown_cell(cell) for cell in normalized[0]) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    lines.extend("| " + " | ".join(_escape_markdown_cell(cell) for cell in row) + " |" for row in normalized[1:])
    return "\n".join(lines).strip()


def _html_int_attr(attrs: str, name: str) -> int:
    match = re.search(rf"(?i)\b{re.escape(name)}\s*=\s*['\"]?(\d+)", str(attrs or ""))
    return int(match.group(1)) if match else 1


def _clean_html_cell(value: str) -> str:
    text = re.sub(r"(?is)<br\s*/?>", "\n", str(value or ""))
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or "n/a"


def _ensure_row_width(row: List[str], width: int) -> None:
    while len(row) < width:
        row.append("n/a")


def _escape_markdown_cell(value: str) -> str:
    return str(value or "n/a").replace("|", "\\|")


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
    html_rows = _html_table_rows(table_md)
    if html_rows:
        return max((sum(cell[1] for cell in row) for row in html_rows), default=0), len(html_rows)

    rows = [ln for ln in str(table_md or "").splitlines() if "|" in ln]
    if not rows:
        return 0, 0
    widths = [len([c for c in row.strip("|").split("|")]) for row in rows]
    return max(widths or [0]), len(rows)


def _table_headers(table_md: str) -> List[str]:
    html_rows = _html_table_rows(table_md)
    if html_rows:
        return [cell[0] for cell in html_rows[0] if cell[0]]

    for line in str(table_md or "").splitlines():
        if "|" not in line:
            continue
        if re.match(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$", line):
            continue
        return [c.strip() for c in line.strip("|").split("|") if c.strip()]
    return []


def _html_table_rows(table_md: str) -> List[List[tuple[str, int]]]:
    text = str(table_md or "")
    if "<table" not in text.lower():
        return []
    rows: List[List[tuple[str, int]]] = []
    for row_match in re.finditer(r"(?is)<tr\b[^>]*>(.*?)</tr>", text):
        cells: List[tuple[str, int]] = []
        for cell_match in re.finditer(r"(?is)<t[dh]\b([^>]*)>(.*?)</t[dh]>", row_match.group(1)):
            attrs = cell_match.group(1) or ""
            content = cell_match.group(2) or ""
            colspan_match = re.search(r'(?i)\bcolspan\s*=\s*["\']?(\d+)', attrs)
            colspan = int(colspan_match.group(1)) if colspan_match else 1
            value = _clean_html_cell(content)
            cells.append((value, max(colspan, 1)))
        if cells:
            rows.append(cells)
    return rows


def _formula_context(page_text: str) -> str:
    lines = [ln.strip() for ln in str(page_text or "").splitlines() if ln.strip()]
    for idx, line in enumerate(lines):
        if "式中" in line or re.search(r"按.*式|公式|计算式", line):
            start = max(0, idx - 2)
            end = min(len(lines), idx + 5)
            return " ".join(lines[start:end])[:300]
    return _trim_context(page_text, 240)


def _formula_blocks(page_text: str) -> List[tuple[str, str, str]]:
    text = str(page_text or "")
    matches = list(re.finditer(r"(?s)\$\$(.*?)\$\$", text))
    blocks: List[tuple[str, str, str]] = []
    for idx, match in enumerate(matches):
        before_start = matches[idx - 1].end() if idx > 0 else 0
        after_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        blocks.append((text[before_start : match.start()], match.group(0), text[match.end() : after_end]))
    return blocks


def _trim_formula_context(before: str, after: str) -> str:
    intro = _formula_description_from_before(before)
    variables = _extract_formula_variables(after)
    combined = " ".join(part for part in [intro, variables] if part)
    return _trim_context(combined, 900)


def _formula_description_from_before(before: str) -> str:
    lines = [ln.strip() for ln in str(before or "").splitlines() if ln.strip()]
    for line in reversed(lines):
        if line.startswith("#"):
            continue
        if "公式" in line or "计算" in line or "面积" in line:
            return line[:240]
    return lines[-1][:240] if lines else ""


def _extract_formula_variables(after: str) -> str:
    text = str(after or "")
    m = re.search(r"(?s)(式中[:：].*)", text)
    if not m:
        return ""
    value = m.group(1)
    stop = re.search(r"(?m)^\s*(?:#{1,6}\s+|(?:[A-Z]\.)?\d+(?:\.\d+){1,}\s+)", value)
    if stop:
        value = value[: stop.start()]
    value = re.split(r"(?s)\n\s*\$\$", value, maxsplit=1)[0]
    value = re.sub(r"\n{2,}", "\n", value).strip()
    return _trim_context(value, 1200)


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
