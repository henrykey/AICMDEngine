#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import yaml
from openai import OpenAI


HAN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def has_chinese(text: str) -> bool:
    return bool(HAN_RE.search(text))


def collect_strings(node: Any, out: list[str]) -> None:
    if isinstance(node, dict):
        for value in node.values():
            collect_strings(value, out)
        return
    if isinstance(node, list):
        for value in node:
            collect_strings(value, out)
        return
    if isinstance(node, str) and has_chinese(node):
        out.append(node)


def replace_strings(node: Any, translations: dict[str, str]) -> Any:
    if isinstance(node, dict):
        return {key: replace_strings(value, translations) for key, value in node.items()}
    if isinstance(node, list):
        return [replace_strings(value, translations) for value in node]
    if isinstance(node, str) and node in translations:
        return translations[node]
    return node


def batched(values: list[str], size: int) -> list[list[str]]:
    return [values[index:index + size] for index in range(0, len(values), size)]


def translate_batch(client: OpenAI, model: str, values: list[str]) -> list[str]:
    prompt = (
        "Translate each input string from Chinese to clear technical English.\n"
        "Rules:\n"
        "1. Preserve YAML-safe plain text semantics.\n"
        "2. Preserve URLs, code blocks, inline code, enum literals, parameter names, field names, and placeholders.\n"
        "3. Keep markdown formatting if present.\n"
        "4. Translate only human-language text.\n"
        "5. Return JSON only: an array of translated strings with the same order and count.\n"
    )
    payload = json.dumps(values, ensure_ascii=False)
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        messages=[
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": (
                    'Return strict JSON as {"translations": [...]} with no markdown fences.\n'
                    f"Input strings:\n{payload}"
                ),
            },
        ],
    )
    content = response.choices[0].message.content or ""
    data = json.loads(content)
    translations = data.get("translations")
    if not isinstance(translations, list) or len(translations) != len(values):
        raise ValueError("Unexpected translation response shape")
    return [str(item) for item in translations]


def build_client(provider: str) -> tuple[OpenAI, str]:
    if provider == "deepseek":
        api_key = os.getenv("DEEPSEEK_API_KEY")
        base_url = os.getenv("DEEPSEEK_BASE_URL")
        model = os.getenv("DEEPSEEK_MODEL_NAME", "deepseek-chat")
    else:
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL")
        model = os.getenv("OPENAI_MODEL_NAME", "gpt-4")

    if not api_key:
        raise ValueError(f"Missing API key for provider: {provider}")

    return OpenAI(api_key=api_key, base_url=base_url), model


def main() -> None:
    parser = argparse.ArgumentParser(description="Translate OpenAPI YAML strings to English")
    parser.add_argument("--input", required=True, help="Input YAML file")
    parser.add_argument("--output", required=True, help="Output YAML file")
    parser.add_argument("--provider", choices=["openai", "deepseek"], default="openai")
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--sleep-seconds", type=float, default=0.5)
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()

    document = yaml.safe_load(input_path.read_text(encoding="utf-8"))
    strings: list[str] = []
    collect_strings(document, strings)
    unique_strings = list(dict.fromkeys(strings))

    client, model = build_client(args.provider)
    translations: dict[str, str] = {}

    for chunk in batched(unique_strings, args.batch_size):
        translated_chunk = translate_batch(client, model, chunk)
        translations.update(dict(zip(chunk, translated_chunk)))
        time.sleep(args.sleep_seconds)

    translated_document = replace_strings(document, translations)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        yaml.safe_dump(translated_document, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "input": str(input_path),
                "output": str(output_path),
                "translated_strings": len(unique_strings),
                "provider": args.provider,
                "model": model,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
