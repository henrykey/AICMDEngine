"""Opt-in, source-bound query projections. Never mutate the supplied table."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import hashlib
import re

IDENTITY = ("tenant_id", "doc_id", "version", "table_id", "table_pk")
NUMBER = r"-?\d+(?:\.\d+)?"
REASONS = {
    "unknown_table_identity", "request_id_required", "source_html_required", "content_hash_mismatch",
    "revision_or_page_mismatch", "single_table_required", "input_budget_exceeded",
    "table_structure_unavailable", "overlapping_source_cells", "invalid_annotation",
    "invalid_model_budget", "identity_or_hash_mismatch", "invalid_source_reference", "content_conflict",
    "model_response_truncated", "invalid_projection", "invalid_section_key", "invalid_field",
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


def _sources(markup, parse_grid):
    if len(re.findall(r"(?i)<table\b", markup)) != 1 or len(re.findall(r"(?i)</table\s*>", markup)) != 1:
        raise ValueError("single_table_required")
    if len(markup) > 200000 or len(re.findall(r"(?i)<t[dh]\b", markup)) > 2000:
        raise ValueError("input_budget_exceeded")
    if any(int(n) > 100 for n in re.findall(r'(?i)(?:rowspan|colspan)\s*=\s*[\"\']?(\d+)', markup)):
        raise ValueError("input_budget_exceeded")
    grid, meta = parse_grid(markup)
    if not grid or "rowspan_exceeds_observed_rows" in meta.get("warnings", []):
        raise ValueError("table_structure_unavailable")
    sources, positions = {}, {}
    for cell in meta["source_cells"]:
        ref = f"r{cell['row']}c{cell['col']}"
        sources[ref] = deepcopy(cell)
        for r in range(cell["row"], cell["row"] + cell["rowspan"]):
            for c in range(cell["col"], cell["col"] + cell["colspan"]):
                position = f"r{r}c{c}"
                if position in positions:
                    raise ValueError("overlapping_source_cells")
                positions[position] = ref
    return sources, positions, meta


def _automatic(markup, sources, positions, binding):
    if any(re.search(r"(?i)\b(if|except|unless|only|note|see|interpolat\w*)\b|仅|除外|条件|插值|注[:：]|续表", cell["text"])
           for cell in sources.values()):
        return None
    rows = re.findall(r"(?is)<tr\b[^>]*>(.*?)</tr>", markup)
    headers = []
    for r, row in enumerate(rows):
        if re.search(r"(?i)<th\b", row) and not re.search(r"(?i)<td\b", row):
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
             "records": records}], "unresolved": []}


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
              "unresolved": [], "model_calls": 0}}
    out = result["query_enhancement"]
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
        proposal = _automatic(markup, {k: v for k, v in sources.items() if not k.startswith("a")}, positions, binding)
        sections, issues, used = [], [], set()
        if proposal:
            sections, issues, used = validate_proposal(proposal, binding, sources, positions)
        else:
            issues = [_issue("ambiguous_header", list(sources))]
        budget = request.get("max_model_calls", 0)
        if type(budget) is not int or not 0 <= budget <= 2:
            raise ValueError("invalid_model_budget")
        if budget:
            config = {**(vlm_config or {}), "description_language": description_language, "max_retries": 0}
            config["timeout_sec"] = max(1, min(int(config.get("timeout_sec", 60)), 60))
            client = vlm_factory(config)
            for attempt in range(budget):
                out["model_calls"] += 1
                try:
                    image_args = {"image_path": request["object_image_path"]} if request.get("object_image_path") else {}
                    candidate = client.explain_table_query({"binding": binding, "source_cells": sources,
                        "positions": positions, "unresolved": issues}, description_language, **image_args)
                    if client.last_call_info.get("truncated"):
                        raise ValueError("model_response_truncated")
                    new_sections, new_issues, new_used = validate_proposal(candidate, binding, sources, positions)
                    sections, issues, used = new_sections, new_issues, new_used
                    if not issues:
                        break
                except (ValueError, TypeError, KeyError, AttributeError) as exc:
                    code = str(exc) if isinstance(exc, ValueError) and str(exc) in REASONS else "invalid_model_response"
                    issues = issues + [_issue(code)]
                except Exception:
                    # Never echo provider errors, prompts, or table content into diagnostics.
                    issues = issues + [_issue("model_call_failed")]
        conflicts = []
        for assertion in request.get("source_assertions", []):
            ref = assertion.get("source")
            if ref not in positions or not isinstance(assertion.get("text"), str):
                raise ValueError("invalid_source_assertion")
            if sources[positions[ref]]["text"] != assertion["text"]:
                conflicts.append(ref)
        if conflicts:
            issues.append(_issue("content_conflict", conflicts))
        if request.get("content_conflicts"):
            issues.append(_issue("content_conflict", list(sources)))
        for ref, cell in sources.items():
            value = scalar(cell["text"])
            if value["kind"] == "text" and re.search(r"(?:[<>≤≥~～]\s*-?\d|\d\s*[~～])", cell["text"]):
                issues.append(_issue("unsupported_condition", [ref]))
        if request.get("requires_previous_context"):
            issues.append(_issue("missing_previous_context", list(sources)))
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
