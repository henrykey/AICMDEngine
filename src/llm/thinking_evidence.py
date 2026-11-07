"""Validate bounded, source-linked model capability claims without guessing support."""

import re
import hashlib

from .thinking_probe_client import _valid_parameters


OPTIONS = {"thinking": {"enabled", "disabled"}, "reasoning_effort": {"low", "high", "max"}}


def restore_quoted_evidence(reference, sources, repairs=None, field="evidence"):
    """Restore only a uniquely anchored, bounded ellipsis from one source."""
    if not isinstance(reference, dict) or set(reference) != {"url", "quote"}:
        return reference
    url, quote = reference["url"], reference["quote"]
    if not isinstance(url, str) or not isinstance(quote, str):
        return reference
    document = sources.get(url)
    if not isinstance(document, str) or quote in document:
        return reference
    if quote.count("...") + quote.count("…") != 1:
        return reference
    marker = "..." if "..." in quote else "…"
    prefix, suffix = (part.strip() for part in quote.split(marker))
    if (len(prefix) < 12 or len(suffix) < 12 or document.count(prefix) != 1 or document.count(suffix) != 1):
        return reference
    start, suffix_start = document.find(prefix), document.find(suffix)
    end = suffix_start + len(suffix)
    if suffix_start < start + len(prefix) or end - start > 5000:
        return reference
    restored = document[start:end]
    if repairs is not None:
        repairs.append({"url": url, "field": field, "method": "unique_ellipsis",
            "original_sha256": hashlib.sha256(quote.encode("utf-8")).hexdigest(),
            "restored_sha256": hashlib.sha256(restored.encode("utf-8")).hexdigest()})
    return {"url": url, "quote": restored}


def restore_unique_model_context(reference, model, sources, repairs=None):
    """Add exact-model context only from a unique unambiguous source sentence."""
    if (not isinstance(reference, dict) or set(reference) != {"url", "quote"}
            or not isinstance(reference["url"], str) or not isinstance(reference["quote"], str)
            or not isinstance(model, str) or "-" not in model):
        return reference
    document, quote = sources.get(reference["url"]), reference["quote"]
    if not isinstance(document, str) or len(quote) < 12 or document.count(quote) != 1:
        return reference
    start = document.find(quote)
    # The provider explicitly lists all models governed by one API restriction.
    # Keep the parameter heading as context, and accept only a plain model list
    # followed by a plain list of allowed values; comparisons are not a list.
    grouped = re.compile(
        r"针对\s+([a-z][a-z0-9._-]*(?:(?:\s*[、,/和及]\s*|\s+)[a-z][a-z0-9._-]*)*)\s*[，,]\s*仅支持\s+"
        r"((?:max|high|low)(?:\s*[、,/和及]\s*(?:max|high|low))*)", re.I)
    for match in grouped.finditer(document):
        if not match.start() <= start or start + len(quote) > match.end():
            continue
        models = re.findall(r"[a-z][a-z0-9._-]*", match.group(1), re.I)
        prefix = model.split("-", 1)[0].lower() + "-"
        if (len(models) < 2 or any(not item.lower().startswith(prefix) for item in models)
                or model.lower() not in [item.lower() for item in models]):
            return reference
        heading = document.rfind("reasoning_effort", max(0, match.start() - 500), match.start())
        if heading < 0 or re.search(r"[。！？;；]", document[heading:match.start()]):
            return reference
        restored = document[heading:match.end()]
        if repairs is not None:
            repairs.append({"url": reference["url"], "field": "evidence", "method": "unique_model_context",
                "original_sha256": hashlib.sha256(quote.encode("utf-8")).hexdigest(),
                "restored_sha256": hashlib.sha256(restored.encode("utf-8")).hexdigest()})
        return {"url": reference["url"], "quote": restored}
    if _contains_identifier(quote, model):
        return reference
    boundaries = list(re.finditer(r"[。！？;；]|[.!?](?=\s|$)", document))
    left = max((item.end() for item in boundaries if item.end() <= start), default=0)
    right = min((item.start() for item in boundaries if item.start() >= start + len(quote)), default=len(document))
    sentence = document[left:right].strip()
    if not 1 <= len(sentence) <= 5000 or quote not in sentence:
        return reference
    if re.search(r"\b(?:versus|vs|unlike|except|excluding|compared)\b|相比|对比|除外|不包括|区别", sentence, re.I):
        return reference
    model_pattern = r"(?<![a-z0-9._-])" + re.escape(model) + r"(?![a-z0-9._-])"
    if len(list(re.finditer(model_pattern, sentence, re.I))) != 1:
        return reference
    vendor = model.split("-", 1)[0]
    vendor_pattern = r"(?<![a-z0-9._-])" + re.escape(vendor) + r"-[a-z0-9][a-z0-9._-]*"
    mentioned = {match.group().lower().rstrip(".") for match in re.finditer(vendor_pattern, sentence, re.I)}
    if mentioned != {model.lower()}:
        return reference
    if repairs is not None:
        repairs.append({"url": reference["url"], "field": "evidence", "method": "unique_model_context",
            "original_sha256": hashlib.sha256(quote.encode("utf-8")).hexdigest(),
            "restored_sha256": hashlib.sha256(sentence.encode("utf-8")).hexdigest()})
    return {"url": reference["url"], "quote": sentence}


def restore_claim_quotes(claims, sources, repairs=None, model=None):
    if not isinstance(claims, list):
        return claims
    result = []
    for raw in claims:
        if not isinstance(raw, dict):
            result.append(raw)
            continue
        item = dict(raw)
        if item.get("scope") == "exact":
            item.setdefault("series", None)
            item.setdefault("relation_evidence", None)
        for key in ("evidence", "relation_evidence"):
            if key in item:
                item[key] = restore_quoted_evidence(item[key], sources, repairs, key)
        if item.get("scope") == "exact" and "evidence" in item and model:
            item["evidence"] = restore_unique_model_context(item["evidence"], model, sources, repairs)
        result.append(item)
    return result


def _contains_identifier(text, identifier):
    return bool(re.search(r"(?<![a-z0-9._-])" + re.escape(identifier) + r"(?![a-z0-9._-])", text, re.I))


def source_mentions_model_and_parameters(model, documents):
    """Select a follow-up target only; co-occurrence is never support evidence."""
    return any(_contains_identifier(document, model) and any(term in document.lower() for term in ("thinking", "reasoning_effort"))
               for document in documents.values() if isinstance(document, str))


def _contains_parameter_term(text, term):
    return bool(re.search(r"(?<![a-z0-9_-])" + re.escape(term) + r"(?![a-z0-9_-])", text, re.I))


def _parameter_terms(value):
    if isinstance(value, dict):
        return [term for key, item in value.items() for term in (key, *_parameter_terms(item))]
    return [str(value).lower() if isinstance(value, bool) else str(value)]


def _negative_for_option(quote, option):
    negative = r"(?:not\s+support(?:ed)?|does\s+not\s+support|unsupported|cannot|不支持|不再支持|不允许)"
    option_pattern = r"(?<![a-z0-9._-])" + re.escape(option) + r"(?![a-z0-9._-])"
    between = r"(?:(?!\.(?:\s|$))[^\n。！？;；]){0,80}"
    return bool(re.search(r"(?:" + negative + between + option_pattern + r"|" + option_pattern + between + negative + r")", quote, re.I))


def _explicit_family_relation(quote, model, series):
    value = quote.lower()
    negative = ("not ", "different", "versus", "compared", "instead", "exclude", "不属于", "并非", "不同", "对比", "区别", "排除")
    if any(term in value for term in negative):
        return False
    model_name, series_name = model.lower(), series.lower()
    model, series = re.escape(model_name), re.escape(series_name)
    patterns = (
        series + r"\s*(?:series|family|系列|家族)\s*(?:includes?|contains?|members?[:：]?|包括|包含|成员[:：]?)[^\n。！？;；]{0,120}" + model,
        model + r"[^\n。！？;；]{0,40}(?:belongs to|part of|member of|属于|是)[^\n。！？;；]{0,40}" + series + r"\s*(?:series|family|系列|家族)",
    )
    if any(re.search(pattern, sentence, re.I) for sentence in re.split(r"(?<=[.!?])\s+", value) for pattern in patterns):
        return True
    groups = re.finditer(r"(?<![a-z0-9._-])([a-z0-9][a-z0-9._-]*(?:\s*/\s*[a-z0-9][a-z0-9._-]*){1,8})\s*(?:series|family|系列|家族)", value)
    for group in groups:
        members = [part.strip() for part in group.group(1).split("/")]
        if (series_name in members and model_name in members
                and all(member == series_name or member.startswith(series_name + "-") for member in members)):
            return True
    return False


def validate_family_relation(model, series, relation, sources):
    if (not isinstance(model, str) or not model or not isinstance(series, str) or not series
            or series.lower() == model.lower() or not isinstance(relation, dict)
            or set(relation) != {"url", "quote"} or not isinstance(relation["url"], str)):
        return False
    document, quote = sources.get(relation["url"]), relation["quote"]
    return (isinstance(document, str) and isinstance(quote, str) and 1 <= len(quote) <= 5000
            and quote in document and _contains_identifier(quote, model) and _contains_identifier(quote, series)
            and _explicit_family_relation(quote, model, series))


def find_explicit_family(model, sources, series):
    """Find an explicitly cited relationship for a model-provided candidate family."""
    if (not isinstance(model, str) or not model or not isinstance(series, str)
            or not 3 <= len(series) <= 128 or series.lower() == model.lower()):
        return None
    candidates = [series]
    found = {}
    ambiguous = False
    for series in candidates:
        for url, document in sources.items():
            if not isinstance(url, str) or not isinstance(document, str):
                continue
            model_pattern = r"(?<![a-z0-9._-])" + re.escape(model) + r"(?![a-z0-9._-])"
            family_pattern = r"(?<![a-z0-9._-])" + re.escape(series) + r"(?![a-z0-9._-])"
            model_hits = list(re.finditer(model_pattern, document, re.I))[:30]
            family_hits = list(re.finditer(family_pattern, document, re.I))[:30]
            for model_hit in model_hits:
                for family_hit in family_hits:
                    start = min(model_hit.start(), family_hit.start())
                    end = max(model_hit.end(), family_hit.end())
                    if end - start > 200:
                        continue
                    nearby = document[max(0, start - 40):min(len(document), end + 80)].lower()
                    if any(term in nearby for term in ("not ", "different", "versus", "compared", "instead", "exclude",
                                                        "不属于", "并非", "不同", "对比", "区别", "排除")):
                        ambiguous = True
                    for before in (0, 40):
                        for after in (0, 20, 60, 100):
                            quote = document[max(0, start - before):min(len(document), end + after)].strip()
                            relation = {"url": url, "quote": quote}
                            if validate_family_relation(model, series, relation, sources):
                                found.setdefault(series.lower(), {"series": series, "relation_evidence": relation})
                                break
                        if series.lower() in found:
                            break
                    if series.lower() in found:
                        break
                if series.lower() in found:
                    break
    return next(iter(found.values())) if len(found) == 1 and not ambiguous else None


def validate_claims(model, sources, claims, diagnostics=None):
    """Return accepted claims and explicit conflicts; absence always means unknown."""
    if not isinstance(model, str) or not model or not isinstance(claims, list) or len(claims) > 10:
        return {}, []
    grouped = {}
    def reject(reason):
        if diagnostics is not None:
            diagnostics[reason] = diagnostics.get(reason, 0) + 1
    for claim in claims:
        if not isinstance(claim, dict) or set(claim) != {"dimension", "option", "support", "scope", "series", "parameters", "evidence", "relation_evidence"}:
            reject("claim_shape")
            continue
        dimension, option = claim["dimension"], claim["option"]
        if (not isinstance(dimension, str) or dimension not in OPTIONS or not isinstance(option, str) or option not in OPTIONS[dimension]
                or not isinstance(claim["support"], str) or claim["support"] not in {"supported", "unsupported"}
                or not isinstance(claim["scope"], str) or claim["scope"] not in {"exact", "series"}):
            reject("claim_category")
            continue
        evidence = claim["evidence"]
        if not isinstance(evidence, dict) or set(evidence) != {"url", "quote"}:
            reject("evidence_shape")
            continue
        doc, quote = sources.get(evidence["url"]) if isinstance(evidence["url"], str) else None, evidence["quote"]
        if not isinstance(doc, str) or not isinstance(quote, str) or not 1 <= len(quote) <= 5000 or quote not in doc:
            reject("evidence_not_exact")
            continue
        identifier = model
        relation = claim["relation_evidence"]
        if claim["scope"] == "series":
            identifier = claim["series"]
            if (not isinstance(identifier, str) or not identifier or identifier.lower() == model.lower()
                    or not isinstance(relation, dict) or set(relation) != {"url", "quote"}):
                reject("family_relation_shape")
                continue
            if not validate_family_relation(model, identifier, relation, sources):
                reject("family_relation_unverified")
                continue
        elif claim["series"] is not None or relation is not None:
            reject("exact_relation_unexpected")
            continue
        if not _contains_identifier(quote, identifier):
            reject("evidence_model_missing")
            continue
        if dimension.lower() not in quote.lower():
            reject("evidence_dimension_missing")
            continue
        if not _contains_identifier(quote, option):
            reject("evidence_option_missing")
            continue
        negative = any(word in quote.lower() for word in ("not support", "does not support", "unsupported", "cannot", "不支持", "不再支持", "不允许"))
        if (claim["support"] == "supported" and negative) or (claim["support"] == "unsupported" and not _negative_for_option(quote, option)):
            reject("support_context_ambiguous")
            continue
        params = claim["parameters"]
        if claim["support"] == "supported":
            if not _valid_parameters(params):
                reject("parameter_shape")
                continue
            # The option is never promoted from a different parameter or another effort level.
            if dimension == "reasoning_effort":
                if params.get("reasoning_effort") != option:
                    reject("parameter_option_mismatch")
                    continue
                if "thinking" in params and params["thinking"] != {"type": "enabled"}:
                    reject("parameter_option_mismatch")
                    continue
                if "enable_thinking" in params and params["enable_thinking"] is not True:
                    reject("parameter_option_mismatch")
                    continue
            if dimension == "thinking" and params not in ({"thinking": {"type": option}}, {"enable_thinking": option == "enabled"}):
                reject("parameter_option_mismatch")
                continue
            if any(not _contains_parameter_term(quote, str(term)) for term in _parameter_terms(params)):
                reject("parameter_evidence_missing")
                continue
        elif params != {}:
            reject("unsupported_has_parameters")
            continue
        grouped.setdefault((dimension, option), []).append(claim)
    accepted, conflicts = {}, []
    for key, items in grouped.items():
        if len({item["support"] for item in items}) > 1:
            conflicts.append({"dimension": key[0], "option": key[1], "evidence": [
                {"support": item["support"], "scope": item["scope"], "series": item["series"],
                 "evidence_level": "model_explicit" if item["scope"] == "exact" else "family_inference",
                 "evidence": item["evidence"], "relation_evidence": item["relation_evidence"]} for item in items]})
        else:
            accepted[key] = items
    return accepted, conflicts
