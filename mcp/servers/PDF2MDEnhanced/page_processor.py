from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import fitz

from .ocr_clients import OpenAICompatibleOcrClient, OcrResult
from .layout_ledger import (
    LAYOUT_VERSION,
    apply_recovered_payloads,
    blank_layout_outcome,
    build_layout_outcome,
    failed_layout_outcome,
    reconcile_layout,
    recovery_blocks,
    validate_recovered_object,
)
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
    bad_text_eval = _detect_bad_text(page, metrics, rc.get("bad_text_policy") or {})
    mode, reasons = _decide_mode(policy, metrics, rc)
    if policy != "force_direct" and bad_text_eval["detected"]:
        fallback_action = str((rc.get("bad_text_policy") or {}).get("fallback_action") or "").strip()
        if fallback_action == "force_vlm_for_page":
            mode = "FULL_VLM"
            reasons = _unique_keep_order(list(reasons) + ["bad_text_detected"] + list(bad_text_eval["reasons"]))
    route_decision = _decide_capability_route(policy, mode, reasons, metrics, bad_text_eval, rc)
    route_selected = route_decision["route_selected"]
    mode = route_decision["mode"]
    reasons = route_decision["reasons"]
    metrics.update(route_decision["signals"])
    logger.info(
        "process_page decision: sourcePageNo=%s routeSelected=%s mode=%s reasons=%s textLayerReliable=%s visualContentDetected=%s engineSelected=%s fallbackReason=%s",
        page_no,
        route_selected,
        mode,
        reasons,
        metrics.get("text_layer_reliable"),
        metrics.get("visual_content_detected"),
        route_decision.get("engine_selected"),
        route_decision.get("fallback_reason"),
    )

    with tempfile.TemporaryDirectory(prefix="pdf2md_enh_page_") as work_dir:
        image_path = _render_page_image(
            doc,
            page_no,
            Path(work_dir),
            dpi=rc["render_dpi"],
            rotate_deg=rc["render_rotate_deg"],
        )

        description_language = str(rc.get("description_language") or "unknown")
        effective_vlm_config = dict(vlm_config or rc.get("vlm_ocr") or {})
        effective_vlm_config["description_language"] = description_language
        vlm = DynamicVLMClient(effective_vlm_config)
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
        glm_calls = 0
        glm_ocr_config = dict(rc.get("glm_ocr") or {})
        glm_ocr_config["description_language"] = description_language
        glm_ocr = OpenAICompatibleOcrClient(glm_ocr_config, source="glm_ocr")
        layout_enabled = bool(rc.get("layout_ledger_enabled", True))
        layout_driven = False
        layout_outcome = None

        layout_probe = None
        if rc.get("debug_layout_probe"):
            try:
                layout_probe = vlm.recognize_layout(str(image_path))
            except Exception as exc:
                layout_probe = {"error": str(exc)}

        if layout_enabled:
            if route_selected == "blank":
                layout_outcome = blank_layout_outcome()
            elif not (
                glm_ocr.enabled
                and bool(getattr(glm_ocr, "use_layout_parsing", False))
                and callable(getattr(glm_ocr, "parse_layout", None))
            ):
                layout_outcome = failed_layout_outcome("layout_analysis_unavailable")
            else:
                try:
                    glm_calls += 1
                    raw_layout = glm_ocr.parse_layout(str(image_path))
                    render_scale = max(float(rc["render_dpi"]) / 72.0, 0.01)
                    fallback_width = float(page.rect.width) * render_scale
                    fallback_height = float(page.rect.height) * render_scale
                    if int(rc.get("render_rotate_deg", 0)) % 180:
                        fallback_width, fallback_height = fallback_height, fallback_width
                    layout_outcome = build_layout_outcome(
                        raw_layout,
                        display_page_no,
                        fallback_width,
                        fallback_height,
                    )
                    layout_driven = layout_outcome["layout_status"] == "EXTRACTED"
                    pending_blocks = recovery_blocks(layout_outcome)
                    if layout_driven and pending_blocks:
                        recovery_glm_calls, recovery_vlm_calls, recovery_diagnostics = _recover_layout_objects(
                            image_path=image_path,
                            output_dir=Path(work_dir),
                            layout_outcome=layout_outcome,
                            pending_blocks=pending_blocks,
                            vlm=vlm,
                            vlm_enabled=bool(rc.get("vlm_ocr_enabled") and vlm.enabled),
                            max_objects=rc["layout_recovery_max_objects"],
                            padding_ratio=rc["layout_recovery_crop_padding_ratio"],
                            glm=glm_ocr,
                            source_dpi=rc["render_dpi"],
                        )
                        glm_calls += recovery_glm_calls
                        vlm_calls += recovery_vlm_calls
                        layout_outcome["recovery"] = recovery_diagnostics
                except Exception as exc:
                    layout_outcome = failed_layout_outcome("layout_analysis_failed")
                    logger.warning(
                        "layout analysis failed: sourcePageNo=%s error_type=%s",
                        page_no,
                        type(exc).__name__,
                    )

        if route_selected == "blank":
            markdown = ""
            structured = {"formulas": [], "tables": [], "figures": []}
            rag_page_text = ""
        elif layout_driven:
            markdown = _clean_markdown(layout_outcome.get("markdown") or "")
            structured = _normalize_structured(layout_outcome.get("payloads") or {})
            rag_page_text = markdown
            route_selected = "full_glm_ocr"
            route_decision["engine_selected"] = "glm_ocr_layout"
            route_decision["reasons"] = _unique_keep_order(
                list(route_decision.get("reasons") or []) + ["layout_ledger"]
            )
        elif mode == "DIRECT":
            markdown = _build_direct_markdown(page)
            structured = {"formulas": [], "tables": [], "figures": []}
            rag_page_text = ""
        elif route_selected == "hybrid_glm_ocr":
            markdown = _build_direct_markdown(page)
            rag_page_text = ""
            try:
                glm_calls += 1
                glm_result = glm_ocr.extract_page(str(image_path))
                structured = _structured_from_ocr_result(glm_result, include_figures=False)
                markdown = _merge_region_vlm_markdown(markdown, structured)
                if _structured_insufficient_for_route(structured, route_selected, metrics):
                    raise RuntimeError("glm_ocr_insufficient_structured_output")
            except Exception as err:
                if rc.get("vlm_ocr_enabled") and vlm.enabled:
                    route_selected = "hybrid_vlm_ocr"
                    route_decision["fallback_reason"] = str(err)
                    structured = _normalize_structured(vlm.extract_region_structured(str(image_path)))
                    vlm_calls += 1
                    markdown = _merge_region_vlm_markdown(markdown, structured)
                else:
                    route_decision["fallback_reason"] = str(err)
                    structured = {"formulas": [], "tables": [], "figures": []}
        elif route_selected == "full_glm_ocr":
            glm_markdown_candidate = ""
            glm_rag_page_text = ""
            glm_structured_candidate = {"formulas": [], "tables": [], "figures": []}
            try:
                glm_calls += 1
                glm_result = glm_ocr.extract_page(str(image_path))
                markdown = _clean_markdown(glm_result.markdown)
                rag_page_text = glm_result.page_text
                structured = _structured_from_ocr_result(glm_result, include_figures=False)
                if _glm_ocr_markdown_bad(markdown):
                    raise RuntimeError("glm_ocr_bad_markdown")
                glm_markdown_candidate = markdown
                glm_rag_page_text = rag_page_text
                glm_structured_candidate = structured
                if _structured_insufficient_for_route(structured, route_selected, metrics):
                    raise RuntimeError("glm_ocr_insufficient_structured_output")
                if (
                    route_decision["signals"].get("has_meaningful_figures")
                    and rc.get("figure_semantic_description_required")
                    and rc.get("vlm_ocr_enabled")
                    and vlm.enabled
                ):
                    figure_structured = _normalize_structured(vlm.extract_region_structured(str(image_path)))
                    structured["figures"] = figure_structured.get("figures") or []
                    vlm_calls += 1
            except Exception as err:
                if rc.get("full_vlm_fallback_enabled") and rc.get("vlm_ocr_enabled") and vlm.enabled:
                    route_selected = "full_vlm_ocr"
                    route_decision["fallback_reason"] = str(err)
                    rag_page_text = ""
                    vlm_calls += 1
                    try:
                        dual = vlm.full_page_dual_output(str(image_path))
                        markdown = _clean_markdown(dual.get("render") or "")
                        rag_obj = dual.get("rag") or {}
                        rag_page_text = str(rag_obj.get("page_text") or "").strip()
                        structured = _normalize_structured(rag_obj.get("elements"))
                        if not markdown.strip():
                            raise RuntimeError("full_vlm_empty_render")
                    except Exception as vlm_err:
                        route_decision["fallback_reason"] = str(vlm_err)
                        if glm_markdown_candidate:
                            route_selected = "full_glm_ocr"
                            markdown = glm_markdown_candidate
                            rag_page_text = glm_rag_page_text
                            structured = glm_structured_candidate
                            logger.warning(
                                "full VLM fallback failed; preserving usable GLM markdown: error_type=%s",
                                type(vlm_err).__name__,
                            )
                        elif rc.get("full_vlm_retry_markdown", False):
                            markdown = _clean_markdown(vlm.full_page_markdown(str(image_path)))
                            vlm_calls += 1
                            structured = {"formulas": [], "tables": [], "figures": []}
                            if not markdown.strip():
                                raise RuntimeError("full_vlm_empty_render")
                        else:
                            raise
                else:
                    raise
        elif route_selected == "hybrid_vlm_ocr" and (not rc.get("vlm_ocr_enabled") or not vlm.enabled):
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
            markdown = _build_direct_markdown(page)
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
    if not layout_driven:
        structured["tables"] = _select_rag_tables(markdown, structured.get("tables") or [])
    rag_content = _build_rag_content(markdown, structured, rag_page_text=rag_page_text)
    table_source = _detect_table_source(markdown, structured)
    semantic_status = _semantic_status(route_selected, metrics, structured, rc, route_decision.get("fallback_reason"))
    if layout_driven:
        output_elements = _build_layout_output_elements(
            markdown,
            layout_outcome.get("payloads") or {},
            route_selected,
            description_language,
        )
    else:
        output_elements = _build_output_elements(
            markdown,
            structured,
            route_selected,
            description_language,
        )

    reconciliation = None
    if layout_enabled and layout_outcome is not None:
        reconciliation = reconcile_layout(
            layout_outcome.get("layout_status") or "FAILED",
            layout_outcome.get("layout") or [],
            output_elements,
            layout_outcome.get("unmatched_recovery_refs") or [],
        )
        if layout_driven:
            failed_layout_ids = [
                item["layout_id"]
                for item in layout_outcome.get("layout") or []
                if item.get("status") == "FAILED"
            ]
            semantic_status = {
                "complete": reconciliation["complete"],
                "missing": failed_layout_ids,
                "reason": "" if reconciliation["complete"] else "layout_objects_incomplete",
            }

    rag_obj = {
        "content": rag_content,
        "page_text": _strip_layout_noise_lines(rag_page_text.strip() or markdown.strip()),
        "elements": output_elements,
    }
    if _should_emit_chunks(rc):
        rag_obj["chunks"] = _build_chunks(rag_content, chunk_size=rc["chunk_size"])

    legacy_route_selected = "vlm" if layout_driven else ("text_layer" if mode == "DIRECT" else "vlm")

    result = {
        "task_page_id": hashlib.sha1(f"{source_path}:{page_no}".encode("utf-8")).hexdigest()[:16],
        "page_no": page_no,
        "route_selected": route_selected,
        "legacy_route_selected": legacy_route_selected,
        "semantic_status": semantic_status,
        "bad_text_detected": bad_text_eval["detected"],
        "bad_text_reasons": bad_text_eval["reasons"],
        "text_quality_summary": bad_text_eval["summary"],
        "decision": {
            "mode": mode,
            "reasons": reasons,
            "metrics": metrics,
            "vlm_calls": vlm_calls,
            "glm_calls": glm_calls,
            "source_page_no": display_page_no,
            "table_source": table_source,
            "table_placeholder_count": len(table_placeholders),
            "layout_probe": layout_probe,
            "route_selected": route_selected,
            "legacy_route_selected": legacy_route_selected,
            "engine_selected": route_decision.get("engine_selected"),
            "fallback_reason": route_decision.get("fallback_reason"),
            "vlm_budget": getattr(vlm, "last_dual_output_budget", {}),
            "semantic_status": semantic_status,
            "bad_text_detected": bad_text_eval["detected"],
            "bad_text_reasons": bad_text_eval["reasons"],
            "text_quality_summary": bad_text_eval["summary"],
        },
        "render": {"markdown": markdown},
        "rag": rag_obj,
        "elements": output_elements,
        "next_context": next_context,
        "page_type": "blank" if route_selected == "blank" else "normal",
    }
    if layout_enabled and layout_outcome is not None:
        result.update(
            {
                "layout_version": LAYOUT_VERSION,
                "layout_status": layout_outcome.get("layout_status") or "FAILED",
                "bbox_space": "normalized_page",
                "page_width": 1.0,
                "page_height": 1.0,
                "source_page_width": layout_outcome.get("source_page_width"),
                "source_page_height": layout_outcome.get("source_page_height"),
                "source_bbox_space": layout_outcome.get("source_bbox_space"),
                "source_page_index": layout_outcome.get("source_page_index"),
                "layout": layout_outcome.get("layout") or [],
                "reconciliation": reconciliation,
                "layout_recovery": layout_outcome.get("recovery") or {
                    "contract": "object-crop-content-v1",
                    "pending": 0,
                    "attempted": 0,
                    "limit": rc["layout_recovery_max_objects"],
                    "objects": [],
                },
            }
        )
        result["decision"]["layout_recovery"] = result["layout_recovery"]
        result["decision"]["layout_status"] = layout_outcome.get("layout_status") or "FAILED"
        result["decision"]["layout_error"] = layout_outcome.get("layout_error") or ""
        if layout_outcome.get("layout_error"):
            result["layout_error"] = layout_outcome["layout_error"]
    return result


def _routing_defaults(cfg: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    c = cfg or {}
    ocr_config = c.get("ocr_config") if isinstance(c.get("ocr_config"), dict) else {}
    glm_ocr = ocr_config.get("glm_ocr") if isinstance(ocr_config.get("glm_ocr"), dict) else {}
    vlm_ocr = ocr_config.get("vlm_ocr") if isinstance(ocr_config.get("vlm_ocr"), dict) else {}
    routing = c.get("routing") if isinstance(c.get("routing"), dict) else {}
    return {
        "text_chars_min": int(c.get("text_chars_min", 80)),
        "image_area_ratio_full_vlm": float(c.get("image_area_ratio_full_vlm", 0.55)),
        "noise_ratio_full_vlm": float(c.get("noise_ratio_full_vlm", 0.30)),
        "formula_score_region_vlm": float(c.get("formula_score_region_vlm", 0.12)),
        "table_score_region_vlm": float(c.get("table_score_region_vlm", 0.20)),
        "render_dpi": int(c.get("render_dpi", 220)),
        "render_rotate_deg": int(c.get("render_rotate_deg", 0)),
        "source_page_no": int(c.get("source_page_no", 0) or 0),
        "description_language": str(c.get("description_language") or "unknown"),
        "chunk_size": int(c.get("chunk_size", 700)),
        "enable_chunks": bool(c.get("enable_chunks", False)),
        "chunk_policy": str(c.get("chunk_policy", "disabled")),
        "task_total_pages": int(c.get("__task_total_pages", 1)),
        "layout_ledger_enabled": bool(c.get("layout_ledger_enabled", True)),
        "layout_recovery_max_objects": max(0, min(int(c.get("layout_recovery_max_objects", 8)), 16)),
        "layout_recovery_crop_padding_ratio": max(
            0.0,
            min(float(c.get("layout_recovery_crop_padding_ratio", 0.02)), 0.1),
        ),
        "debug_layout_probe": bool(c.get("debug_layout_probe", False)),
        "full_vlm_split_extract": bool(c.get("full_vlm_split_extract", False)),
        # Default ON: complex pages often return invalid/empty dual JSON.
        # Markdown retry avoids hard-failing pages when render can still be recovered.
        "full_vlm_retry_markdown": bool(c.get("full_vlm_retry_markdown", True)),
        "render_cleanup_with_llm": bool(c.get("render_cleanup_with_llm", True)),
        "hybrid_ocr_enabled": bool(routing.get("hybrid_ocr_enabled", c.get("hybrid_ocr_enabled", True))),
        "glm_ocr_enabled": bool(routing.get("glm_ocr_enabled", c.get("glm_ocr_enabled", bool(glm_ocr.get("enabled", False))))),
        "vlm_ocr_enabled": bool(routing.get("vlm_ocr_enabled", c.get("vlm_ocr_enabled", True))),
        "full_vlm_fallback_enabled": bool(
            routing.get("full_vlm_fallback_enabled", c.get("full_vlm_fallback_enabled", True))
        ),
        "figure_semantic_description_required": bool(
            routing.get(
                "figure_semantic_description_required",
                c.get("figure_semantic_description_required", True),
            )
        ),
        "glm_ocr": {**glm_ocr, "enabled": bool(glm_ocr.get("enabled", False) and routing.get("glm_ocr_enabled", c.get("glm_ocr_enabled", True)))},
        "vlm_ocr": vlm_ocr,
        "large_table_placeholder_enabled": bool(c.get("large_table_placeholder_enabled", True)),
        "large_table_min_cols": int(c.get("large_table_min_cols", 12)),
        "large_table_min_rows": int(c.get("large_table_min_rows", 16)),
        "large_table_min_cells": int(c.get("large_table_min_cells", 180)),
        "bad_text_policy": _bad_text_policy_defaults(c.get("bad_text_policy")),
    }


def _bad_text_policy_defaults(cfg: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    c = cfg or {}
    thresholds = c.get("thresholds") or {}
    return {
        "enabled": bool(c.get("enabled", False)),
        "fallback_action": str(c.get("fallback_action") or ""),
        "persist_bad_text": bool(c.get("persist_bad_text", False)),
        "signals": list(c.get("signals") or []),
        "thresholds": {
            "max_cjk_ratio": float(thresholds.get("max_cjk_ratio", 0.01)),
            "min_ascii_symbol_ratio": float(thresholds.get("min_ascii_symbol_ratio", 0.60)),
            "min_long_symbol_runs": int(thresholds.get("min_long_symbol_runs", 3)),
        },
        "decision_prompt": str(c.get("decision_prompt") or ""),
        "near_empty_text_chars_max": int(c.get("near_empty_text_chars_max", 20)),
        "visual_content_image_ratio_min": float(c.get("visual_content_image_ratio_min", 0.08)),
        "visual_content_drawing_density_min": float(c.get("visual_content_drawing_density_min", 0.30)),
        "visual_content_non_text_blocks_min": int(c.get("visual_content_non_text_blocks_min", 1)),
        "long_symbol_run_length": int(c.get("long_symbol_run_length", 4)),
    }


def _collect_metrics(page: fitz.Page) -> Dict[str, Any]:
    page_area = float(page.rect.width * page.rect.height) or 1.0
    text = page.get_text("text") or ""
    compact_text = re.sub(r"\s+", "", text)
    text_chars = len(compact_text)
    text_blocks = len(page.get_text("blocks") or [])
    cjk_count = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", compact_text))
    ascii_symbol_count = len(re.findall(r"[!-/:-@\\[-`{-~]", compact_text))
    long_symbol_runs = len(re.findall(r"(?:(?<!\w)[!-/:-@\\[-`{-~]{4,}(?!\w))", text))
    private_use_chars = len(re.findall(r"[\uE000-\uF8FF]", text))
    cid_like_tokens = len(re.findall(r"\(cid:\d+\)", text, flags=re.IGNORECASE))

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
    cjk_ratio = cjk_count / max(text_chars, 1)
    ascii_symbol_ratio = ascii_symbol_count / max(text_chars, 1)

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

    non_text_blocks = 0
    try:
        dict_payload = page.get_text("dict") or {}
        for block in dict_payload.get("blocks", []):
            if block.get("type") != 0:
                non_text_blocks += 1
    except Exception:
        non_text_blocks = 0

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
        "text_sample": text[:500],
        "text_blocks": text_blocks,
        "image_area_ratio": round(image_area_ratio, 4),
        "drawing_density": round(drawing_density, 4),
        "noise_ratio": round(noise_ratio, 4),
        "cjk_ratio": round(cjk_ratio, 4),
        "ascii_symbol_ratio": round(ascii_symbol_ratio, 4),
        "long_symbol_runs": int(long_symbol_runs),
        "private_use_chars": int(private_use_chars),
        "cid_like_tokens": int(cid_like_tokens),
        "missing_unicode_mapping": bool(noise_chars > 0 or private_use_chars > 0 or cid_like_tokens > 0),
        "visual_content_detected": bool(
            image_area_ratio >= 0.08 or drawing_density >= 0.30 or non_text_blocks >= 1
        ),
        "non_text_blocks": int(non_text_blocks),
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


def _decide_capability_route(
    policy: str,
    legacy_mode: str,
    reasons: list[str],
    metrics: Dict[str, Any],
    bad_text_eval: Dict[str, Any],
    rc: Dict[str, Any],
) -> Dict[str, Any]:
    glm_available = bool(rc.get("hybrid_ocr_enabled") and rc.get("glm_ocr_enabled") and (rc.get("glm_ocr") or {}).get("enabled"))
    vlm_available = bool(rc.get("vlm_ocr_enabled"))
    blank_page = _looks_blank(metrics)
    text_layer_bad = bool(
        bad_text_eval.get("detected")
        or legacy_mode == "FULL_VLM"
        or (
            int(metrics.get("text_chars", 0) or 0) < int(rc.get("text_chars_min", 80))
            and bool(metrics.get("visual_content_detected", False))
        )
    )
    text_layer_reliable = bool(
        not text_layer_bad
        and (
            legacy_mode in {"DIRECT", "REGION_VLM"}
            or int(metrics.get("text_chars", 0) or 0) >= int(rc.get("text_chars_min", 80))
        )
    )
    page_text = str(metrics.get("text_sample") or "")
    needs_formula_latex = bool(
        float(metrics.get("formula_score", 0.0) or 0.0) >= float(rc.get("formula_score_region_vlm", 0.12))
        or re.search(r"按.*式|式中|公式|计算式", page_text)
    )
    needs_table_structure = bool(
        float(metrics.get("table_score", 0.0) or 0.0) >= float(rc.get("table_score_region_vlm", 0.20))
        or int(metrics.get("native_table_count", 0) or 0) > 0
    )
    has_meaningful_figures = bool(
        metrics.get("visual_content_detected")
        and not needs_table_structure
        and (
            float(metrics.get("image_area_ratio", 0.0) or 0.0) >= 0.12
            or float(metrics.get("drawing_density", 0.0) or 0.0) >= 0.45
        )
    )

    route = "text_only"
    mode = legacy_mode
    route_reasons = list(reasons or [])
    if policy == "force_direct":
        route = "text_only"
        mode = "DIRECT"
    elif policy == "force_vlm":
        route = "full_vlm_ocr"
        mode = "FULL_VLM"
    elif blank_page:
        route = "blank"
        mode = "DIRECT"
        route_reasons = _unique_keep_order(route_reasons + ["blank_page"])
    elif glm_available:
        # Do not treat the PDF text layer as authoritative page content. It can
        # silently omit section labels even when it otherwise looks reliable.
        route = "full_glm_ocr"
        mode = "FULL_VLM"
        route_reasons = _unique_keep_order(route_reasons + ["glm_ocr_primary"])
    elif vlm_available:
        route = "full_vlm_ocr"
        mode = "FULL_VLM"
    else:
        route = "text_only"
        mode = "DIRECT"

    engine = {
        "text_only": "text_layer",
        "hybrid_glm_ocr": "text_layer+glm_ocr",
        "hybrid_vlm_ocr": "text_layer+vlm_ocr",
        "full_glm_ocr": "glm_ocr",
        "full_vlm_ocr": "vlm_ocr",
        "blank": "none",
    }.get(route, "unknown")

    return {
        "route_selected": route,
        "mode": mode,
        "reasons": _unique_keep_order(route_reasons),
        "engine_selected": engine,
        "fallback_reason": "",
        "signals": {
            "has_meaningful_figures": has_meaningful_figures,
            "needs_formula_latex": needs_formula_latex,
            "needs_table_structure": needs_table_structure,
            "text_layer_reliable": text_layer_reliable,
            "text_layer_bad": text_layer_bad,
            "glm_ocr_available": glm_available,
            "vlm_ocr_available": vlm_available,
            "blank_page": blank_page,
        },
    }


def _looks_blank(metrics: Dict[str, Any]) -> bool:
    return bool(
        int(metrics.get("text_chars", 0) or 0) == 0
        and float(metrics.get("image_area_ratio", 0.0) or 0.0) < 0.01
        and float(metrics.get("drawing_density", 0.0) or 0.0) < 0.05
        and int(metrics.get("non_text_blocks", 0) or 0) == 0
    )


def _detect_bad_text(page: fitz.Page, metrics: Dict[str, Any], policy: Dict[str, Any]) -> Dict[str, Any]:
    summary = {
        "cjk_ratio": float(metrics.get("cjk_ratio", 0.0) or 0.0),
        "ascii_symbol_ratio": float(metrics.get("ascii_symbol_ratio", 0.0) or 0.0),
        "long_symbol_runs": int(metrics.get("long_symbol_runs", 0) or 0),
        "missing_unicode_mapping": bool(metrics.get("missing_unicode_mapping", False)),
    }
    if not policy.get("enabled"):
        return {"detected": False, "reasons": [], "summary": summary}

    thresholds = policy.get("thresholds") or {}
    enabled_signals = set(policy.get("signals") or [])
    reasons: list[str] = []

    if "missing_unicode_mapping" in enabled_signals and _has_missing_unicode_mapping(page, metrics):
        reasons.append("missing_unicode_mapping")

    if (
        "low_cjk_ratio" in enabled_signals
        and "high_ascii_symbol_ratio" in enabled_signals
        and summary["cjk_ratio"] <= float(thresholds.get("max_cjk_ratio", 0.01))
        and summary["ascii_symbol_ratio"] >= float(thresholds.get("min_ascii_symbol_ratio", 0.60))
    ):
        reasons.extend(["low_cjk_ratio", "high_ascii_symbol_ratio"])

    if (
        "long_ascii_symbol_runs" in enabled_signals
        and _count_long_symbol_runs(page, min_run_length=int(policy.get("long_symbol_run_length", 4)))
        >= int(thresholds.get("min_long_symbol_runs", 3))
    ):
        reasons.append("long_ascii_symbol_runs")

    if (
        "empty_or_near-empty_text_with_visual_content" in enabled_signals
        and int(metrics.get("text_chars", 0) or 0) <= int(policy.get("near_empty_text_chars_max", 20))
        and _has_visual_content(metrics, policy)
    ):
        reasons.append("empty_or_near-empty_text_with_visual_content")

    return {"detected": bool(reasons), "reasons": _unique_keep_order(reasons), "summary": summary}


def _has_missing_unicode_mapping(page: fitz.Page, metrics: Dict[str, Any]) -> bool:
    if bool(metrics.get("missing_unicode_mapping", False)):
        return True

    try:
        raw = page.get_text("rawdict") or {}
    except Exception:
        raw = {}

    suspicious_spans = 0
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                span_text = _span_text(span).strip()
                if not span_text:
                    continue
                if re.search(r"\(cid:\d+\)", span_text, flags=re.IGNORECASE):
                    return True
                if re.search(r"[\uE000-\uF8FF\uFFFD�]", span_text):
                    return True
                if _looks_like_garbled_symbol_span(span_text):
                    suspicious_spans += 1
                    if suspicious_spans >= 2:
                        return True
    return False


def _count_long_symbol_runs(page: fitz.Page, min_run_length: int = 4) -> int:
    text = page.get_text("text") or ""
    pattern = r"(?:(?<!\w)[^\w\s]{%d,}(?!\w))" % max(3, int(min_run_length or 4))
    return len(re.findall(pattern, text))


def _has_visual_content(metrics: Dict[str, Any], policy: Dict[str, Any]) -> bool:
    return bool(
        float(metrics.get("image_area_ratio", 0.0) or 0.0) >= float(policy.get("visual_content_image_ratio_min", 0.08))
        or float(metrics.get("drawing_density", 0.0) or 0.0) >= float(policy.get("visual_content_drawing_density_min", 0.30))
        or int(metrics.get("non_text_blocks", 0) or 0) >= int(policy.get("visual_content_non_text_blocks_min", 1))
        or bool(metrics.get("visual_content_detected", False))
    )


def _span_text(span: Dict[str, Any]) -> str:
    chars = span.get("chars")
    if isinstance(chars, list):
        return "".join([str(ch.get("c") or "") for ch in chars])
    return str(span.get("text") or "")


def _looks_like_garbled_symbol_span(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""))
    if len(compact) < 4:
        return False
    symbol_ratio = len(re.findall(r"[!-/:-@\\[-`{-~]", compact)) / max(len(compact), 1)
    return symbol_ratio >= 0.75 and not re.search(r"[A-Za-z0-9\u3400-\u4dbf\u4e00-\u9fff]", compact)


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


def _recover_layout_objects(
    image_path: Path,
    output_dir: Path,
    layout_outcome: Dict[str, Any],
    pending_blocks: list[Dict[str, Any]],
    vlm: DynamicVLMClient,
    vlm_enabled: bool,
    max_objects: int,
    padding_ratio: float,
    glm: Optional[OpenAICompatibleOcrClient] = None,
    source_dpi: float = 150,
) -> tuple[int, int, Dict[str, Any]]:
    glm_calls = 0
    vlm_calls = 0
    limit = max(0, min(int(max_objects), 16))
    diagnostics: Dict[str, Any] = {
        "contract": "object-crop-content-v1",
        "pending": len(pending_blocks),
        "attempted": 0,
        "limit": limit,
        "objects": [],
    }

    for index, block in enumerate(pending_blocks):
        layout_id = str(block.get("layout_id") or "")
        object_type = str(block.get("type") or "unknown")
        item_diagnostics: Dict[str, Any] = {
            "layout_id": layout_id,
            "type": object_type,
            "crop": None,
            "attempts": [],
            "outcome": "failed",
        }
        diagnostics["objects"].append(item_diagnostics)
        use_glm = (object_type == "table" and bool(getattr(glm, "enabled", False))
                   and callable(getattr(glm, "extract_table_html", None)))
        if index >= limit or not (vlm_enabled or use_glm):
            item_diagnostics.update({
                "outcome": "not_attempted", "review_required": True,
                "reason": "recovery_limit_exceeded" if index >= limit else "provider_unavailable",
            })
            continue
        diagnostics["attempted"] += 1
        try:
            crop_path, crop_info = _crop_layout_block_image(
                image_path,
                block,
                output_dir,
                padding_ratio=padding_ratio,
                source_dpi=source_dpi,
            )
            item_diagnostics["crop"] = crop_info
        except Exception as exc:
            item_diagnostics["attempts"].append(
                {"provider": "crop", "outcome": "failed", "reason": type(exc).__name__}
            )
            item_diagnostics["review_required"] = True
            continue

        # At most two OCR attempts, then two VLM attempts. The second attempt
        # for each provider uses fewer pixels, never the same oversized image.
        providers = (["glm_ocr"] * 2 if use_glm else []) + (["vlm_ocr"] * 2 if vlm_enabled else [])
        skip_glm = False
        for attempt_no, provider in enumerate(providers, 1):
            if provider == "glm_ocr" and skip_glm:
                continue
            compact = attempt_no > 1 and providers[attempt_no - 2] == provider
            client = glm if provider == "glm_ocr" else vlm
            attempt: Dict[str, Any] = {
                "attempt": attempt_no, "mode": "compact" if compact else "initial",
                "provider": provider, "endpoint_kind": "layout_parsing" if provider == "glm_ocr"
                and getattr(glm, "use_layout_parsing", False) else "image_chat_completions",
                "outcome": "not_recovered",
            }
            item_diagnostics["attempts"].append(attempt)
            client.last_object_call_info = {}
            try:
                if compact:
                    crop_path, crop_info = _shrink_recovery_image(crop_path, crop_info, 2 / 3)
                attempt["image_width"] = crop_info["width"]
                attempt["image_height"] = crop_info["height"]
                if provider == "glm_ocr":
                    glm_calls += 1
                else:
                    vlm_calls += 1
                if object_type == "table":
                    html = (glm.extract_table_html(str(crop_path)) if provider == "glm_ocr" else
                            vlm.extract_table_html(str(crop_path), block, compact=compact))
                    candidate = {
                        "layout_id": layout_id,
                        "type": "table",
                        "status": "EXTRACTED",
                        "complete": True,
                        "markdown": html,
                    }
                else:
                    candidate = vlm.extract_object_structured(str(crop_path), block, compact=compact)
                attempt.update(_safe_object_call_info(client))
                reason, shape = validate_recovered_object(block, candidate)
                attempt.update(shape)
                if attempt.get("truncated") or attempt.get("finish_reason") == "length":
                    reason = "provider_output_truncated"
                elif attempt.get("finish_reason") in {"content_filter", "tool_calls"}:
                    reason = "provider_content_blocked"
                elif object_type != "table" and attempt.get("json_status") in {"empty", "invalid", "non_object"}:
                    reason = {"empty": "response_empty", "invalid": "response_json_invalid",
                              "non_object": "response_invalid"}[attempt["json_status"]]
                if not reason:
                    payload = _object_success_payload(block, candidate)
                    if provider == "glm_ocr":
                        payload["source"] = "glm_ocr_layout+glm_object_crop"
                    apply_recovered_payloads(layout_outcome, _single_recovery_result(object_type, payload))
                    if _layout_entry_recovered(layout_outcome, layout_id):
                        attempt.update({"outcome": "recovered", "reason": "validated_object"})
                        item_diagnostics["outcome"] = "recovered"
                        item_diagnostics["provider"] = provider
                        break
                    reason = "ledger_binding_failed"
                attempt["reason"] = reason
                if reason in {"layout_id_mismatch", "object_type_mismatch"}:
                    refs = layout_outcome.setdefault("unmatched_recovery_refs", [])
                    refs.append(f"{layout_id}:{reason}")
                if not _object_content_retryable(reason):
                    break
            except Exception as exc:
                attempt.update(_safe_object_call_info(client))
                attempt.update({"outcome": "failed", "reason": type(exc).__name__})
                if provider == "glm_ocr":
                    skip_glm = True
                    continue
                break

        if item_diagnostics["outcome"] != "recovered":
            item_diagnostics["review_required"] = True
    return glm_calls, vlm_calls, diagnostics


def _object_content_retryable(reason: str) -> bool:
    return reason in {
        "response_empty", "response_invalid", "response_json_invalid", "provider_reported_incomplete",
        "provider_output_truncated", "table_content_empty", "table_html_unclosed", "table_html_invalid",
        "table_cells_missing", "table_count_invalid", "table_markdown_invalid", "formula_content_empty",
        "formula_unbalanced", "figure_content_empty",
    }


def _safe_object_call_info(vlm: DynamicVLMClient) -> Dict[str, Any]:
    raw = getattr(vlm, "last_object_call_info", {}) or {}
    result: Dict[str, Any] = {}
    for key in ("response_chars", "requested_max_tokens", "effective_max_tokens"):
        value = raw.get(key)
        result[key] = value if type(value) is int and value >= 0 else None
    for key, allowed in {
        "finish_reason": {"stop", "length", "content_filter", "tool_calls", "other"},
        "json_status": {"object", "html", "empty", "invalid", "non_object"},
        "call_mode": {"stream", "non_stream", "unknown"},
    }.items():
        value = raw.get(key)
        result[key] = value if isinstance(value, str) and value in allowed else None
    result["truncated"] = raw.get("truncated") is True or result["finish_reason"] == "length"
    return result


def _object_success_payload(block: Dict[str, Any], candidate: Dict[str, Any]) -> Dict[str, Any]:
    keys = {
        "table": ("markdown", "title"), "formula": ("latex", "description", "variables", "context"),
        "figure": ("description", "caption"),
    }[block["type"]]
    return {
        **{key: candidate[key] for key in keys if isinstance(candidate.get(key), str)},
        "layout_id": block["layout_id"], "source": "glm_ocr_layout+vlm_object_crop",
    }


def _crop_layout_block_image(
    image_path: Path,
    block: Dict[str, Any],
    output_dir: Path,
    padding_ratio: float = 0.02,
    source_dpi: float = 150,
) -> tuple[Path, Dict[str, Any]]:
    source = fitz.Pixmap(str(image_path))
    bbox = block.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        raise ValueError("layout recovery bbox missing")
    try:
        x0, y0, x1, y1 = [float(value) for value in bbox]
    except (TypeError, ValueError) as exc:
        raise ValueError("layout recovery bbox invalid") from exc
    x0, y0 = max(0.0, min(x0, 1.0)), max(0.0, min(y0, 1.0))
    x1, y1 = max(0.0, min(x1, 1.0)), max(0.0, min(y1, 1.0))
    if x1 <= x0 or y1 <= y0:
        raise ValueError("layout recovery bbox invalid")

    pad_x = max(2.0, (x1 - x0) * source.width * max(0.0, float(padding_ratio)))
    pad_y = max(2.0, (y1 - y0) * source.height * max(0.0, float(padding_ratio)))
    left = max(0, math.floor(x0 * source.width - pad_x))
    top = max(0, math.floor(y0 * source.height - pad_y))
    right = min(source.width, math.ceil(x1 * source.width + pad_x))
    bottom = min(source.height, math.ceil(y1 * source.height + pad_y))
    if right <= left or bottom <= top:
        raise ValueError("layout recovery crop empty")

    crop_width = right - left
    crop_height = bottom - top
    samples = memoryview(source.samples)
    rows = [
        samples[row * source.stride + left * source.n : row * source.stride + right * source.n]
        for row in range(top, bottom)
    ]
    crop = fitz.Pixmap(
        source.colorspace,
        crop_width,
        crop_height,
        b"".join(bytes(row) for row in rows),
        source.alpha,
    )
    scale = min(1.0, 150.0 / max(float(source_dpi), 1.0))
    if scale < 1:
        crop = fitz.Pixmap(crop, max(1, math.floor(crop_width * scale)),
                          max(1, math.floor(crop_height * scale)))
    dpi = max(1, min(150, int(source_dpi)))
    crop.set_dpi(dpi, dpi)
    safe_layout_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(block.get("layout_id") or "object"))
    output_path = output_dir / f"layout-recovery-{safe_layout_id}.png"
    crop.save(str(output_path))
    return output_path, {
        "pixel_bbox": [left, top, right, bottom],
        "width": crop.width,
        "height": crop.height,
        "padding_ratio": float(padding_ratio),
    }


def _shrink_recovery_image(
    image_path: Path, crop_info: Dict[str, Any], scale: float,
) -> tuple[Path, Dict[str, Any]]:
    source = fitz.Pixmap(str(image_path))
    resized = fitz.Pixmap(source, max(1, math.floor(source.width * scale)),
                         max(1, math.floor(source.height * scale)))
    resized.set_dpi(max(1, int(source.xres * scale)), max(1, int(source.yres * scale)))
    output = image_path.with_name(f"{image_path.stem}-smaller.png")
    resized.save(str(output))
    return output, {**crop_info, "width": resized.width, "height": resized.height}


def _single_recovery_result(object_type: str, candidate: Dict[str, Any]) -> Dict[str, Any]:
    result = {"tables": [], "formulas": [], "figures": []}
    collection = {"table": "tables", "formula": "formulas", "figure": "figures"}.get(object_type)
    if collection:
        result[collection] = [candidate]
    return result


def _layout_entry_recovered(layout_outcome: Dict[str, Any], layout_id: str) -> bool:
    return any(
        str(item.get("layout_id") or "") == layout_id and item.get("status") == "EXTRACTED"
        for item in layout_outcome.get("layout") or []
    )


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
        # A PyMuPDF text block may contain several consecutive clause headings.
        # Keeping only its prefix silently drops valid sections such as "7.1".
        cleaned = _clean_markdown(raw_text)
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
    return _format_text_layer_markdown(_clean_markdown(merged))


def _format_text_layer_markdown(text: str) -> str:
    """Restore only unambiguous clause headings from text-layer line breaks."""
    lines = str(text or "").splitlines()
    formatted: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        match = re.fullmatch(r"\s*(\d+(?:\s*\.\s*\d+){1,4})\s*\.?\s*", line)
        if match and index + 1 < len(lines):
            title = lines[index + 1].strip()
            if _is_clause_title_line(title):
                number = re.sub(r"\s*\.\s*", ".", match.group(1))
                formatted.append(f"## {number} {title}")
                index += 2
                continue
        formatted.append(line)
        index += 1
    return _clean_markdown("\n".join(formatted))


def _is_clause_title_line(line: str) -> bool:
    value = str(line or "").strip()
    if not value or len(value) > 120:
        return False
    if value.startswith(("#", "|", "$$", "[")):
        return False
    return not value.endswith(("。", "；", ";", ".", ":", "："))


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


def _build_output_elements(
    markdown: str,
    structured: Dict[str, Any],
    route_selected: str,
    description_language: str = "unknown",
) -> Dict[str, Any]:
    lines = (markdown or "").splitlines()
    table_source = "glm_ocr" if "glm" in route_selected else ("vlm_ocr" if "vlm" in route_selected else "pymupdf")
    formula_source = "glm_ocr" if "glm" in route_selected else "vlm_ocr"
    table_metadata = structured.get("table_metadata") or {}
    tables = []
    for table in structured.get("tables") or []:
        table_text = str(table or "").strip()
        if not table_text:
            continue
        metadata = table_metadata.get(table_text) if isinstance(table_metadata, dict) else None
        metadata = metadata if isinstance(metadata, dict) else {}
        title = str(metadata.get("title") or "").strip()
        if not title and not metadata.get("layout_id"):
            title = _title_for_table(table_text, lines)
        item = {
            "source": table_source if not table_text.startswith("[TABLE_PLACEHOLDER]") else "pymupdf",
            "title": title,
            "markdown": table_text,
            "semantic_summary": str(metadata.get("description") or "").strip()
            or _table_summary(title, table_text, description_language),
            "context": str(metadata.get("context") or "").strip() or _context_for_anchor(title, lines),
        }
        _copy_optional_element_metadata(item, metadata)
        tables.append(item)

    formula_descriptions = structured.get("formula_descriptions") or {}
    formula_metadata = structured.get("formula_metadata") or {}
    formulas = []
    for formula in structured.get("formulas") or []:
        latex = str(formula or "").strip()
        if not latex:
            continue
        metadata = formula_metadata.get(latex) if isinstance(formula_metadata, dict) else None
        metadata = metadata if isinstance(metadata, dict) else {}
        context = str(metadata.get("context") or "").strip() or _context_for_formula(latex, lines)
        semantic_summary = str(formula_descriptions.get(latex) or "").strip() or _formula_summary(
            context,
            description_language,
        )
        item = {
            "source": formula_source,
            "latex": latex,
            "semantic_summary": semantic_summary,
            "variables": str(metadata.get("variables") or "").strip() or _extract_formula_variables_context(lines),
            "context": context,
        }
        _copy_optional_element_metadata(item, metadata)
        formulas.append(item)

    figure_metadata = structured.get("figure_metadata") or {}
    figures = []
    for figure in structured.get("figures") or []:
        desc = str(figure or "").strip()
        if not desc:
            continue
        metadata = figure_metadata.get(desc) if isinstance(figure_metadata, dict) else None
        metadata = metadata if isinstance(metadata, dict) else {}
        item = {
            "source": "vlm_ocr",
            "type": str(metadata.get("type") or "").strip() or _guess_figure_type(desc),
            "caption": str(metadata.get("caption") or "").strip() or _figure_caption(desc),
            "description": desc,
            "labels": metadata.get("labels") if isinstance(metadata.get("labels"), list) else _extract_figure_labels(desc),
            "semantic_summary": desc,
            "context": str(metadata.get("context") or "").strip() or _nearby_figure_context(desc, lines),
        }
        _copy_optional_element_metadata(item, metadata)
        figures.append(item)
    return {"tables": tables, "formulas": formulas, "figures": figures}


def _build_layout_output_elements(
    markdown: str,
    payloads: Dict[str, Any],
    route_selected: str,
    description_language: str = "unknown",
) -> Dict[str, Any]:
    output: Dict[str, list[Dict[str, Any]]] = {"tables": [], "formulas": [], "figures": []}
    for collection in ("tables", "formulas", "figures"):
        values = payloads.get(collection)
        if not isinstance(values, list):
            continue
        for payload in values:
            if not isinstance(payload, dict):
                continue
            normalized = _normalize_structured({collection: [payload]})
            built = _build_output_elements(
                markdown,
                normalized,
                route_selected,
                description_language,
            ).get(collection) or []
            if not built:
                continue
            item = built[0]
            if payload.get("source"):
                item["source"] = payload["source"]
            output[collection].append(item)
    return output


def _copy_optional_element_metadata(item: Dict[str, Any], metadata: Dict[str, Any]) -> None:
    bbox = metadata.get("bbox")
    if isinstance(bbox, list) and len(bbox) == 4:
        item["bbox"] = bbox
    confidence = metadata.get("confidence")
    if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
        item["confidence"] = confidence
    status = str(metadata.get("status") or "").strip()
    if status:
        item["status"] = status
    bbox_space = str(metadata.get("bbox_space") or "").strip()
    if bbox_space:
        item["bbox_space"] = bbox_space
    for key in (
        "layout_id",
        "reading_order",
        "columns",
        "normalized_rows",
        "source_cells",
        "cell_status",
        "source_cell_row_offset",
        "source_block_index",
    ):
        value = metadata.get(key)
        if value is not None:
            item[key] = value


def _semantic_status(
    route_selected: str,
    metrics: Dict[str, Any],
    structured: Dict[str, Any],
    rc: Dict[str, Any],
    fallback_reason: Optional[str],
) -> Dict[str, Any]:
    missing = []
    reason = ""
    if metrics.get("needs_formula_latex") and not structured.get("formulas"):
        missing.append("formula_latex")
        if not rc.get("vlm_ocr_enabled") or not metrics.get("vlm_ocr_available"):
            reason = "vlm_ocr_disabled"
        else:
            reason = fallback_reason or "formula_extraction_unavailable"
    if metrics.get("needs_table_structure") and not structured.get("tables"):
        missing.append("table_structure")
        if not reason:
            if not rc.get("vlm_ocr_enabled") or not metrics.get("vlm_ocr_available"):
                reason = "vlm_ocr_disabled"
            else:
                reason = fallback_reason or "table_extraction_unavailable"
    if (
        rc.get("figure_semantic_description_required")
        and metrics.get("has_meaningful_figures")
        and not structured.get("figures")
    ):
        missing.append("figure_description")
        if not reason:
            if not rc.get("vlm_ocr_enabled") or not metrics.get("vlm_ocr_available"):
                reason = "vlm_ocr_disabled"
            else:
                reason = fallback_reason or "figure_description_unavailable"
    if route_selected == "blank":
        return {"complete": True, "missing": [], "reason": ""}
    return {"complete": not missing, "missing": missing, "reason": reason}


def _title_for_table(table_text: str, lines: list[str]) -> str:
    if table_text.startswith("[TABLE_PLACEHOLDER]"):
        m = re.match(r"^\[TABLE_PLACEHOLDER\]\s*([^：:]+)", table_text)
        if m:
            return m.group(1).strip()
    titles = []
    for line in lines:
        t = line.strip()
        if re.match(r"^(?:表\s*[A-Za-z0-9０-９]|Table\s+[A-Za-z0-9])", t, flags=re.IGNORECASE):
            titles.append(t[:80])
    return titles[0] if len(set(titles)) == 1 else ""


def _table_summary(title: str, table_text: str, description_language: str = "unknown") -> str:
    cols, rows = _table_shape(table_text)
    headers = _header_tokens(table_text)
    if title:
        return title
    if not _uses_chinese_description(description_language):
        if headers:
            return f"Table: contains {rows} rows and {cols} columns; fields include {', '.join(headers[:6])}."
        return f"Table: contains {rows} rows and {cols} columns."
    if headers:
        return f"表格：包含 {rows} 行、{cols} 列，字段包括 {'、'.join(headers[:6])}。"
    return f"表格：包含 {rows} 行、{cols} 列。"


def _context_for_anchor(anchor: str, lines: list[str]) -> str:
    if not anchor:
        return ""
    for idx, line in enumerate(lines):
        if anchor in line:
            return _nearby_context(lines, idx)
    return ""


def _context_for_formula(latex: str, lines: list[str]) -> str:
    _ = latex
    for idx, line in enumerate(lines):
        if "式中" in line:
            return _nearby_context(lines, idx) or line.strip()
    for idx, line in enumerate(lines):
        if re.search(r"按.*式|计算|公式", line):
            return _nearby_context(lines, idx) or line.strip()
    return ""


def _formula_summary(context: str, description_language: str = "unknown") -> str:
    ctx = (context or "").strip()
    if ctx:
        return ctx[:160]
    if _uses_chinese_description(description_language):
        return "公式：变量说明见原文。"
    return "Formula: see the source document for variable definitions."


def _uses_chinese_description(description_language: str) -> bool:
    return str(description_language or "").strip().lower() in {
        "zh",
        "zh-cn",
        "zh_hans",
        "chinese",
    }


def _extract_formula_variables_context(lines: list[str]) -> str:
    for idx, line in enumerate(lines):
        if "式中" not in line:
            continue
        block = [line.strip()]
        for nxt in lines[idx + 1 : idx + 5]:
            t = nxt.strip()
            if not t:
                break
            block.append(t)
        return "\n".join(block)
    return ""


def _guess_figure_type(text: str) -> str:
    low = (text or "").lower()
    if "schematic" in low or "示意" in text:
        return "schematic"
    if "chart" in low or "curve" in low or "图表" in text:
        return "chart"
    if "diagram" in low or "cross-section" in low or "剖面" in text:
        return "diagram"
    if text:
        return "figure"
    return "unknown"


def _figure_caption(text: str) -> str:
    m = re.search(r"(图\s*\d+(?:[.-]\d+)?[^，。;\n]*)", text)
    return m.group(1).strip() if m else ""


def _extract_figure_labels(text: str) -> list[str]:
    labels = re.findall(r"\b[A-Z][A-Za-z0-9_./-]{0,12}\b", text or "")
    labels.extend(re.findall(r"[A-Za-z]\s*[≥≤=]\s*[\d.]+[A-Za-z]*", text or ""))
    return _unique_keep_order([x.strip() for x in labels])[:12]


def _nearby_figure_context(desc: str, lines: list[str]) -> str:
    caption = _figure_caption(desc)
    if caption:
        return _context_for_anchor(caption, lines)
    return ""


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
    table_metadata: Dict[str, Dict[str, Any]] = {}
    tables: list[str] = []
    for item in _structured_list(raw, "tables"):
        table_value = _structured_value(item, "markdown", "table_markdown", "data")
        normalized_tables = _normalize_table_candidates([table_value])
        tables.extend(normalized_tables)
        if not normalized_tables:
            continue
        metadata = _structured_metadata(
            item,
            title=("title", "table_title", "tableName", "table_name"),
            description=("description", "semanticDesc", "semantic_summary", "summary"),
            context=("context", "surrounding_text"),
        )
        for key in (
            "columns",
            "normalized_rows",
            "source_cells",
            "cell_status",
            "source_cell_row_offset",
            "source_block_index",
        ):
            value = item.get(key) if isinstance(item, dict) else None
            if value is not None:
                metadata[key] = value
        if metadata:
            for table in normalized_tables:
                table_metadata[table] = metadata
    tables = _unique_keep_order(tables)

    formula_descriptions: Dict[str, str] = {}
    formula_metadata: Dict[str, Dict[str, Any]] = {}
    formula_values: list[str] = []
    for item in _structured_list(raw, "formulas"):
        latex = str(_structured_value(item, "latex", "formula", "text") or "").strip()
        if not latex:
            continue
        formula_values.append(latex)
        metadata = _structured_metadata(
            item,
            variables=("variables",),
            context=("context", "surrounding_text"),
        )
        if metadata:
            formula_metadata[latex] = metadata
        description = _first_text(
            item if isinstance(item, dict) else {},
            "description",
            "semanticDesc",
            "semantic_summary",
            "summary",
        )
        if description:
            formula_descriptions[latex] = description
    formulas = _filter_formula_candidates(formula_values, tables)

    figure_metadata: Dict[str, Dict[str, Any]] = {}
    figures: list[str] = []
    for item in _structured_list(raw, "figures"):
        item_dict = item if isinstance(item, dict) else {}
        description = _first_text(item_dict, "description", "semanticDesc", "semantic_summary", "summary")
        caption = _first_text(item_dict, "caption", "capture", "figureName", "name", "title")
        figure = description or caption or (str(item or "").strip() if not isinstance(item, dict) else "")
        if not figure or _is_noise_figure_line(f"[FIGURE: {figure}]"):
            continue
        figures.append(figure)
        metadata = _structured_metadata(
            item,
            caption=("caption", "capture", "figureName", "name", "title"),
            type=("type",),
            context=("context", "surrounding_text"),
        )
        labels = item_dict.get("labels")
        if isinstance(labels, list):
            metadata["labels"] = [str(label).strip() for label in labels if str(label).strip()]
        if metadata:
            figure_metadata[figure] = metadata
    figures = _unique_keep_order(figures)

    raw_descriptions = raw.get("formula_descriptions")
    if isinstance(raw_descriptions, dict):
        formula_descriptions.update(
            {
                str(latex).strip(): str(description).strip()
                for latex, description in raw_descriptions.items()
                if str(latex).strip() in formulas and str(description).strip()
            }
        )

    normalized = {
        "formulas": formulas,
        "tables": tables,
        "figures": figures,
    }
    if formula_descriptions:
        normalized["formula_descriptions"] = {
            latex: formula_descriptions[latex]
            for latex in formulas
            if latex in formula_descriptions
        }
    if formula_metadata:
        normalized["formula_metadata"] = {
            latex: formula_metadata[latex]
            for latex in formulas
            if latex in formula_metadata
        }
    if table_metadata:
        normalized["table_metadata"] = {
            table: table_metadata[table]
            for table in tables
            if table in table_metadata
        }
    if figure_metadata:
        normalized["figure_metadata"] = {
            figure: figure_metadata[figure]
            for figure in figures
            if figure in figure_metadata
        }
    return normalized


def _structured_list(raw: Dict[str, Any], name: str) -> list[Any]:
    value = raw.get(name)
    return value if isinstance(value, list) else []


def _structured_value(item: Any, *keys: str) -> Any:
    if not isinstance(item, dict):
        return item
    for key in keys:
        value = item.get(key)
        if value:
            return value
    if any(item.get(key) for key in ("header", "columns", "rows", "raw_array", "normalized_rows")):
        return item
    return ""


def _structured_metadata(item: Any, **text_fields: tuple[str, ...]) -> Dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    metadata: Dict[str, Any] = {}
    for output_name, keys in text_fields.items():
        value = _first_text(item, *keys)
        if value:
            metadata[output_name] = value
    bbox = item.get("bbox")
    if isinstance(bbox, list) and len(bbox) == 4:
        metadata["bbox"] = bbox
    bbox_space = _first_text(item, "bbox_space")
    if bbox_space:
        metadata["bbox_space"] = bbox_space
    confidence = item.get("confidence")
    if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
        metadata["confidence"] = confidence
    status = _first_text(item, "status")
    if status:
        metadata["status"] = status
    source_block_index = item.get("source_block_index", item.get("block_index"))
    if isinstance(source_block_index, int) and not isinstance(source_block_index, bool):
        metadata["source_block_index"] = source_block_index
    layout_id = item.get("layout_id")
    if isinstance(layout_id, str) and layout_id.strip():
        metadata["layout_id"] = layout_id.strip()
    reading_order = item.get("reading_order")
    if isinstance(reading_order, int) and not isinstance(reading_order, bool):
        metadata["reading_order"] = reading_order
    return metadata


def _first_text(item: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _structured_from_ocr_result(result: OcrResult, include_figures: bool) -> Dict[str, Any]:
    tables = [_ocr_element_payload(item, "table") for item in result.tables if (item.markdown or item.text)]
    formulas = [_ocr_element_payload(item, "formula") for item in result.formulas if (item.latex or item.text)]
    figures = (
        [_ocr_element_payload(item, "figure") for item in result.figures if (item.description or item.caption or item.text)]
        if include_figures
        else []
    )
    return _normalize_structured({"tables": tables, "formulas": formulas, "figures": figures})


def _ocr_element_payload(item: Any, kind: str) -> Dict[str, Any]:
    raw = item.raw if isinstance(item.raw, dict) else {}
    if kind == "table":
        payload = {
            "markdown": item.markdown or item.text,
            "title": item.title,
            "description": item.description,
            "context": item.context,
        }
    elif kind == "formula":
        payload = {
            "latex": item.latex or item.text,
            "description": item.description,
            "variables": raw.get("variables"),
            "context": item.context,
        }
    else:
        payload = {
            "caption": item.caption,
            "description": item.description or item.caption or item.text,
            "type": raw.get("type"),
            "labels": raw.get("labels"),
            "context": item.context,
        }
    passthrough_keys = ["bbox", "bbox_space", "confidence", "status", "block_index", "source_block_index"]
    if kind == "table":
        passthrough_keys.extend(
            [
                "columns",
                "normalized_rows",
                "source_cells",
                "cell_status",
                "source_cell_row_offset",
                "source_block_index",
            ]
        )
    for key in passthrough_keys:
        if raw.get(key) is not None:
            payload[key] = raw[key]
    return payload


def _structured_insufficient_for_route(structured: Dict[str, Any], route_selected: str, metrics: Dict[str, Any]) -> bool:
    if route_selected in {"hybrid_glm_ocr", "full_glm_ocr"}:
        if metrics.get("needs_formula_latex") and not structured.get("formulas"):
            return True
        if metrics.get("needs_table_structure") and not structured.get("tables"):
            return True
    return False


def _glm_ocr_markdown_bad(markdown: str) -> bool:
    text = str(markdown or "")
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return True
    if re.search(r"\(cid:\d+\)|[\uE000-\uF8FF\uFFFD�]", text, flags=re.IGNORECASE):
        return True
    if re.search(r"[?]{4,}", compact):
        return True
    symbol_ratio = len(re.findall(r"[!-/:-@\\[-`{-~]", compact)) / max(len(compact), 1)
    return symbol_ratio >= 0.75 and not re.search(r"[A-Za-z0-9\u3400-\u4dbf\u4e00-\u9fff]", compact)


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

    description_language = str(rc.get("description_language") or "unknown")
    use_chinese = _uses_chinese_description(description_language)
    markdown, latex_placeholders = _replace_latex_tabular_with_placeholders(
        markdown,
        page_no,
        description_language,
    )
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
            anchor = f"未命名表{unnamed_idx}" if use_chinese else f"Untitled table {unnamed_idx}"
        semantic_desc = _build_table_semantic_desc(anchor, block, lines, start, description_language)
        if use_chinese:
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
        else:
            placeholder = (
                f"[TABLE_PLACEHOLDER] {anchor} (page: {page_no}): {semantic_desc} "
                f"(approximately {row_count} rows x {col_count} columns); "
                "refer to this page in the source PDF for key values."
            )
            block_md = (
                f"### {anchor} (page: {page_no})\n"
                "This large or wide table has been omitted; only a semantic placeholder is retained.\n"
                f"Semantic description: {semantic_desc}\n"
                f"The table has approximately {row_count} rows x {col_count} columns; "
                "refer to this page in the source PDF for key values.\n"
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


def _replace_latex_tabular_with_placeholders(
    markdown: str,
    page_no: int,
    description_language: str = "unknown",
) -> tuple[str, list[str]]:
    lines = (markdown or "").splitlines()
    if not lines:
        return markdown, []
    replacements: list[tuple[int, int, str]] = []
    placeholders: list[str] = []
    i = 0
    unnamed = 0
    use_chinese = _uses_chinese_description(description_language)
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
            anchor = f"未命名表{unnamed}" if use_chinese else f"Untitled table {unnamed}"
        semantic_desc = _build_table_semantic_desc(anchor, block, lines, start, description_language)
        rows = max(1, row_count)
        cols = max(1, col_count)
        if use_chinese:
            placeholder = (
                f"[TABLE_PLACEHOLDER] {anchor}（页号: {page_no}）："
                f"{semantic_desc}（检测到LaTeX表格块，约{rows}行×{cols}列）；关键数值请回看原PDF本页。"
            )
            repl = (
                f"### {anchor}（页号: {page_no}）\n"
                "该表为大表/横向表（LaTeX表格块），已省略表体，仅保留语义占位。\n"
                f"语义说明：{semantic_desc}\n"
                f"字段维度约为 {rows} 行 × {cols} 列，关键数值请回看原PDF本页。\n"
                f"{placeholder}"
            )
        else:
            placeholder = (
                f"[TABLE_PLACEHOLDER] {anchor} (page: {page_no}): {semantic_desc} "
                f"(LaTeX table block detected, approximately {rows} rows x {cols} columns); "
                "refer to this page in the source PDF for key values."
            )
            repl = (
                f"### {anchor} (page: {page_no})\n"
                "This large or wide LaTeX table has been omitted; only a semantic placeholder is retained.\n"
                f"Semantic description: {semantic_desc}\n"
                f"The table has approximately {rows} rows x {cols} columns; "
                "refer to this page in the source PDF for key values.\n"
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


def _build_table_semantic_desc(
    anchor: str,
    table_block: str,
    lines: list[str],
    table_start: int,
    description_language: str = "unknown",
) -> str:
    a = (anchor or "").strip()
    ctx = _nearby_context(lines, table_start)
    sig = f"{a}\n{ctx}\n{table_block[:800]}"
    use_chinese = _uses_chinese_description(description_language)
    if re.search(r"许用应力|allowable stress|应力", sig, flags=re.IGNORECASE):
        base = (
            "该表用于给出材料在不同工况下的许用应力对照"
            if use_chinese
            else "This table compares allowable material stresses under different conditions"
        )
    elif re.search(r"成分|化学|composition", sig, flags=re.IGNORECASE):
        base = (
            "该表用于给出材料化学成分及限值对照"
            if use_chinese
            else "This table compares material chemical compositions and limits"
        )
    elif re.search(
        r"尺寸|公差|厚度|直径|dimension|tolerance|thickness|diameter",
        sig,
        flags=re.IGNORECASE,
    ):
        base = (
            "该表用于给出尺寸范围与对应参数对照"
            if use_chinese
            else "This table compares dimensional ranges and corresponding parameters"
        )
    else:
        base = (
            "该表用于给出多维条件下的参数对照"
            if use_chinese
            else "This table compares parameters across multiple conditions"
        )

    dims = []
    if re.search(r"温度|temperature|℃", sig, flags=re.IGNORECASE):
        dims.append("温度" if use_chinese else "temperature")
    if re.search(r"厚度|thickness|mm", sig, flags=re.IGNORECASE):
        dims.append("厚度" if use_chinese else "thickness")
    if re.search(r"牌号|数字代号|material|grade", sig, flags=re.IGNORECASE):
        dims.append("材料牌号" if use_chinese else "material grade")
    if re.search(r"标准|GB/?T|ASME|ASTM", sig, flags=re.IGNORECASE):
        dims.append("材料标准" if use_chinese else "material standard")
    if re.search(r"Rm|ReL|Rp0\\.2|强度", sig, flags=re.IGNORECASE):
        dims.append("强度指标" if use_chinese else "strength properties")

    head_tokens = _header_tokens(table_block)
    if head_tokens:
        dims.extend([t for t in head_tokens if t not in dims])
    dims = [_normalize_dim_token(x) for x in dims]
    dims = _unique_keep_order([x for x in dims if x])[:6]
    if dims:
        usage = _build_table_usage_hint(dims, description_language)
        if use_chinese:
            return f"{base}，主要维度包括：{'、'.join(dims)}。{usage}"
        return f"{base}. Primary dimensions include {', '.join(dims)}. {usage}"
    if use_chinese:
        return f"{base}。可结合表题与页号回查原文获取完整数值。"
    return f"{base}. Refer to the table title and page number for complete values."


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


def _build_table_usage_hint(dims: list[str], description_language: str = "unknown") -> str:
    d = [x for x in (dims or []) if x]
    if not _uses_chinese_description(description_language):
        if not d:
            return "Refer to the table title and page number for complete values."
        if "temperature" in d and "thickness" in d:
            return (
                "Locate the target cell by temperature and thickness, then read the parameter "
                "for the relevant material grade or standard."
            )
        if "material grade" in d and "material standard" in d:
            return (
                "Filter by material grade and material standard, then use the remaining "
                "dimensions to find the target parameter."
            )
        return (
            f"Use {', '.join(d[:3])} to locate the target parameter, then verify details "
            "in the source PDF."
        )
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
