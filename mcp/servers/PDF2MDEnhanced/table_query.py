"""Opt-in, source-bound query projections. Never mutate the supplied table."""
from __future__ import annotations

from .model_errors import raise_model_error

from copy import deepcopy
from decimal import Decimal
import base64
import html
import hashlib
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
import re

from .thinking_policy import thinking_capabilities
from .vlm_client import valid_router_thinking

IDENTITY = ("tenant_id", "doc_id", "version", "table_id", "table_pk")
NUMBER = r"-?\d+(?:\.\d+)?"
REASONS = {
    "calculation_sheet_not_data_table", "table_type_requires_review",
    "unknown_table_identity", "request_id_required", "source_html_required", "content_hash_mismatch",
    "revision_or_page_mismatch", "single_table_required", "input_budget_exceeded",
    "table_structure_unavailable", "overlapping_source_cells", "invalid_annotation",
    "invalid_model_budget", "invalid_query_strategy", "model_initialization_failed", "identity_or_hash_mismatch", "invalid_source_reference", "content_conflict",
    "model_response_truncated", "invalid_projection", "invalid_section_key", "invalid_field",
    "footer_requires_review", "embedded_image_requires_asset",
    "body_spanning_cells", "conditional_source_requires_review", "ragged_table_rows",
    "ambiguous_header", "incomplete_record", "empty_section", "invalid_unresolved",
    "invalid_source_assertion", "missing_previous_context", "unsupported_condition", "unmapped_source_cells",
}


def scalar(raw):
    """Preserve strings (including leading zeroes); parse only unambiguous numbers."""
    result = {"raw_text": raw, "value": raw if raw else None, "kind": "text" if raw else "blank"}
    text = raw.strip()
    if re.fullmatch(NUMBER + r"[%％]?", text) and not re.match(r"-?0\d", text):
        result.update(kind="percent" if text.endswith(("%", "％")) else "number",
                      number=str(Decimal(text.rstrip("%％"))))
    elif re.fullmatch(r"-?\d+ \d+/[1-9]\d*", text):
        whole, fraction = text.split()
        numerator, denominator = fraction.split("/")
        result.update(kind="fraction", whole=whole, numerator=numerator, denominator=denominator)
    interval = parse_interval(text)
    if interval:
        result.update(kind="interval", interval=interval)
    return result


def parse_interval(text):
    # Only explicit comparisons carry reliable inclusion semantics. A~B is ambiguous.
    text = text.strip().strip("$").replace("＞", ">").replace("＜", "<")
    for command, symbol in ((r"\geqslant", "≥"), (r"\leqslant", "≤"),
                            (r"\geq", "≥"), (r"\leq", "≤"), (r"\ge", "≥"), (r"\le", "≤")):
        text = text.replace(command, symbol)
    text = re.sub(r"\\(?:mathrm|text)\{([A-Za-z_][A-Za-z_0-9]*)\}", r"\1", text)
    text = re.sub(r"\s+", "", text).replace("<=", "≤").replace(">=", "≥")
    variable = r"[A-Za-z_][A-Za-z_0-9]*"
    match = re.fullmatch(f"({NUMBER})([<≤>≥])({variable})([<≤>≥])({NUMBER})", text)
    if match:
        a, op1, var, op2, b = match.groups()
        comparisons = [(op1.translate(str.maketrans("<≤>≥", ">≥<≤")), a), (op2, b)]
    else:
        match = re.fullmatch(f"({variable})?([<≤>≥])({NUMBER})", text)
        if not match:
            reversed_match = re.fullmatch(f"({NUMBER})([<≤>≥])({variable})", text)
            if not reversed_match:
                return None
            number, op, var = reversed_match.groups()
            op = op.translate(str.maketrans("<≤>≥", ">≥<≤"))
        else:
            var, op, number = match.groups()
        comparisons = [(op, number)]
    result = {"variable": var, "lower": None, "upper": None,
              "lower_inclusive": False, "upper_inclusive": False}
    for op, number in comparisons:
        side = "lower" if op in (">", "≥") else "upper"
        if result[side] is not None:
            return None
        result[side] = str(Decimal(number))
        result[side + "_inclusive"] = op in ("≥", "≤")
    if result["lower"] is not None and result["upper"] is not None:
        if Decimal(result["lower"]) >= Decimal(result["upper"]):
            return None
    return result


def interval_contains(interval, value):
    value = Decimal(str(value))
    if not value.is_finite():
        return False
    for side, greater in (("lower", True), ("upper", False)):
        bound = interval[side]
        if bound is None:
            continue
        bound = Decimal(bound)
        if value == bound and not interval[side + "_inclusive"]:
            return False
        if (greater and value < bound) or (not greater and value > bound):
            return False
    return True


def _issue(code, sources=None):
    return {"reason": code, "sources": sources or []}


def _object_image_args(request):
    """Accept an explicitly supplied single-object image without opening arbitrary files."""
    path = request.get("object_image_path")
    encoded = request.get("object_image_data")
    if path and encoded:
        raise ValueError("invalid_source_reference")
    if path:
        return {"image_path": path}
    if not encoded:
        return {}
    if not isinstance(encoded, str) or len(encoded) > 14_000_000:
        raise ValueError("input_budget_exceeded")
    declared_mime = None
    if encoded.startswith("data:"):
        header, sep, encoded = encoded.partition(",")
        match = re.fullmatch(r"data:(image/(?:png|jpeg|jpg));base64", header, re.IGNORECASE)
        if not sep or not match:
            raise ValueError("invalid_source_reference")
        declared_mime = match.group(1).lower().replace("jpg", "jpeg")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        raise ValueError("invalid_source_reference")
    actual_mime = "image/png" if data.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg" if data.startswith(b"\xff\xd8\xff") else None
    if not actual_mime or (declared_mime and declared_mime != actual_mime):
        raise ValueError("invalid_source_reference")
    if len(data) > 10 * 1024 * 1024:
        raise ValueError("input_budget_exceeded")
    try:
        import fitz
        image = fitz.Pixmap(data)
        if image.width <= 0 or image.height <= 0 or image.width * image.height > 20_000_000:
            raise ValueError("input_budget_exceeded")
    except ValueError:
        raise
    except Exception as exc:
        raise_model_error(exc)
        raise ValueError("invalid_source_reference")
    handle = tempfile.NamedTemporaryFile(prefix="pdf2md_table_crop_", suffix=".png" if actual_mime == "image/png" else ".jpg", delete=False)
    try:
        handle.write(data)
        handle.close()
    except Exception as exc:
        raise_model_error(exc)
        handle.close()
        Path(handle.name).unlink(missing_ok=True)
        raise
    return {"image_path": handle.name, "_owned_image_path": handle.name}


def _sources(markup, parse_grid):
    if len(re.findall(r"(?i)<table\b", markup)) != 1 or len(re.findall(r"(?i)</table\s*>", markup)) != 1:
        raise ValueError("single_table_required")
    if len(markup) > 200000 or len(re.findall(r"(?i)<t[dh]\b", markup)) > 2000:
        raise ValueError("input_budget_exceeded")
    if any(int(n) > 100 for n in re.findall(r'(?i)(?:rowspan|colspan)\s*=\s*[\"\']?(\d+)', markup)):
        raise ValueError("input_budget_exceeded")
    grid, meta = parse_grid(markup)
    if not grid or not meta.get("source_cells") or "rowspan_exceeds_observed_rows" in meta.get("warnings", []):
        raise ValueError("table_structure_unavailable")
    sources, positions = {}, {}
    mapped = {(item["row"], item["col"]): (item.get("source_row", item["row"]), item.get("source_col", item["col"]))
              for item in meta["cell_status"]}
    for cell in meta["source_cells"]:
        ref = f"r{cell['row']}c{cell['col']}"
        sources[ref] = deepcopy(cell)
        for r in range(cell["row"], cell["row"] + cell["rowspan"]):
            for c in range(cell["col"], cell["col"] + cell["colspan"]):
                position = f"r{r}c{c}"
                if position in positions or mapped.get((r, c)) != (cell["row"], cell["col"]):
                    raise ValueError("overlapping_source_cells")
                positions[position] = ref
    if len(meta["source_cells"]) != len(re.findall(r"(?i)<t[dh]\b", markup)):
        raise ValueError("table_structure_unavailable")
    for index, match in enumerate(re.finditer(r"(?is)<caption\b[^>]*>(.*?)</caption>", markup)):
        ref = f"caption{index}"
        sources[ref] = {"text": html.unescape(re.sub(r"(?is)<[^>]+>", " ", match.group(1))).strip(), "kind": "caption"}
        positions[ref] = ref
    for index, text in enumerate(meta.get("source_annotations", [])):
        ref = f"note{index}"
        sources[ref] = {"text": text, "kind": "note"}
        positions[ref] = ref
    return sources, positions, meta


def _automatic(markup, sources, positions, binding):
    if re.search(r"(?i)<tfoot\b", markup):
        return None
    if any(re.search(r"(?i)\b(if|except|unless|only|note|see|interpolat\w*)\b|仅|除外|条件|插值|注[:：]|续表", cell["text"])
           for cell in sources.values()):
        return None
    captions = [ref for ref, cell in sources.items() if cell.get("kind") == "caption"]
    sources = {ref: cell for ref, cell in sources.items() if "row" in cell}
    rows = range(max(cell["row"] + cell["rowspan"] for cell in sources.values()))
    headers = []
    for r in rows:
        cells = [cell for cell in sources.values() if cell["row"] == r]
        if cells and all(cell.get("html_tag") == "th" or cell.get("row_group") == "thead" for cell in cells):
            headers.append(r)
        else:
            break
    if not headers or len(headers) == len(rows):
        return None
    width = max(cell["col"] + cell["colspan"] for cell in sources.values())
    fields = []
    for c in range(width):
        path = list(dict.fromkeys(positions.get(f"r{r}c{c}") for r in headers))
        if None in path or not any(sources[ref]["text"] for ref in path):
            return None
        fields.append({"key": f"c{c}", "header_path": path})
    records = []
    for r in range(len(headers), len(rows)):
        refs = [f"r{r}c{c}" for c in range(width)]
        if any(ref not in positions for ref in refs):
            return None
        # A spanning body cell can be a section heading or footnote, not a record.
        if any(sources[positions[ref]]["colspan"] > 1 for ref in refs):
            return None
        records.append({"values": {f"c{c}": ref for c, ref in enumerate(refs)}})
    return {"binding": binding, "lookup_sections": [{"key": "section_1", "fields": fields,
             "records": records, "title_sources": captions}], "unresolved": []}


def validate_proposal(proposal, binding, sources, positions):
    """Model supplies bindings only. All exported values are read from source cells."""
    if not isinstance(proposal, dict) or proposal.get("binding") != binding:
        raise ValueError("identity_or_hash_mismatch")
    used, sections, unresolved = set(), [], []

    covered = {ref: set() for ref in sources}

    def bind(ref):
        start, end = None, None
        if isinstance(ref, dict):
            if set(ref) != {"source", "start", "end"}:
                raise ValueError("invalid_source_reference")
            start, end, ref = ref["start"], ref["end"], ref["source"]
        if not isinstance(ref, str) or ref not in positions:
            raise ValueError("invalid_source_reference")
        origin = positions[ref]
        cell = sources[origin]
        if start is None and end is None:
            start, end = 0, len(cell["text"])
        elif type(start) is not int or type(end) is not int or not 0 <= start < end <= len(cell["text"]):
            raise ValueError("invalid_source_reference")
        token = lambda char: char.isalnum() or char in "._-/"
        if (start and start < len(cell["text"]) and token(cell["text"][start - 1]) and token(cell["text"][start])) or (
                end and end < len(cell["text"]) and token(cell["text"][end - 1]) and token(cell["text"][end])):
            raise ValueError("invalid_source_reference")
        covered[origin].update(range(start, end))
        used.add(origin)
        return {**scalar(cell["text"][start:end]), "source": origin, "position": ref,
                "start": start, "end": end, "binding_id": f"{origin}:{start}:{end}",
                "status": "merged_fill" if ref != origin else ("blank_in_source" if not cell["text"] else "source"),
                **{key: deepcopy(cell[key]) for key in ("bbox", "bbox_space") if key in cell}}

    def bindings(refs):
        if not isinstance(refs, list):
            raise ValueError("invalid_source_reference")
        return [bind(ref) for ref in refs]

    raw_sections = proposal.get("lookup_sections")
    if not isinstance(raw_sections, list):
        raise ValueError("invalid_projection")
    keys = set()
    for section in raw_sections:
        if not isinstance(section, dict) or set(section) - {"key", "fields", "records", "title_sources"}:
            raise ValueError("invalid_projection")
        key = section.get("key")
        if not isinstance(key, str) or not key or key in keys:
            raise ValueError("invalid_section_key")
        keys.add(key)
        fields, field_keys = [], set()
        for field in section.get("fields", []):
            if not isinstance(field, dict) or set(field) - {"key", "header_path", "unit_sources"}:
                raise ValueError("invalid_field")
            name = field.get("key")
            if not isinstance(name, str) or not name or name in field_keys:
                raise ValueError("invalid_field")
            field_keys.add(name)
            path = bindings(field.get("header_path"))
            if not path or not any(part["raw_text"] for part in path):
                raise ValueError("ambiguous_header")
            fields.append({"key": name, "header_path": path,
                           "units": bindings(field.get("unit_sources", []))})
        records = []
        for record in section.get("records", []):
            if not isinstance(record, dict) or set(record) - {"values", "conditions", "groups"}:
                raise ValueError("content_conflict")
            if isinstance(record.get("values"), list):
                values = record["values"]
                if len(values) != len(fields):
                    raise ValueError("incomplete_record")
                record = {**record, "values": {field["key"]: ref for field, ref in zip(fields, values)}}
            if not isinstance(record.get("values"), dict) or set(record["values"]) != field_keys:
                raise ValueError("incomplete_record")
            records.append({"values": {name: bind(ref) for name, ref in record["values"].items()},
                            "conditions": bindings(record.get("conditions", [])),
                            "groups": bindings(record.get("groups", []))})
        if not fields or not records:
            raise ValueError("empty_section")
        title = bindings(section.get("title_sources", []))
        sections.append({"key": key, "title": " / ".join(part["raw_text"] for part in title) or key,
                         "fields": fields, "records": records,
                         "columns": [field["key"] for field in fields],
                         "rows": [[record["values"][field["key"]]["raw_text"] for field in fields] for record in records],
                         "title_sources": title})
    for item in proposal.get("unresolved", []):
        if not isinstance(item, dict) or item.get("reason") not in REASONS:
            raise ValueError("invalid_unresolved")
        refs = item.get("sources", [])
        bindings(refs)
        unresolved.append(_issue(item["reason"], refs))
    missing = sorted(ref for ref, cell in sources.items() if ref not in used or
                     any(i not in covered[ref] for i, char in enumerate(cell["text"]) if not char.isspace()))
    if missing:
        unresolved.append(_issue("unmapped_source_cells", missing))
    return sections, unresolved, used - set(missing)


def enhance_table(request, parse_grid, vlm_factory, vlm_config=None, description_language="unknown"):
    request = deepcopy(request)
    if not isinstance(request, dict):
        request = {}
    table = request.get("table", {})
    result = {"table": table, "query_enhancement": {"contract_version": "1", "lookup_status": "unavailable",
              "lookup_sections": [], "degraded": True, "manualReviewRequired": True,
              "unresolved": [], "model_calls": 0, "diagnostics": []}}
    out = result["query_enhancement"]
    stage = "source_validation"
    try:
        target = request.get("target")
        if not isinstance(table, dict) or not isinstance(target, dict):
            raise ValueError("unknown_table_identity")
        if any(not target.get(k) or target.get(k) != table.get(k) for k in IDENTITY):
            raise ValueError("unknown_table_identity")
        if not request.get("request_id"):
            raise ValueError("request_id_required")
        markup = table.get("render_html")
        if not isinstance(markup, str) or not markup:
            raise ValueError("source_html_required")
        digest = hashlib.sha256(markup.encode("utf-8")).hexdigest()
        out["source_html_sha256"] = digest
        if request.get("source_html_sha256") != digest:
            raise ValueError("content_hash_mismatch")
        binding = {**{k: target[k] for k in IDENTITY}, "request_id": request["request_id"], "source_html_sha256": digest}
        for key in ("page_no", "override_revision"):
            if key in table:
                if target.get(key) != table[key]:
                    raise ValueError("revision_or_page_mismatch")
                binding[key] = table[key]
        out["binding"] = binding
        if table.get("table_kind") == "calculation_sheet":
            raise ValueError("calculation_sheet_not_data_table")
        if table.get("table_kind", "data_table") != "data_table":
            raise ValueError("table_type_requires_review")
        sources, positions, meta = _sources(markup, parse_grid)
        for cell in table.get("source_cells", []):
            ref = f"r{cell.get('row')}c{cell.get('col')}"
            if ref in sources and cell.get("text") == sources[ref]["text"]:
                for key in ("bbox", "bbox_space"):
                    if key in cell:
                        sources[ref][key] = deepcopy(cell[key])
        # Explicit annotations are object-bound input; never read page or adjacent objects.
        for index, annotation in enumerate(request.get("annotations", [])):
            if not isinstance(annotation, dict) or not isinstance(annotation.get("text"), str):
                raise ValueError("invalid_annotation")
            ref = f"a{index}"
            sources[ref] = {"text": annotation["text"], "kind": annotation.get("kind", "note")}
            positions[ref] = ref
        if len(sources) > 2000 or sum(len(c["text"]) for c in sources.values()) > 100000:
            raise ValueError("input_budget_exceeded")
        out["source_cells"] = sources
        out["cell_status"] = meta["cell_status"]
        deterministic_issues = []
        if re.search(r"(?i)<(?:img|svg)\b", markup):
            deterministic_issues.append(_issue("embedded_image_requires_asset", list(sources)))
        for assertion in request.get("source_assertions", []):
            if not isinstance(assertion, dict):
                raise ValueError("invalid_source_assertion")
            ref = assertion.get("source")
            if ref not in positions or not isinstance(assertion.get("text"), str):
                raise ValueError("invalid_source_assertion")
            if sources[positions[ref]]["text"] != assertion["text"]:
                deterministic_issues.append(_issue("content_conflict", [ref]))
        if request.get("content_conflicts"):
            deterministic_issues.append(_issue("content_conflict", list(sources)))
        if request.get("requires_previous_context"):
            out["dependencies"] = [{"reason": "missing_previous_context", "binding": deepcopy(binding),
                                    "required_evidence": "caller_supplied_continuation_context", "auto_fetch": False}]
            deterministic_issues.append(_issue("missing_previous_context", list(sources)))
        proposal = _automatic(markup, {k: v for k, v in sources.items() if not k.startswith("a")}, positions, binding)
        sections, issues, used = [], [], set()
        if proposal:
            sections, issues, used = validate_proposal(proposal, binding, sources, positions)
        else:
            if any(re.search(r"(?i)\b(if|except|unless|only|note|see|interpolat\w*)\b|仅|除外|条件|插值|注[:：]|续表", c["text"]) for c in sources.values()):
                reason = "conditional_source_requires_review"
            elif re.search(r"(?i)<tfoot\b", markup):
                reason = "footer_requires_review"
            elif any(c.get("colspan", 1) > 1 and c.get("row", 0) > 0 for c in sources.values()):
                reason = "body_spanning_cells"
            elif sum(ref.startswith("r") for ref in positions) != (max(c["row"] + c["rowspan"] for c in sources.values() if "row" in c) * max(c["col"] + c["colspan"] for c in sources.values() if "col" in c)):
                reason = "ragged_table_rows"
            else:
                reason = "ambiguous_header"
            issues = [_issue(reason, list(sources))]
        issues = deterministic_issues + issues
        out["diagnostics"].append({"stage": "deterministic_projection",
                                   "reasons": [issue["reason"] for issue in issues]})
        stage = "strategy_validation"
        budget = request.get("max_model_calls", 0)
        if type(budget) is not int or not 0 <= budget <= 1:
            raise ValueError("invalid_model_budget")
        strategy = str(request.get("query_strategy") or "").strip().lower()
        if strategy not in {"", "semantic_review", "model_required"}:
            raise ValueError("invalid_query_strategy")
        if strategy and budget == 0:
            raise ValueError("invalid_model_budget")
        should_call_model = bool(budget and strategy in {"semantic_review", "model_required"}
                                 and not deterministic_issues)
        if should_call_model:
            stage = "model_initialization"
            config = {**(vlm_config or {}), "description_language": description_language, "max_retries": 0,
                      "_calculation_processing": "single_operation", "table_analysis_max_model_calls": 1,
                      "table_analysis_max_physical_requests": 1}
            requested_thinking = request.get("thinking_mode")
            if requested_thinking is not None:
                if requested_thinking not in {"default", "high"}:
                    raise ValueError("invalid_request")
                supported = thinking_capabilities(config.get("base_url"), config.get("model"))["modes"]
                actual_thinking = requested_thinking if requested_thinking in supported else "default"
                config["thinking_mode"] = actual_thinking
                if (requested_thinking == "high" and actual_thinking == "default"
                        and (urlsplit(str(config.get("base_url") or "")).hostname or "").lower() == "open.bigmodel.cn"
                        and str(config.get("model") or "").lower() == "glm-4.6v-flashx"):
                    config["table_query_enable_thinking"] = True
                    actual_thinking = "enabled"
                if requested_thinking == "high" and valid_router_thinking(config.get("_router_discovered_thinking")):
                    actual_thinking = "unverified"
                out["thinking"] = {"requested": requested_thinking, "actual": actual_thinking}
                if actual_thinking == "unverified":
                    out["thinking"]["probe_status"] = "http_accepted"
            config["timeout_sec"] = max(1, min(int(config.get("timeout_sec", 60)), 60))
            prepared_image = _object_image_args(request)
            owned_image = prepared_image.pop("_owned_image_path", None)
            client = None
            try:
                try:
                    client = vlm_factory(config)
                except Exception as exc:
                    raise_model_error(exc)
                    raise ValueError("model_initialization_failed") from None
                for attempt in range(budget):
                    out["model_calls"] += 1
                    try:
                        image_args = dict(prepared_image)
                        candidate = client.explain_table_query({"binding": binding, "source_cells": sources,
                            "positions": positions, "unresolved": issues}, description_language, **image_args)
                        if client.last_call_info.get("truncated"):
                            raise ValueError("model_response_truncated")
                        new_sections, new_issues, new_used = validate_proposal(candidate, binding, sources, positions)
                        sections, issues, used = new_sections, new_issues, new_used
                        out["diagnostics"].append({"stage": "model_projection", "attempt": attempt + 1,
                                                   "reasons": [issue["reason"] for issue in new_issues]})
                        if not issues:
                            break
                    except (ValueError, TypeError, KeyError, AttributeError) as exc:
                        code = str(exc) if isinstance(exc, ValueError) and str(exc) in REASONS else "invalid_model_response"
                        issues = issues + [_issue(code)]
                        out["diagnostics"].append({"stage": "model_projection", "attempt": attempt + 1, "reasons": [code]})
                    except Exception as exc:
                        raise_model_error(exc)
                        # Never echo provider errors, prompts, or table content into diagnostics.
                        issues = issues + [_issue("model_call_failed")]
                        out["diagnostics"].append({"stage": "model_projection", "attempt": attempt + 1,
                                                   "reasons": ["model_call_failed"]})
            finally:
                out["physical_requests"] = getattr(client, "physical_requests", 0)
                if owned_image:
                    Path(owned_image).unlink(missing_ok=True)
        stage = "condition_validation"
        before_conditions = len(issues)
        for ref, cell in sources.items():
            value = scalar(cell["text"])
            if value["kind"] == "text" and re.search(r"(?:[<>≤≥~～]\s*-?\d|\d\s*[~～])", cell["text"]):
                issues.append(_issue("unsupported_condition", [ref]))
        out["diagnostics"].append({"stage": "condition_validation",
                                   "reasons": [issue["reason"] for issue in issues[before_conditions:]]})
        # Hash equality proves association, not correctness against the original page.
        out["quality"] = {"content_consistency": "conflict" if any(issue["reason"] == "content_conflict" for issue in issues) else "source_bound_not_image_verified",
                          "structure_coverage": "complete" if set(sources) <= used else "unavailable",
                          "query_projection": "complete" if sections and not issues else "unavailable"}
        out["unresolved"] = issues
        out["lookup_status"] = "complete" if sections and not issues else "unavailable"
        out["degraded"] = out["manualReviewRequired"] = bool(issues) or not sections
        if not issues:
            out["lookup_sections"] = sections
        else:
            # Existing consumer treats any section as whole-table success. Quarantine partial output.
            out["candidate_sections"] = sections
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        out["unresolved"] = [_issue(str(exc) if isinstance(exc, ValueError) and str(exc) in REASONS else "invalid_request")]
        out["diagnostics"].append({"stage": stage, "reasons": [out["unresolved"][0]["reason"]]})
    return result


def select_records(projection, section_key, where, satisfied_conditions=()):
    """Offline reference filter; callers must establish textual conditions explicitly."""
    if projection.get("lookup_status") != "complete":
        raise ValueError("query_projection_unavailable")
    sections = [s for s in projection["lookup_sections"] if s["key"] == section_key]
    if len(sections) != 1 or not where or set(where) - set(sections[0]["columns"]):
        raise ValueError("invalid_query_scope")
    matched = []
    for record in sections[0]["records"]:
        if not {c["binding_id"] for c in record["conditions"]} <= set(satisfied_conditions):
            continue
        def matches(key, expected):
            value = record["values"][key]
            if value["kind"] == "interval":
                return interval_contains(value["interval"], expected)
            return value["value"] == expected
        if all(matches(key, expected) for key, expected in where.items()):
            matched.append(deepcopy(record))
    return matched



def select_candidate_labels(projection, section_key, where, satisfied_conditions=()):
    """Diagnostic exact-string matching only; never grants v1 query publication."""
    if not where or any(not isinstance(value, str) for value in where.values()):
        return {"status": "diagnostic_only", "records": []}
    sections = [s for s in projection.get("candidate_sections", []) if s["key"] == section_key]
    if len(sections) != 1 or set(where) - set(sections[0]["columns"]):
        raise ValueError("invalid_query_scope")
    rows = [r for r in sections[0]["records"]
            if all(r["values"][key]["raw_text"] == value for key, value in where.items())
            and all(c["binding_id"] in satisfied_conditions for c in r["conditions"])]
    return {"status": "diagnostic_only", "records": deepcopy(rows)}
