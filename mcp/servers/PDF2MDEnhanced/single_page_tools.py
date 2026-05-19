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
DEFAULT_REVISE_PAGE_MARKDOWN_PROMPT = """请根据这张单页渲染图片，重新生成该页可审核的 Markdown 内容。
要求：
1. 以页面图片为准修正乱码、错字、漏字、错误换行和明显 OCR 错误。
2. 保留表格、公式、图示的可读结构；无法可靠结构化时保留占位说明，不要编造数据。
3. 保留 Markdown、LaTeX、placeholder 这类人读校对格式。
4. 删除页眉、页脚、页码、标准号页眉等重复版面元素；不要保留，也不要用注释输出。
5. 只输出修订后的页面 Markdown，不要输出解释、代码围栏或额外标题。"""


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
    table_rows_format: str = "structured_json",
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
        table_rows_format=table_rows_format,
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


def revise_page_markdown_direct(
    file_data: Optional[str] = None,
    file_path: Optional[str] = None,
    file_url: Optional[str] = None,
    content_type: str = "image/png",
    filename: Optional[str] = None,
    page_no: int = 1,
    prompt: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    output_target: str = "page_text",
    output_format: str = "markdown",
    vlm_config: Optional[Dict[str, Any]] = None,
    routing_config: Optional[Dict[str, Any]] = None,
) -> str:
    _ = content_type
    _ = filename
    _ = context
    _ = output_target
    final_prompt = str(prompt or "").strip() or DEFAULT_REVISE_PAGE_MARKDOWN_PROMPT
    with tempfile.TemporaryDirectory(prefix="pdf2md_enh_revise_page_") as work_dir:
        ctx = _prepare_context(
            Path(work_dir),
            file_path=file_path,
            file_data=file_data,
            file_url=file_url,
            page_no=page_no,
            input_type="auto",
            routing_config=routing_config,
        )
        warnings: List[str] = []
        vlm = DynamicVLMClient(_resolve_revise_vlm_config(vlm_config, routing_config))
        vlm_info = _vlm_debug_info(vlm)
        if not vlm.enabled:
            warnings.append("vlm_ocr_unavailable_for_page_revision")
            page_text = ""
        else:
            try:
                raw = vlm._call_image_prompt(ctx.image_path, final_prompt, max_tokens=vlm.max_tokens)
                page_text = _normalize_page_markdown(raw)
            except Exception as exc:
                warnings.append(f"vlm_ocr_failed: {exc}")
                page_text = ""

        result = {
            "pageText": page_text,
            "page_no": ctx.page_no,
            "output_format": output_format or "markdown",
            "warnings": _dedupe(warnings),
            "vlm": vlm_info,
        }
        return json.dumps(result, ensure_ascii=False)


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
    table_rows_format: str = "structured_json",
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
            items = _extract_tables(ctx, glm, vlm, describe, model_calls, warnings, table_rows_format=table_rows_format)
            return _base_result(tool, ctx, model_calls, warnings, items=items)
        if target == "formulas":
            return _extract_formula_page_result(ctx, glm, vlm, describe, model_calls, warnings)
        if target == "figures":
            return _extract_figure_page_result(ctx, vlm, model_calls, warnings)

        tables = _extract_tables(ctx, glm, vlm, describe, model_calls, warnings, allow_native=True, table_rows_format=table_rows_format)
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
    table_rows_format: str = "structured_json",
) -> List[Dict[str, Any]]:
    if allow_native and ctx.input_type == "pdf" and ctx.native_tables:
        return [_table_item("pymupdf", table, ctx.page_text, describe, table_rows_format=table_rows_format) for table in ctx.native_tables]

    if glm.enabled:
        try:
            model_calls["glm_ocr"] += 1
            result = glm.extract_page(ctx.image_path, prompt=_prompt_tables(ctx.page_text, describe))
            items = [
                _table_item("glm_ocr", item.markdown or item.text, ctx.page_text, describe, item, table_rows_format=table_rows_format)
                for item in result.tables
            ]
            if not items:
                recovered, source_text = _recover_table_from_result(result)
                if recovered:
                    items = [_table_item("glm_ocr", recovered, ctx.page_text, describe, table_rows_format=table_rows_format, source_text=source_text)]
            if items:
                _enrich_table_metadata_with_vlm(ctx, vlm, items, describe, model_calls, warnings)
                return items
            warnings.append("glm_ocr_returned_no_tables")
        except Exception as exc:
            warnings.append(f"glm_ocr_failed: {exc}")

    if vlm.enabled:
        try:
            model_calls["vlm_ocr"] += 1
            result = _call_vlm_structured(vlm, ctx.image_path, _prompt_tables(ctx.page_text, describe))
            items = [
                _table_item("vlm_ocr", item.markdown or item.text, ctx.page_text, describe, item, table_rows_format=table_rows_format)
                for item in result.tables
            ]
            if not items:
                recovered, source_text = _recover_table_from_result(result)
                if recovered:
                    items = [_table_item("vlm_ocr", recovered, ctx.page_text, describe, table_rows_format=table_rows_format, source_text=source_text)]
            if items:
                return items
            warnings.append("vlm_ocr_returned_no_tables")
        except Exception as exc:
            warnings.append(f"vlm_ocr_failed: {exc}")
    else:
        warnings.append("vlm_ocr_unavailable")
    return []


def _enrich_table_metadata_with_vlm(
    ctx: SinglePageContext,
    vlm: DynamicVLMClient,
    items: List[Dict[str, Any]],
    describe: bool,
    model_calls: Dict[str, int],
    warnings: List[str],
) -> None:
    if not items or not describe:
        return
    _fill_local_table_descriptions(items)
    if not _tables_need_vlm_metadata(items):
        return
    if not vlm.enabled:
        warnings.append("vlm_ocr_unavailable_for_table_metadata")
        return
    try:
        model_calls["vlm_ocr"] += 1
        raw = vlm._call_image_prompt(
            ctx.image_path,
            _prompt_table_metadata(items, ctx.page_text),
            max_tokens=min(vlm.max_tokens, 2048),
        )
        metadata = _parse_table_metadata_response(raw)
        if metadata:
            _merge_table_metadata(items, metadata)
        else:
            warnings.append("vlm_ocr_returned_no_table_metadata")
    except Exception as exc:
        warnings.append(f"vlm_ocr_table_metadata_failed: {exc}")


def _fill_local_table_descriptions(items: List[Dict[str, Any]]) -> None:
    for item in items:
        title = _cell_to_text(item.get("title"))
        if not title or not _is_reliable_table_title(title, item):
            continue
        columns = item.get("columns") if isinstance(item.get("columns"), list) else []
        headers = [_cell_to_text(col) for col in columns if _cell_to_text(col)]
        if headers:
            desc = f"{title}。字段包括：{', '.join(headers[:8])}。"
        else:
            desc = title
        item["description"] = desc
        item["semanticDesc"] = desc


def _tables_need_vlm_metadata(items: List[Dict[str, Any]]) -> bool:
    return any(not _is_reliable_table_title(_cell_to_text(item.get("title")), item) for item in items)


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


def _vlm_debug_info(vlm: DynamicVLMClient) -> Dict[str, Any]:
    return {
        "enabled": bool(getattr(vlm, "enabled", False)),
        "provider": getattr(vlm, "provider", "") or "",
        "model": getattr(vlm, "model", "") or "",
        "base_url": getattr(vlm, "base_url", "") or "",
        "max_tokens": getattr(vlm, "max_tokens", None),
        "timeout_sec": getattr(vlm, "timeout_sec", None),
        "has_api_key": bool(getattr(vlm, "api_key", "")),
    }


def _resolve_revise_vlm_config(
    vlm_config: Optional[Dict[str, Any]],
    routing_config: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if vlm_config:
        return vlm_config
    if not isinstance(routing_config, dict):
        return None

    direct = routing_config.get("vlm_ocr")
    if isinstance(direct, dict) and direct.get("enabled", True):
        return direct

    ocr_config = routing_config.get("ocr_config")
    if isinstance(ocr_config, dict):
        nested = ocr_config.get("vlm_ocr")
        if isinstance(nested, dict) and nested.get("enabled", True):
            return nested
    return None


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
    table_rows_format: str = "structured_json",
    source_text: str = "",
) -> Dict[str, Any]:
    raw_text = source_text or str(markdown or "").strip()
    normalized = _normalize_table_contract(raw_text, table_rows_format)
    if raw_item and isinstance(raw_item.raw, dict):
        normalized = _merge_model_normalized_table(normalized, raw_item.raw)
    table_md = normalized["markdown"]
    title = (
        (raw_item.title if raw_item else "")
        or _table_title_from_raw(raw_item.raw if raw_item else None)
        or _find_table_title(page_text)
        or _table_title_from_markdown(table_md)
    )
    desc = (raw_item.description if raw_item else "") if describe else ""
    if describe and not desc:
        desc = _describe_table(title, table_md, page_text)
    item = {
        "source": source,
        "title": title,
        "markdown": table_md,
        "description": desc,
        "semanticDesc": desc,
        "tableRowsFormat": normalized["tableRowsFormat"],
        "tableRowsContent": normalized["tableRowsContent"],
        "orientation": normalized["orientation"],
        "columns": normalized["columns"],
        "normalized_rows": normalized["normalized_rows"],
        "source_cells": normalized["source_cells"],
        "cell_status": normalized["cell_status"],
        "raw_html": normalized["raw_html"],
        "warnings": normalized["warnings"],
        "degraded": normalized["degraded"],
        "manualReviewRequired": normalized["manualReviewRequired"],
        "context": (raw_item.context if raw_item else "") or _near_context(page_text, title),
    }
    if normalized["reason"]:
        item["reason"] = normalized["reason"]
    if normalized["sourceHtml"]:
        item["sourceHtml"] = normalized["sourceHtml"]
    if normalized["rawText"]:
        item["rawText"] = normalized["rawText"]
    return item


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
    desc = str(item.description or item.text or item.caption or item.title or "").strip()
    caption = item.caption or item.title or _figure_caption(desc) or _figure_caption(page_text)
    labels = item.raw.get("labels", []) if isinstance(item.raw, dict) else []
    if not isinstance(labels, list):
        labels = []
    labels = [str(x).strip() for x in labels if str(x).strip()] or _figure_labels(desc)
    return {
        "source": "vlm_ocr",
        "caption": caption,
        "capture": caption,
        "name": caption,
        "figureName": caption,
        "type": str(item.raw.get("type") or _figure_type(desc)) if isinstance(item.raw, dict) else _figure_type(desc),
        "description": desc,
        "semanticDesc": desc,
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
                "capture": _figure_caption(content) or f"Figure {len(figures) + 1}",
                "name": _figure_caption(content) or f"Figure {len(figures) + 1}",
                "figureName": _figure_caption(content) or f"Figure {len(figures) + 1}",
                "type": "figure",
                "description": content,
                "semanticDesc": content,
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
                "capture": detail.get("capture") or detail.get("caption") or enriched.get("capture") or enriched.get("caption"),
                "name": detail.get("name") or detail.get("caption") or enriched.get("name") or enriched.get("caption"),
                "figureName": detail.get("figureName") or detail.get("caption") or enriched.get("figureName") or enriched.get("caption"),
                "type": detail.get("type") or enriched.get("type"),
                "description": detail.get("description") or enriched.get("description"),
                "semanticDesc": detail.get("semanticDesc") or detail.get("description") or enriched.get("semanticDesc") or enriched.get("description"),
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
    result = {
        "tool": tool,
        "source": _source_payload(ctx),
        "items": items,
        "model_calls": model_calls,
        "warnings": _dedupe(warnings),
    }
    if tool == "extract_page_tables":
        result["tables"] = items
        if items:
            _promote_first_table_fields(result, items[0])
    return result


def _promote_first_table_fields(result: Dict[str, Any], item: Dict[str, Any]) -> None:
    for key in [
        "columns",
        "normalized_rows",
        "source_cells",
        "cell_status",
        "orientation",
        "raw_html",
        "sourceHtml",
        "markdown",
        "tableRowsFormat",
        "tableRowsContent",
        "degraded",
        "manualReviewRequired",
        "reason",
    ]:
        if key in item:
            result[key] = item[key]
    result["rows"] = item.get("normalized_rows") or []
    result["warnings"] = _dedupe([*result.get("warnings", []), *item.get("warnings", [])])


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
        title = item.get("caption") or item.get("capture") or item.get("name") or item.get("figureName") or f"Figure {idx}"
        labels = item.get("labels") or []
        desc = item.get("description") or ""
        zh = _contains_cjk(" ".join([str(title), str(desc), str(item.get("context") or "")]))
        type_label = "类型" if zh else "Type"
        labels_label = "标注" if zh else "Labels"
        label_line = f"{labels_label}: {', '.join(labels)}" if labels else ""
        out.append(
            f"## {title}\n\n{type_label}: {item.get('type') or 'unknown'}\n\n{desc}\n\n{label_line}".strip()
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
        "请按表格网格线逐行逐列读取，不能按文本连续顺序重排。目标是可查询的标准矩阵，不是视觉 Markdown。\n"
        "规则：\n"
        "1. 识别表名。\n"
        "2. 检测页面/表格方向，orientation 只能是 0/90/180/270；横置或倒置时按旋正后的逻辑顺序抽取。\n"
        "3. 识别行、列、单元格边界、rowspan、colspan；source_cells 必须包含 row/col/text/rowspan/colspan/confidence。\n"
        "4. 输出 normalized_rows：每行列数必须一致；rowspan 覆盖区域必须向下填充原单元格文本，不能写成 n/a。\n"
        "5. colspan 按逻辑列展开；无法可靠拆分时仍保留矩阵并设置 degraded/manualReviewRequired/warnings。\n"
        "6. 区分空白来源：merged_fill、blank_in_source、unreadable、recognized，并在 cell_status 返回。\n"
        "7. 禁止因为空白或合并单元格导致后续数值左移；禁止额外产生尾部 n/a 伪列。\n"
        "8. 单元格数字必须按图中原样抄录，不要根据相邻数字推断或修正；看不清的单元格标记 unreadable。\n"
        "9. 可以额外返回 markdown/raw_html，但必须返回 normalized JSON。\n"
        "JSON schema："
        "{\"table_title\":\"\",\"orientation\":0,\"columns\":[],\"normalized_rows\":[[]],"
        "\"source_cells\":[{\"row\":0,\"col\":0,\"text\":\"\",\"rowspan\":1,\"colspan\":1,\"confidence\":1.0}],"
        "\"cell_status\":[{\"row\":0,\"col\":0,\"status\":\"recognized\"}],"
        "\"raw_html\":\"\",\"markdown\":\"\",\"degraded\":false,\"manualReviewRequired\":false,\"warnings\":[]}。\n"
        f"是否需要语义描述：{bool(describe)}。\n"
        f"可用的文本层上下文：\n{_trim_context(page_text)}"
    )


def _prompt_table_metadata(items: List[Dict[str, Any]], page_text: str) -> str:
    summaries = []
    for idx, item in enumerate(items):
        columns = item.get("columns") if isinstance(item.get("columns"), list) else []
        rows = item.get("normalized_rows") if isinstance(item.get("normalized_rows"), list) else []
        summaries.append(
            {
                "index": idx,
                "existing_title": str(item.get("title") or "")[:120],
                "columns": [str(col) for col in columns[:12]],
                "sample_rows": rows[:3],
                "markdown_preview": str(item.get("markdown") or "")[:600],
                "context": str(item.get("context") or "")[:240],
            }
        )
    return (
        "请根据这张页面图片，为已抽取的表格补全表名和语义描述，只输出严格 JSON。\n"
        "不要重新抽取或改写表格数据；不要输出 Markdown、代码围栏或解释。\n"
        "表名必须来自图片中可见的表题/表注原文，例如“表 7-35 ...”；看不到可靠表名时返回空字符串。\n"
        "semanticDesc 用图片/表题同语种简要说明该表含义，不要编造数据。\n"
        "返回 schema：{\"tables\":[{\"index\":0,\"title\":\"\",\"semanticDesc\":\"\"}]}。\n"
        f"已抽取表格摘要：\n{json.dumps(summaries, ensure_ascii=False)}\n"
        f"可用页面文本上下文（可能含 OCR 噪声，仅供定位，不要当正文）：\n{_trim_context(page_text)}"
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
        "只识别这张单页图片中的插图、示意图、结构图、曲线图或技术图，忽略表格和公式。"
        "请描述图像语义、可见标注、图题/图注和图类型。必须严格返回 JSON，不要输出解释："
        "{\"figures\":[{\"caption\":\"\",\"capture\":\"\",\"name\":\"\",\"figureName\":\"\","
        "\"type\":\"schematic|chart|diagram|figure|unknown\",\"description\":\"\",\"semanticDesc\":\"\","
        "\"labels\":[],\"context\":\"\"}],\"tables\":[],\"formulas\":[]}。\n"
        "字段要求：caption/capture/name/figureName 都表示图名/图题；有可见图题/图注时必须抄录原文并填入这些字段。"
        "description/semanticDesc 都表示图的语义描述。"
        "语种要求：图名必须抄录图片中可见图题/图注的原文；description/semanticDesc 和 context "
        "必须优先使用图题/图注的语种，其次使用正文/图片中文字的主要语种；中文页面请用中文描述，不要翻译成英文。"
        "未见图题时图名字段都留空，不要编造图名。\n"
        f"可用的文本层上下文：\n{_trim_context(page_text)}"
    )


def _prompt_figure_page(page_text: str) -> str:
    return (
        "识别这张单页图片中的含插图页面内容，只关注正文、图题、图注、插图位置和插图语义描述。"
        "忽略表格和公式的结构化抽取。请按页面自然阅读顺序输出严格 JSON："
        "{\"markdown\":\"整页Markdown，保留正文顺序，并在插图位置写图题和图描述\","
        "\"figures\":[{\"caption\":\"\",\"capture\":\"\",\"name\":\"\",\"figureName\":\"\","
        "\"type\":\"schematic|chart|diagram|figure|unknown\",\"description\":\"\",\"semanticDesc\":\"\","
        "\"labels\":[],\"context\":\"\"}],\"tables\":[],\"formulas\":[]}。"
        "Markdown 中的每个插图应包含图题和简洁但具体的图像描述。"
        "字段要求：caption/capture/name/figureName 都表示图名/图题；有可见图题/图注时必须抄录原文并填入这些字段。"
        "description/semanticDesc 都表示图的语义描述。"
        "语种要求：图名必须抄录图片中可见图题/图注的原文；Markdown、description/semanticDesc 和 context "
        "必须优先使用图题/图注的语种，其次使用正文/图片中文字的主要语种；中文页面请用中文描述，不要翻译成英文。"
        "未见图题时图名字段都留空，不要编造图名。"
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
        "\"capture\":\"\",\"name\":\"\",\"figureName\":\"\",\"type\":\"schematic|chart|diagram|figure|unknown\","
        "\"description\":\"\",\"semanticDesc\":\"\","
        "\"labels\":[],\"context\":\"\"}],\"tables\":[],\"formulas\":[]}。\n"
        "要求：每个输入 image block 最多返回一个对应 figure；block_index 和 bbox 必须原样保留；"
        "description 要说明图中表达的对象、结构关系、关键标注和可读文字。"
        "字段要求：caption/capture/name/figureName 都表示图名/图题；有可见图题/图注时必须抄录原文并填入这些字段。"
        "description/semanticDesc 都表示图的语义描述。"
        "语种要求：图名必须抄录图片中可见图题/图注的原文；description/semanticDesc 和 context "
        "必须优先使用图题/图注的语种，其次使用正文/图片中文字的主要语种；中文页面请用中文描述，不要翻译成英文。"
        "未见图题时图名字段都留空，不要编造图名。\n"
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


def _recover_table_from_result(result: OcrResult) -> tuple[str, str]:
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
        source_text = str(candidate or "")
        recovered = _recover_table_markdown(source_text)
        if recovered:
            return recovered, source_text
    return "", ""


def _normalize_table_output(table_md: str) -> str:
    return _normalize_table_contract(table_md, "markdown")["markdown"]


def _normalize_table_contract(table_text: str, table_rows_format: str = "markdown") -> Dict[str, Any]:
    raw_text = str(table_text or "").strip()
    source_html = _extract_html_table(raw_text)
    warnings: List[str] = []
    degraded = False
    manual_review = False
    reason = ""

    if source_html:
        grid, meta = _html_table_to_grid(source_html)
        markdown = _grid_to_markdown(grid) if grid else ""
        warnings.extend(meta["warnings"])
        degraded = bool(meta["degraded"])
        manual_review = bool(meta["manualReviewRequired"])
        reason = str(meta["reason"] or "")
    else:
        markdown = _recover_table_markdown(raw_text) or raw_text
        grid, meta = _markdown_table_to_grid_and_meta(markdown)
        warnings.extend(meta["warnings"])
        degraded = bool(meta["degraded"])
        manual_review = bool(meta["manualReviewRequired"])
        reason = str(meta["reason"] or "")

    if not markdown:
        markdown = raw_text
    fmt = _normalize_table_rows_format(table_rows_format)
    table_rows_content: Any
    if fmt == "markdown":
        table_rows_content = markdown
    elif fmt == "csv":
        table_rows_content = _grid_to_delimited(grid or _markdown_table_to_grid(markdown), ",")
    elif fmt == "tsv":
        table_rows_content = _grid_to_delimited(grid or _markdown_table_to_grid(markdown), "\t")
    else:
        table_rows_content = _structured_table_payload_json(
            _structured_table_payload(grid, meta, source_html, markdown, degraded, manual_review, warnings, reason)
        )

    if isinstance(table_rows_content, str) and "<table" in table_rows_content.lower():
        warnings.append("html_removed_from_tableRowsContent")
        table_rows_content = markdown if fmt == "markdown" else ""
        degraded = True
        manual_review = True
        reason = reason or "normalized output would contain html"

    return {
        "markdown": markdown,
        "tableRowsFormat": fmt,
        "tableRowsContent": table_rows_content,
        "orientation": meta.get("orientation", 0),
        "columns": meta.get("columns", grid[0] if grid else []),
        "normalized_rows": meta.get("normalized_rows", grid[1:] if len(grid) > 1 else []),
        "source_cells": meta.get("source_cells", []),
        "cell_status": meta.get("cell_status", []),
        "raw_html": source_html,
        "sourceHtml": source_html,
        "rawText": raw_text if raw_text and raw_text != source_html else "",
        "warnings": _dedupe(warnings),
        "degraded": degraded,
        "manualReviewRequired": manual_review,
        "reason": reason,
    }


def _merge_model_normalized_table(normalized: Dict[str, Any], raw: Dict[str, Any]) -> Dict[str, Any]:
    columns = raw.get("columns")
    rows = raw.get("normalized_rows") or raw.get("rows")
    if not isinstance(columns, list) or not isinstance(rows, list):
        return normalized
    norm_columns = [_cell_to_text(cell) for cell in columns]
    norm_rows = [
        [_cell_to_text(cell) for cell in row]
        for row in rows
        if isinstance(row, list)
    ]
    if not norm_columns or not norm_rows:
        return normalized

    column_width = len(norm_columns)
    inconsistent_row_width = any(len(row) > column_width for row in norm_rows)
    for row in norm_rows:
        if len(row) < column_width:
            row.extend([""] * (column_width - len(row)))

    grid = [norm_columns, *norm_rows]
    raw_markdown = _cell_to_text(raw.get("markdown"))
    raw_html = _cell_to_text(raw.get("raw_html")) or _cell_to_text(normalized.get("raw_html"))
    html_leak = bool(_contains_html_table(raw_markdown))
    markdown = (normalized.get("markdown") if html_leak else raw_markdown) or _grid_to_markdown(grid)
    if html_leak and not raw_html:
        raw_html = raw_markdown
    warnings = _dedupe([*normalized.get("warnings", []), *[str(w) for w in raw.get("warnings", []) if str(w).strip()]])
    warnings = _model_orientation_warnings(raw, warnings)
    if inconsistent_row_width:
        warnings.append("inconsistent_row_width")
    if html_leak:
        warnings.append("html_removed_from_tableRowsContent")
    degraded = bool(raw.get("degraded", normalized.get("degraded", False)))
    manual_review = bool(raw.get("manualReviewRequired", normalized.get("manualReviewRequired", False)))
    if inconsistent_row_width or html_leak:
        degraded = True
        manual_review = True
    reason = str(raw.get("reason") or normalized.get("reason") or "")
    if inconsistent_row_width and "inconsistent_row_width" not in reason:
        reason = _join_reasons(reason, "inconsistent_row_width: row data is wider than columns")
    if html_leak:
        reason = _join_reasons(reason, "normalized output would contain html")
    source_cells = raw.get("source_cells") if isinstance(raw.get("source_cells"), list) else normalized.get("source_cells", [])
    cell_status = raw.get("cell_status") if isinstance(raw.get("cell_status"), list) else normalized.get("cell_status", [])
    structured_content = _structured_table_payload_json(
        _structured_table_payload(
            grid,
            {
                "orientation": raw.get("orientation", normalized.get("orientation", 0)),
                "columns": norm_columns,
                "normalized_rows": norm_rows,
                "source_cells": source_cells,
                "cell_status": cell_status,
            },
            raw_html,
            markdown,
            degraded,
            manual_review,
            _dedupe(_model_orientation_warnings(raw, warnings)),
            reason,
        )
    )
    if html_leak:
        structured_content = ""

    merged = dict(normalized)
    merged.update(
        {
            "markdown": markdown,
            "tableRowsContent": structured_content
            if normalized.get("tableRowsFormat") == "structured_json"
            else normalized.get("tableRowsContent"),
            "orientation": raw.get("orientation", normalized.get("orientation", 0)),
            "columns": norm_columns,
            "normalized_rows": norm_rows,
            "source_cells": source_cells,
            "cell_status": cell_status,
            "raw_html": raw_html,
            "sourceHtml": raw_html,
            "warnings": _dedupe(warnings),
            "degraded": degraded,
            "manualReviewRequired": manual_review,
            "reason": reason,
        }
    )
    if normalized.get("tableRowsFormat") == "markdown":
        merged["tableRowsContent"] = markdown
    elif normalized.get("tableRowsFormat") == "csv":
        merged["tableRowsContent"] = _grid_to_delimited(grid, ",")
    elif normalized.get("tableRowsFormat") == "tsv":
        merged["tableRowsContent"] = _grid_to_delimited(grid, "\t")
    if html_leak and normalized.get("tableRowsFormat") in {"csv", "tsv"}:
        merged["tableRowsContent"] = ""
    return merged


def _model_orientation_warnings(raw: Dict[str, Any], warnings: List[str]) -> List[str]:
    if raw.get("orientation") in {0, 90, 180, 270, "0", "90", "180", "270"}:
        return [warning for warning in warnings if warning != "orientation_defaulted_to_0"]
    return warnings


def _parse_table_metadata_response(text: str) -> List[Dict[str, Any]]:
    payload = _extract_json_payload(text)
    if not isinstance(payload, dict):
        return []
    value = payload.get("tables") or payload.get("items") or payload.get("table_metadata")
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _extract_json_payload(text: str) -> Any:
    raw = str(text or "").strip()
    if not raw:
        return None
    raw = re.sub(r"(?m)^\s*```(?:json)?\s*$", "", raw)
    raw = re.sub(r"(?m)^\s*```\s*$", "", raw).strip()
    try:
        return json.loads(raw)
    except Exception:
        pass
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:
        return None


def _merge_table_metadata(items: List[Dict[str, Any]], metadata: List[Dict[str, Any]]) -> None:
    for entry in metadata:
        idx = _metadata_index(entry)
        if idx is None or idx < 0 or idx >= len(items):
            continue
        item = items[idx]
        title = _cell_to_text(
            entry.get("title")
            or entry.get("table_title")
            or entry.get("tableName")
            or entry.get("table_name")
            or entry.get("表名")
        )
        desc = _cell_to_text(entry.get("semanticDesc") or entry.get("description") or entry.get("summary"))
        if title and _should_replace_table_title(item):
            item["title"] = title[:120]
        if desc:
            item["description"] = desc
            item["semanticDesc"] = desc


def _metadata_index(entry: Dict[str, Any]) -> Optional[int]:
    value = entry.get("index")
    if value is None:
        value = entry.get("table_index")
    try:
        return int(value)
    except Exception:
        return None


def _should_replace_table_title(item: Dict[str, Any]) -> bool:
    existing = _cell_to_text(item.get("title"))
    if not existing:
        return True
    inferred = _table_title_from_markdown(str(item.get("markdown") or ""))
    return bool(inferred and existing == inferred)


def _is_reliable_table_title(title: str, item: Dict[str, Any]) -> bool:
    value = _cell_to_text(title)
    if not value:
        return False
    inferred = _table_title_from_markdown(str(item.get("markdown") or ""))
    if inferred and value == inferred:
        return False
    return bool(re.match(r"^(表|Table)\s*[\dA-Za-z一二三四五六七八九十附录.-]*", value, flags=re.IGNORECASE))


def _cell_to_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _contains_html_table(value: str) -> bool:
    return "<table" in str(value or "").lower()


def _join_reasons(existing: str, addition: str) -> str:
    existing = str(existing or "").strip()
    addition = str(addition or "").strip()
    if not existing:
        return addition
    if not addition or addition in existing:
        return existing
    return f"{existing}; {addition}"


def _normalize_table_rows_format(value: str) -> str:
    fmt = str(value or "markdown").strip().lower()
    if fmt in {"markdown", "csv", "tsv", "structured_json"}:
        return fmt
    return "markdown"


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
    grid, _meta = _html_table_to_grid(text)
    return _grid_to_markdown(grid)


def _extract_html_table(text: str) -> str:
    if "<table" not in str(text or "").lower():
        return ""
    match = re.search(r"(?is)<table\b[^>]*>.*?</table>", str(text or ""))
    return match.group(0) if match else str(text or "")


def _html_table_to_grid(text: str) -> tuple[List[List[str]], Dict[str, Any]]:
    table = _extract_html_table(text)
    if not table:
        return [], {"warnings": [], "degraded": False, "manualReviewRequired": False, "reason": ""}
    html_rows = [row_match.group(1) for row_match in re.finditer(r"(?is)<tr\b[^>]*>(.*?)</tr>", table)]
    grid: List[List[Optional[str]]] = [[] for _ in html_rows]
    cell_status: List[Dict[str, Any]] = []
    source_cells: List[Dict[str, Any]] = []
    has_spans = False
    has_colspan = False
    clipped_rowspan = False
    for row_index, row_html in enumerate(html_rows):
        row = grid[row_index]
        col_index = 0
        for cell_match in re.finditer(r"(?is)<(td|th)\b([^>]*)>(.*?)</\1>", row_html):
            while col_index < len(row) and row[col_index] is not None:
                col_index += 1
            attrs = cell_match.group(2)
            cell_text, source_status = _clean_html_cell_with_status(cell_match.group(3))
            rowspan = max(1, _html_int_attr(attrs, "rowspan"))
            colspan = max(1, _html_int_attr(attrs, "colspan"))
            if rowspan > 1 or colspan > 1:
                has_spans = True
            if colspan > 1:
                has_colspan = True
            if row_index + rowspan > len(html_rows):
                clipped_rowspan = True
            source_cells.append(
                {
                    "row": row_index,
                    "col": col_index,
                    "text": cell_text,
                    "rowspan": rowspan,
                    "colspan": colspan,
                    "confidence": 1.0,
                }
            )
            for r in range(min(rowspan, len(html_rows) - row_index)):
                target = grid[row_index + r]
                _ensure_optional_row_width(target, col_index + colspan)
                for c in range(colspan):
                    target[col_index + c] = cell_text
                    status = source_status if r == 0 and c == 0 else "merged_fill"
                    entry: Dict[str, Any] = {"row": row_index + r, "col": col_index + c, "status": status}
                    if status == "merged_fill":
                        entry["source_row"] = row_index
                        entry["source_col"] = col_index
                    cell_status.append(entry)
            col_index += colspan
    normalized = [
        [cell if cell is not None else "" for cell in row]
        for row in grid
        if any(_cell_to_text(cell) for cell in row)
    ]
    if not normalized:
        return [], {"warnings": ["html_table_parse_empty"], "degraded": True, "manualReviewRequired": True, "reason": "html table could not be parsed into rows"}
    width = max(len(row) for row in normalized)
    for row_idx, row in enumerate(normalized):
        old_width = len(row)
        _ensure_row_width(row, width)
        for col_idx in range(old_width, width):
            cell_status.append({"row": row_idx, "col": col_idx, "status": "blank_in_source"})
    warnings: List[str] = []
    reason = ""
    if has_spans:
        warnings.append("html_table_contains_rowspan_or_colspan")
    if has_colspan:
        warnings.append("complex_header")
    if clipped_rowspan:
        warnings.append("rowspan_exceeds_observed_rows")
    if has_colspan:
        reason = "colspan expanded into logical columns; verify complex headers"
    elif clipped_rowspan:
        reason = "rowspan exceeded observed table rows and was clipped to avoid pseudo rows"
    orientation, orientation_reliable = _table_orientation_status(table)
    if not orientation_reliable:
        warnings.append("orientation_defaulted_to_0")
    return normalized, {
        "warnings": warnings,
        "degraded": has_colspan or clipped_rowspan,
        "manualReviewRequired": has_colspan or clipped_rowspan,
        "reason": reason,
        "orientation": orientation,
        "columns": normalized[0] if normalized else [],
        "normalized_rows": normalized[1:] if len(normalized) > 1 else [],
        "source_cells": source_cells,
        "cell_status": _dedupe_cell_status(cell_status),
    }


def _grid_to_markdown(grid: List[List[str]]) -> str:
    if not grid:
        return ""
    width = max(len(row) for row in grid)
    normalized = [list(row) for row in grid]
    for row in normalized:
        _ensure_row_width(row, width)
    lines = [
        "| " + " | ".join(_escape_markdown_cell(cell) for cell in normalized[0]) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    lines.extend("| " + " | ".join(_escape_markdown_cell(cell) for cell in row) + " |" for row in normalized[1:])
    return "\n".join(lines).strip()


def _markdown_table_to_grid(markdown: str) -> List[List[str]]:
    return _markdown_table_to_grid_and_meta(markdown)[0]


def _markdown_table_to_grid_and_meta(markdown: str) -> tuple[List[List[str]], Dict[str, Any]]:
    lines = [line.strip() for line in str(markdown or "").splitlines() if "|" in line]
    rows: List[List[str]] = []
    for line in lines:
        cells = [cell.strip().replace("\\|", "|") for cell in line.strip().strip("|").split("|")]
        if cells and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        rows.append(cells)
    if not rows:
        return [], _grid_table_meta([])
    width = max(len(row) for row in rows)
    if width <= 1:
        return rows, _grid_table_meta(rows)
    repaired, repair_meta = _repair_markdown_merged_rows(rows, width)
    meta = _grid_table_meta(repaired)
    warnings = _dedupe([*meta.get("warnings", []), *repair_meta.get("warnings", [])])
    meta.update(
        {
            "columns": repaired[0] if repaired else [],
            "normalized_rows": repaired[1:] if len(repaired) > 1 else [],
            "source_cells": repair_meta.get("source_cells") or meta.get("source_cells", []),
            "cell_status": repair_meta.get("cell_status") or meta.get("cell_status", []),
            "warnings": warnings,
            "degraded": bool(repair_meta.get("degraded", False)),
            "manualReviewRequired": bool(repair_meta.get("manualReviewRequired", False)),
            "reason": str(repair_meta.get("reason") or ""),
        }
    )
    return repaired, meta


def _repair_markdown_merged_rows(rows: List[List[str]], width: int) -> tuple[List[List[str]], Dict[str, Any]]:
    normalized: List[List[str]] = []
    source_cells: List[Dict[str, Any]] = []
    cell_status: List[Dict[str, Any]] = []
    warnings: List[str] = []
    degraded = False
    manual_review = False
    reason = ""
    profiles = _build_column_profiles(rows, width)
    previous_complete_row: Optional[List[str]] = None
    previous_complete_idx: Optional[int] = None

    for row_idx, original in enumerate(rows):
        row = list(original)
        if len(row) >= width:
            normalized_row = row[:width]
            if len(row) > width:
                degraded = True
                manual_review = True
                warnings.append("inconsistent_row_width")
                reason = _join_reasons(reason, "inconsistent_row_width: markdown row is wider than header")
            normalized.append(normalized_row)
            _record_markdown_cells(row_idx, normalized_row, source_cells, cell_status)
            if row_idx > 0 and len(row) == width:
                previous_complete_row = normalized_row
                previous_complete_idx = row_idx
            continue

        missing_count = width - len(row)
        if row_idx == 0 or not previous_complete_row or previous_complete_idx is None:
            normalized_row = row + [""] * missing_count
            normalized.append(normalized_row)
            _record_markdown_cells(row_idx, normalized_row, source_cells, cell_status, original_width=len(row))
            degraded = True
            manual_review = True
            warnings.append("ambiguous_markdown_merged_cell_repair")
            reason = _join_reasons(reason, "cannot reliably infer missing markdown table columns")
            continue

        candidates = _markdown_alignment_candidates(row, width, previous_complete_row, previous_complete_idx, row_idx, profiles)
        ranked = sorted(candidates, key=lambda item: item["score"], reverse=True)
        best = ranked[0] if ranked else None
        second_score = ranked[1]["score"] if len(ranked) > 1 else -999.0
        if best and best["score"] >= 1.0 and best["score"] - second_score >= 2.0:
            normalized_row = best["row"]
            normalized.append(normalized_row)
            source_cells.extend(best["source_cells"])
            cell_status.extend(best["cell_status"])
            warnings.append("markdown_merged_cell_repaired")
        else:
            normalized_row = row + [""] * missing_count
            normalized.append(normalized_row)
            _record_markdown_cells(row_idx, normalized_row, source_cells, cell_status, original_width=len(row))
            degraded = True
            manual_review = True
            warnings.append("ambiguous_markdown_merged_cell_repair")
            reason = _join_reasons(reason, "cannot reliably infer missing markdown table columns")

    return normalized, {
        "source_cells": source_cells,
        "cell_status": _dedupe_cell_status(cell_status),
        "warnings": _dedupe(warnings),
        "degraded": degraded,
        "manualReviewRequired": manual_review,
        "reason": reason,
    }


def _record_markdown_cells(
    row_idx: int,
    row: List[str],
    source_cells: List[Dict[str, Any]],
    cell_status: List[Dict[str, Any]],
    original_width: Optional[int] = None,
) -> None:
    original_width = len(row) if original_width is None else original_width
    for col_idx, value in enumerate(row):
        text = _cell_to_text(value)
        status = _cell_status_from_text(text) if col_idx < original_width else "blank_in_source"
        cell_status.append({"row": row_idx, "col": col_idx, "status": status})
        if col_idx < original_width:
            source_cells.append(
                {
                    "row": row_idx,
                    "col": col_idx,
                    "text": "" if status == "blank_in_source" else text,
                    "rowspan": 1,
                    "colspan": 1,
                    "confidence": 1.0,
                }
            )


def _markdown_alignment_candidates(
    row: List[str],
    width: int,
    previous_row: List[str],
    previous_row_idx: int,
    row_idx: int,
    profiles: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    missing = width - len(row)
    candidates: List[Dict[str, Any]] = []
    missing_sets: List[set[int]] = []
    for left_missing in range(missing + 1):
        right_missing = missing - left_missing
        missing_cols = set(range(left_missing)) | set(range(width - right_missing, width))
        if len(missing_cols) == missing:
            missing_sets.append(missing_cols)
    unique_sets: List[set[int]] = []
    seen = set()
    for item in missing_sets:
        key = tuple(sorted(item))
        if key not in seen:
            seen.add(key)
            unique_sets.append(item)

    for missing_cols in unique_sets:
        values: List[str] = []
        source_cells: List[Dict[str, Any]] = []
        cell_status: List[Dict[str, Any]] = []
        src_idx = 0
        score = 0.0
        for col_idx in range(width):
            if col_idx in missing_cols:
                inherited = previous_row[col_idx] if col_idx < len(previous_row) else ""
                values.append(inherited)
                cell_status.append(
                    {
                        "row": row_idx,
                        "col": col_idx,
                        "status": "merged_fill",
                        "source_row": previous_row_idx,
                        "source_col": col_idx,
                    }
                )
                if inherited:
                    score += 0.35
                continue
            value = row[src_idx] if src_idx < len(row) else ""
            values.append(value)
            cell_score = _score_cell_for_column(value, profiles[col_idx] if col_idx < len(profiles) else {})
            score += cell_score
            status = _cell_status_from_text(value)
            cell_status.append({"row": row_idx, "col": col_idx, "status": status})
            source_cells.append(
                {
                    "row": row_idx,
                    "col": col_idx,
                    "text": "" if status == "blank_in_source" else _cell_to_text(value),
                    "rowspan": 1,
                    "colspan": 1,
                    "confidence": 1.0,
                }
            )
            src_idx += 1
        candidates.append({"row": values, "score": score, "source_cells": source_cells, "cell_status": cell_status})
    return candidates


def _build_column_profiles(rows: List[List[str]], width: int) -> List[Dict[str, Any]]:
    headers = rows[0] if rows else []
    complete_rows = [row for row in rows[1:] if len(row) == width]
    profiles: List[Dict[str, Any]] = []
    for col_idx in range(width):
        header = headers[col_idx] if col_idx < len(headers) else ""
        categories = [_classify_table_cell(header, header=True)]
        for row in complete_rows:
            categories.append(_classify_table_cell(row[col_idx] if col_idx < len(row) else ""))
        counts: Dict[str, int] = {}
        for category in categories:
            if category and category != "blank":
                counts[category] = counts.get(category, 0) + 1
        profiles.append({"header": header, "counts": counts})
    return profiles


def _classify_table_cell(value: Any, header: bool = False) -> str:
    text = _cell_to_text(value)
    compact = text.replace(" ", "")
    lower = compact.lower()
    if not compact:
        return "blank"
    if _is_unreadable_marker(compact):
        return "unreadable"
    if "%" in compact or "％" in compact:
        return "percent"
    if "℃" in compact or "温度" in compact:
        return "temperature"
    if header:
        if re.search(r"材料|型号|类别|等级|代号|名称", compact):
            return "material"
        if re.search(r"状态|条件|处理|工艺|方式", compact):
            return "status"
        if re.search(r"直径|尺寸|厚度|长度|宽度|mm|公称|范围", lower):
            return "range"
        if re.search(r"系数|比值|比例", compact):
            return "ratio"
        if re.search(r"mpa|能量|强度|压力|数值|质量|重量|硬度|伸长|冲击", lower):
            return "numeric"
    if re.search(r"[~～]", compact) or re.fullmatch(r"[A-Za-z]*\d+(?:[~～\-][A-Za-z]*\d+)+", compact):
        return "range"
    if (
        re.fullmatch(r"[≤≥<>]?\s*M?\d+(?:[.,]\d+)?(?:\s*[~～\-]\s*M?\d+(?:[.,]\d+)?)?", compact, flags=re.IGNORECASE)
        and (re.search(r"[≤≥<>M]", compact, flags=re.IGNORECASE) or re.search(r"[~～\-]", compact))
    ):
        return "range"
    if re.fullmatch(r"[<>≤≥=]*\s*-?\d+(?:[.,]\d+)?", compact):
        numeric = _parse_float(compact)
        if numeric is not None and 0 <= numeric <= 1 and re.search(r"[.,]", compact):
            return "ratio"
        if re.fullmatch(r"[<>≤≥=]*\s*-?\d+", compact):
            return "integer"
        return "decimal"
    if re.search(r"\d", compact) and re.search(r"[A-Za-z]", compact):
        return "model"
    if re.search(r"正火|退火|淬火|回火|热轧|冷轧|调质|固溶|时效|处理|状态|条件", compact):
        return "status"
    if re.search(r"钢|铁|铜|铝|合金|材料|级", compact):
        return "material"
    return "text"


def _score_cell_for_column(value: Any, profile: Dict[str, Any]) -> float:
    category = _classify_table_cell(value)
    counts = profile.get("counts") if isinstance(profile, dict) else {}
    if not isinstance(counts, dict):
        counts = {}
    if category == "blank":
        return -0.5
    if category == "unreadable":
        return 0.0
    score = 0.0
    if counts.get(category):
        score += 3.0 + min(2.0, float(counts.get(category, 0)) * 0.4)
    if category in {"numeric", "integer", "decimal", "ratio", "range"} and any(
        counts.get(name) for name in ["numeric", "integer", "decimal", "ratio", "range"]
    ):
        score += 1.5
    if category == "ratio" and (counts.get("integer") or counts.get("temperature")):
        score -= 1.0
    if category == "integer" and counts.get("ratio"):
        score -= 1.5
    if category == "decimal" and counts.get("ratio"):
        score -= 0.75
    if category in {"material", "model", "text"} and (counts.get("material") or counts.get("model")):
        score += 1.0
    if category == "status" and counts.get("status"):
        score += 1.0
    if not score and counts:
        score -= 1.0
    return score


def _parse_float(value: str) -> Optional[float]:
    cleaned = re.sub(r"^[<>≤≥=]+", "", str(value or "").strip()).replace(",", ".")
    try:
        return float(cleaned)
    except Exception:
        return None


def _grid_table_meta(grid: List[List[str]]) -> Dict[str, Any]:
    cell_status: List[Dict[str, Any]] = []
    source_cells: List[Dict[str, Any]] = []
    for row_idx, row in enumerate(grid):
        for col_idx, value in enumerate(row):
            text = _cell_to_text(value)
            status = _cell_status_from_text(text)
            cell_status.append({"row": row_idx, "col": col_idx, "status": status})
            source_cells.append(
                {
                    "row": row_idx,
                    "col": col_idx,
                    "text": "" if status == "blank_in_source" else text,
                    "rowspan": 1,
                    "colspan": 1,
                    "confidence": 1.0,
                }
            )
    orientation, orientation_reliable = _table_orientation_status(_grid_to_markdown(grid))
    warnings = [] if orientation_reliable else ["orientation_defaulted_to_0"]
    return {
        "orientation": orientation,
        "columns": grid[0] if grid else [],
        "normalized_rows": grid[1:] if len(grid) > 1 else [],
        "source_cells": source_cells,
        "cell_status": cell_status,
        "warnings": warnings,
        "degraded": False,
        "manualReviewRequired": False,
        "reason": "",
    }


def _structured_table_payload(
    grid: List[List[str]],
    meta: Dict[str, Any],
    raw_html: str,
    markdown: str,
    degraded: bool,
    manual_review: bool,
    warnings: List[str],
    reason: str,
) -> Dict[str, Any]:
    columns = meta.get("columns") or (grid[0] if grid else [])
    normalized_rows = meta.get("normalized_rows") or (grid[1:] if len(grid) > 1 else [])
    return {
        "table_title": _table_title_from_markdown(markdown),
        "orientation": meta.get("orientation", 0),
        "columns": columns,
        "normalized_rows": normalized_rows,
        "rows": normalized_rows,
        "source_cells": meta.get("source_cells", []),
        "cell_status": meta.get("cell_status", []),
        "raw_html": raw_html,
        "markdown": markdown,
        "degraded": degraded,
        "manualReviewRequired": manual_review,
        "warnings": _dedupe(warnings),
        "reason": reason,
    }


def _structured_table_payload_json(payload: Dict[str, Any]) -> str:
    publish_payload = dict(payload)
    publish_payload.pop("raw_html", None)
    return json.dumps(publish_payload, ensure_ascii=False)


def _grid_to_delimited(grid: List[List[str]], delimiter: str) -> str:
    if not grid:
        return ""
    escaped_rows = []
    for row in grid:
        values = []
        for cell in row:
            value = str(cell if cell is not None else "")
            if delimiter == "," and any(ch in value for ch in [",", "\"", "\n"]):
                value = "\"" + value.replace("\"", "\"\"") + "\""
            values.append(value)
        escaped_rows.append(delimiter.join(values))
    return "\n".join(escaped_rows)


def _html_int_attr(attrs: str, name: str) -> int:
    match = re.search(rf"(?i)\b{re.escape(name)}\s*=\s*['\"]?(\d+)", str(attrs or ""))
    return int(match.group(1)) if match else 1


def _clean_html_cell(value: str) -> str:
    return _clean_html_cell_with_status(value)[0] or "n/a"


def _clean_html_cell_with_status(value: str) -> tuple[str, str]:
    text = re.sub(r"(?is)<br\s*/?>", "\n", str(value or ""))
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return "", "blank_in_source"
    if _is_unreadable_marker(text):
        return text, "unreadable"
    return text, "recognized"


def _cell_status_from_text(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return "blank_in_source"
    if _is_unreadable_marker(value):
        return "unreadable"
    return "recognized"


def _is_unreadable_marker(text: str) -> bool:
    value = str(text or "").strip().lower()
    return value in {"n/a", "na", "n.a.", "?", "？", "无法识别", "看不清", "unreadable"}


def _table_orientation_from_text(text: str) -> int:
    return _table_orientation_status(text)[0]


def _table_orientation_status(text: str) -> tuple[int, bool]:
    match = re.search(r'(?i)\borientation\b\s*[:=]\s*["\']?(0|90|180|270)', str(text or ""))
    if match:
        return int(match.group(1)), True
    return 0, False


def _ensure_row_width(row: List[str], width: int) -> None:
    while len(row) < width:
        row.append("")


def _ensure_optional_row_width(row: List[Optional[str]], width: int) -> None:
    while len(row) < width:
        row.append(None)


def _dedupe_cell_status(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out: List[Dict[str, Any]] = []
    for item in items:
        key = (item.get("row"), item.get("col"))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _escape_markdown_cell(value: str) -> str:
    return str(value if value is not None else "").replace("|", "\\|")


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


def _table_title_from_raw(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    for key in ["table_title", "tableName", "table_name", "表名", "caption", "title", "name"]:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:120]
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


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", str(text or "")))


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
