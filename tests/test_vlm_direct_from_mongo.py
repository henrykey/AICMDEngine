#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import re
from pathlib import Path
from typing import Any, Dict, Optional

import fitz
from openai import OpenAI
from pymongo import MongoClient


DEFAULT_PROMPT = (
    "Analyze this PDF page and return strict JSON only, no markdown fence, no explanations.\n"
    "You must output exactly keys: render, rag.\n"
    "Rules:\n"
    "1) Remove page number, header, footer, and footnotes from BOTH render and rag.\n"
    "2) render: clean markdown for display; keep headings/paragraphs/list/table/formula. "
    "Tables as markdown tables, formulas as LaTeX. "
    "figures are represented by placeholders using textual descriptions.\n"
    "3) rag.page_text: plain retrieval text summary of page body (no header/footer/page number/footnotes).\n"
    "4) rag.elements: object with keys formulas/tables/figures, each value is list of semantic descriptions.\n"
    "5) No base64 image output.\n"
    "Output schema:\n"
    "{\"render\":\"...\",\"rag\":{\"page_text\":\"...\",\"elements\":{\"formulas\":[],\"tables\":[],\"figures\":[]}}}"
)


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


def _clean_render_markdown(text: str) -> str:
    s = (text or "").strip()
    if not s.startswith("```"):
        return s
    lines = s.splitlines()
    if not lines:
        return s
    if lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _render_pdf_page_image(pdf_path: Path, page_no: int, dpi: int) -> bytes:
    doc = fitz.open(str(pdf_path))
    try:
        if page_no < 1 or page_no > len(doc):
            raise ValueError(f"page_no out of range: {page_no} / {len(doc)}")
        page = doc[page_no - 1]
        mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        return pix.tobytes("png")
    finally:
        doc.close()


def _read_provider(mongo_uri: str, db_name: str, collection: str, provider_name: str) -> Dict[str, Any]:
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=8000)
    try:
        doc = client[db_name][collection].find_one({"name": provider_name, "enabled": True})
        if not doc:
            raise RuntimeError(f"provider not found or disabled: {provider_name}")
        api_key = (doc.get("api_key_ref") or doc.get("api_key") or "").strip()
        base_url = (doc.get("base_url") or "").strip()
        model = (doc.get("model") or "").strip()
        timeout = int(doc.get("timeout") or 120)
        temperature = float(doc.get("temperature") if doc.get("temperature") is not None else 0.1)
        max_tokens = int(doc.get("max_tokens") or 2400)
        if not (api_key and base_url and model):
            raise RuntimeError("provider config missing required fields: api_key/base_url/model")
        return {
            "name": provider_name,
            "api_key": api_key,
            "base_url": base_url,
            "model": model,
            "timeout": timeout,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Direct VLM test from MongoDB provider config (without MCP).")
    parser.add_argument("--pdf", required=True, help="Absolute path to PDF file")
    parser.add_argument("--page", type=int, default=31, help="1-based page number")
    parser.add_argument("--dpi", type=int, default=300, help="Render DPI")
    parser.add_argument("--provider", default="multmode", help="Provider name in llm_providers")
    parser.add_argument("--mongo-uri", default="mongodb://192.168.123.61", help="MongoDB URI")
    parser.add_argument("--db", default="nl_tps", help="MongoDB database name")
    parser.add_argument("--collection", default="llm_providers", help="MongoDB collection name")
    parser.add_argument("--prompt-file", default="", help="Optional prompt txt path")
    parser.add_argument("--save-prefix", default="docs/test/direct-vlm", help="Output prefix for md/json")
    parser.add_argument("--debug-save", action="store_true", help="Also save raw/meta/parsed debug files")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        raise FileNotFoundError(f"pdf not found: {pdf_path}")

    provider = _read_provider(args.mongo_uri, args.db, args.collection, args.provider)
    print("provider:", json.dumps({k: ("***" if k == "api_key" else v) for k, v in provider.items()}, ensure_ascii=False))

    prompt = DEFAULT_PROMPT
    if args.prompt_file:
        prompt = Path(args.prompt_file).read_text(encoding="utf-8")

    png_bytes = _render_pdf_page_image(pdf_path, args.page, args.dpi)
    image_b64 = base64.b64encode(png_bytes).decode("utf-8")

    client = OpenAI(api_key=provider["api_key"], base_url=provider["base_url"])
    resp = client.chat.completions.create(
        model=provider["model"],
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                ],
            }
        ],
        timeout=provider["timeout"],
        temperature=provider["temperature"],
        max_tokens=provider["max_tokens"],
    )

    content = resp.choices[0].message.content if resp.choices else ""
    if isinstance(content, list):
        raw_text = "\n".join(str(x.get("text", "")) for x in content if isinstance(x, dict))
    else:
        raw_text = str(content or "")

    parsed = _extract_json(raw_text)
    save_prefix = Path(args.save_prefix)
    save_prefix.parent.mkdir(parents=True, exist_ok=True)
    md_path = save_prefix.with_suffix(".md")
    rag_path = save_prefix.with_suffix(".json")

    render_md = _clean_render_markdown((parsed or {}).get("render", "")) if parsed else ""
    rag_obj = (parsed or {}).get("rag") if parsed else None

    md_path.write_text(render_md, encoding="utf-8")
    rag_path.write_text(
        json.dumps(rag_obj if isinstance(rag_obj, dict) else {"parse_error": True}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    meta = {
        "model": provider["model"],
        "base_url": provider["base_url"],
        "provider": provider["name"],
        "page": args.page,
        "dpi": args.dpi,
        "raw_chars": len(raw_text),
        "json_parse_ok": bool(parsed),
        "finish_reason": (resp.choices[0].finish_reason if resp.choices else None),
    }
    print(f"saved: {md_path}")
    print(f"saved: {rag_path}")
    if args.debug_save:
        raw_path = save_prefix.with_suffix(".raw.txt")
        parsed_path = save_prefix.with_suffix(".parsed.json")
        meta_path = save_prefix.with_suffix(".meta.json")
        raw_path.write_text(raw_text, encoding="utf-8")
        parsed_path.write_text(json.dumps(parsed or {"parse_error": True}, ensure_ascii=False, indent=2), encoding="utf-8")
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"saved(debug): {raw_path}")
        print(f"saved(debug): {parsed_path}")
        print(f"saved(debug): {meta_path}")
    print("json_parse_ok:", bool(parsed))
    print("finish_reason:", meta["finish_reason"])


if __name__ == "__main__":
    main()
