"""Shared conservative language evidence for generated prose, never source titles."""
import re


def normalize_language(value):
    value = str(value or "").strip().lower()
    if value in {"zh", "zh-cn", "zh_hans", "chinese"}:
        return "zh"
    if value in {"en", "en-us", "english"}:
        return "en"
    return "unknown"


def detect_description_language(value):
    text = re.sub(r"(?s)\$\$.*?\$\$|\$[^$]*\$", " ", str(value or ""))
    text = re.sub(r"(?is)</?[A-Za-z][^<>]*>", " ", text)
    han_count = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", text))
    latin_words = re.findall(r"\b[A-Za-z][A-Za-z'-]{1,}\b", text)
    if han_count >= 4:
        return "zh"
    if sum(len(word) for word in latin_words) >= 12 and len(latin_words) >= 3:
        return "en"
    return None



def description_mismatch(value, language):
    expected = normalize_language(language)
    detected = detect_description_language(value)
    if expected == "zh":
        prose = re.sub(r"^[^:：\n]{1,60}[:：]", "", str(value or ""))
        # Inspect prose clauses so a Chinese heading cannot mask English sentences.
        if any(detect_description_language(part) == "en" for part in re.split(r"[。！？!?\n]", prose)):
            return True
    return expected != "unknown" and detected is not None and detected != expected


def validate_descriptions(item, language):
    """Clear rejected generated fields only; leave source HTML/LaTeX/names untouched."""
    rejected = []
    for field in ("description", "semantic_desc", "semanticDesc", "semantic_summary", "variables"):
        value = item.get(field)
        if field == "semantic_summary" and isinstance(value, str):
            for name in ("title", "formula_name", "caption"):
                if isinstance(item.get(name), str) and item[name]:
                    value = value.replace(item[name], "", 1)
        if isinstance(value, str) and description_mismatch(value, language):
            item[field] = ""
            rejected.append(field)
    if rejected:
        item["semantic_reason"] = "description_language_mismatch"
        item["semantic_status"] = "unresolved"
        item["missing_fields"] = list(dict.fromkeys(list(item.get("missing_fields") or []) + rejected))
    return rejected


def number_only(value: str) -> bool:
    return bool(re.fullmatch(
        r"(?i)(?:(?:equation|eq\.?|formula|公式|式)\s*)?[（(]?\s*"
        r"(?:[A-Z]?[.\-]?\d+(?:[.\-]\d+)*[A-Z]?|[IVXLCDM]+)\s*[)）]?[.:：]?",
        value.strip(),
    ))


def valid_description(value, name: str = "") -> str:
    description = str(value or "").strip()
    if not description or number_only(description):
        return ""
    compact = lambda text: re.sub(r"[\s:：。.!！]+", "", text).casefold()
    if name:
        remainder = re.sub(re.escape(name), "", description, count=1, flags=re.I).strip(" :：。.")
        if compact(description) == compact(name) or number_only(remainder):
            return ""
    # Strip known non-semantic filler, retaining substantive sentences if supplied.
    parts = re.split(r"(?<=[。.!！;；])\s*|\n+", description)
    invalid = r"包含\s*\d+\s*行|contains?\s+\d+\s+rows|语义(?:说明)?缺失|变量说明见原文|请?结合上下文解释|see the source document|refer to (?:the )?(?:source|context)|semantic (?:description )?(?:missing|unavailable)"
    return " ".join(part for part in parts if part.strip() and not re.search(invalid, part, re.I)).strip()
