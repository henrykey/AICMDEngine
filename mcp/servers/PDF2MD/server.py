#!/usr/bin/env python3
import asyncio
import base64
import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastmcp import FastMCP


@dataclass
class RuntimeConfig:
    output_dir: str = os.getenv("PDF2MD_OUTPUT_DIR", "/tmp/pdf2md_output")
    max_file_size_mb: int = int(os.getenv("PDF2MD_MAX_FILE_SIZE_MB", "100"))
    max_pages: int = int(os.getenv("PDF2MD_MAX_PAGES", "500"))
    max_qwen_calls_per_doc: int = int(os.getenv("PDF2MD_MAX_QWEN_CALLS_PER_DOC", "40"))
    qwen_timeout_sec: int = int(os.getenv("PDF2MD_QWEN_TIMEOUT_SEC", "60"))
    qwen_max_retries: int = int(os.getenv("PDF2MD_QWEN_MAX_RETRIES", "2"))
    allow_external_vlm: bool = os.getenv("PDF2MD_ALLOW_EXTERNAL_VLM", "true").lower() in {"1", "true", "yes"}


class QwenVLClient:
    def __init__(self, cfg: RuntimeConfig) -> None:
        self._cfg = cfg
        self._client = None
        self._model = None
        self._enabled = False

        api_key = os.getenv("QWEN_API_KEY") or os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("QWEN_BASE_URL") or os.getenv("OPENAI_BASE_URL")
        model = os.getenv("QWEN_MODEL_NAME") or "qwen-vl-max-latest"

        if not cfg.allow_external_vlm or not api_key:
            return

        try:
            from openai import OpenAI

            self._client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
            self._model = model
            self._enabled = True
        except Exception:
            self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    def describe_image(self, image_path: str, prompt: str) -> str:
        if not self._enabled or not self._client:
            return ""

        with open(image_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")

        for attempt in range(self._cfg.qwen_max_retries + 1):
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/png;base64,{encoded}"},
                                },
                            ],
                        }
                    ],
                    timeout=self._cfg.qwen_timeout_sec,
                    max_tokens=900,
                )
                content = response.choices[0].message.content if response.choices else ""
                if isinstance(content, list):
                    return "\n".join([item.get("text", "") for item in content if isinstance(item, dict)])
                return content or ""
            except Exception:
                if attempt >= self._cfg.qwen_max_retries:
                    return ""
                time.sleep(0.4 * (attempt + 1))
        return ""


class PDF2MDService:
    def __init__(self) -> None:
        self.cfg = RuntimeConfig()
        Path(self.cfg.output_dir).mkdir(parents=True, exist_ok=True)
        self.qwen = QwenVLClient(self.cfg)

    def health_check(self) -> Dict[str, Any]:
        mineru_available = self._check_mineru_available()
        return {
            "ok": True,
            "service": "PDF2MD",
            "version": "0.1.0",
            "mineru_available": mineru_available,
            "qwen_enabled": self.qwen.enabled,
            "allow_external_vlm": self.cfg.allow_external_vlm,
        }

    def parse_standard_pdf(self, file_path: str, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        options = options or {}
        started = time.time()

        resolved = self._validate_file(file_path)
        run_id = hashlib.sha1(f"{resolved}:{time.time()}".encode("utf-8")).hexdigest()[:12]

        with tempfile.TemporaryDirectory(prefix="pdf2md_", dir=self.cfg.output_dir) as work_dir:
            markdown, blocks, warnings, parser_engine = self._parse_with_mineru(resolved, work_dir)

            if not markdown.strip() or not blocks:
                fb_markdown, fb_blocks, fb_warning = self._fallback_parse_with_fitz(resolved)
                warnings.extend(fb_warning)
                if fb_markdown.strip() and fb_blocks:
                    markdown, blocks = fb_markdown, fb_blocks
                    parser_engine = "fitz-fallback"

            enable_qwen = bool(options.get("enable_qwen_enhance", True)) and self.qwen.enabled
            qwen_calls = 0

            if enable_qwen and blocks:
                page_images = self._render_page_images(resolved, work_dir)
                blocks, qwen_calls, enhance_warnings = self._enhance_non_text_blocks(blocks, page_images)
                warnings.extend(enhance_warnings)

            if not markdown:
                markdown = self._compose_markdown(blocks)

            elapsed_ms = int((time.time() - started) * 1000)
            return {
                "success": True,
                "run_id": run_id,
                "document_markdown": markdown,
                "layout_blocks": blocks,
                "assets": {
                    "temp_artifacts_retained": False,
                },
                "stats": {
                    "elapsed_ms": elapsed_ms,
                    "block_count": len(blocks),
                    "qwen_calls": qwen_calls,
                    "parser_engine": parser_engine,
                },
                "warnings": warnings,
                "errors": [],
            }

    def prepare_rag_chunks(self, file_path: str, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        options = options or {}
        parse_result = self.parse_standard_pdf(file_path=file_path, options=options)
        if not parse_result.get("success"):
            return parse_result

        blocks = parse_result.get("layout_blocks", [])
        max_chars = int(options.get("chunk_max_chars", 1600))
        overlap_chars = int(options.get("chunk_overlap_chars", 120))

        chunks = self._build_chunks(blocks, max_chars=max_chars, overlap_chars=overlap_chars)
        return {
            "success": True,
            "run_id": parse_result.get("run_id"),
            "rag_chunks": chunks,
            "embedding_metadata": {
                "non_text_enhanced": True,
                "source": str(file_path),
                "block_count": len(blocks),
                "parser_engine": parse_result.get("stats", {}).get("parser_engine"),
            },
            "stats": {
                **parse_result.get("stats", {}),
                "chunk_count": len(chunks),
            },
            "warnings": parse_result.get("warnings", []),
            "errors": [],
        }

    def _check_mineru_available(self) -> bool:
        try:
            import magic_pdf  # noqa: F401

            return True
        except Exception:
            return False

    def _validate_file(self, file_path: str) -> Path:
        path = Path(file_path).expanduser().resolve()
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"PDF file not found: {path}")
        if path.suffix.lower() != ".pdf":
            raise ValueError("Only .pdf files are supported")

        file_size_mb = path.stat().st_size / (1024 * 1024)
        if file_size_mb > self.cfg.max_file_size_mb:
            raise ValueError(f"File too large: {file_size_mb:.1f}MB > {self.cfg.max_file_size_mb}MB")

        pages = self._detect_page_count(path)
        if pages is not None and pages > self.cfg.max_pages:
            raise ValueError(f"Too many pages: {pages} > {self.cfg.max_pages}")

        return path

    def _detect_page_count(self, pdf_path: Path) -> Optional[int]:
        try:
            import fitz

            doc = fitz.open(str(pdf_path))
            count = len(doc)
            doc.close()
            return count
        except Exception:
            return None

    def _parse_with_mineru(self, pdf_path: Path, work_dir: str) -> Tuple[str, List[Dict[str, Any]], List[str], str]:
        warnings: List[str] = []
        try:
            from magic_pdf.data.data_reader_writer import FileBasedDataWriter
            from magic_pdf.data.read_api import read_local_pdf
            from magic_pdf.pipe.OCRPipe import OCRPipe

            image_writer = FileBasedDataWriter(work_dir)
            pdf_docs = read_local_pdf(str(pdf_path))
            pipe = OCRPipe(pdf_docs, image_writer, None)

            pipe.pipe_classify()
            pipe.pipe_analyze()
            pipe.pipe_parse()

            markdown = self._safe_get_markdown(pipe)
            blocks = self._markdown_to_blocks(markdown)
            return markdown, blocks, warnings, "mineru"
        except Exception as exc:
            warnings.append(f"MinerU parse failed: {exc}")
            return "", [], warnings, "mineru"

    def _safe_get_markdown(self, pipe: Any) -> str:
        if hasattr(pipe, "get_markdown") and callable(pipe.get_markdown):
            content = pipe.get_markdown()
            if isinstance(content, str):
                return content
        if hasattr(pipe, "get_md") and callable(pipe.get_md):
            content = pipe.get_md()
            if isinstance(content, str):
                return content
        return ""

    def _markdown_to_blocks(self, markdown: str) -> List[Dict[str, Any]]:
        if not markdown.strip():
            return []

        lines = markdown.splitlines()
        blocks: List[Dict[str, Any]] = []
        buf: List[str] = []
        order = 0

        def flush_text() -> None:
            nonlocal order
            text = "\n".join(buf).strip()
            if text:
                blocks.append(
                    {
                        "block_id": f"b{order}",
                        "page": None,
                        "type": "text",
                        "bbox": None,
                        "confidence": None,
                        "raw_content": text,
                        "normalized_content": text,
                        "source": "mineru",
                        "order": order,
                    }
                )
                order += 1
            buf.clear()

        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            if not stripped:
                flush_text()
                i += 1
                continue

            if stripped.startswith("!") and "(" in stripped and ")" in stripped:
                flush_text()
                blocks.append(
                    {
                        "block_id": f"b{order}",
                        "page": None,
                        "type": "image",
                        "bbox": None,
                        "confidence": None,
                        "raw_content": stripped,
                        "normalized_content": stripped,
                        "source": "mineru",
                        "order": order,
                    }
                )
                order += 1
                i += 1
                continue

            if stripped.startswith("$$") or stripped.startswith("\\["):
                flush_text()
                formula_lines = [line]
                i += 1
                while i < len(lines):
                    formula_lines.append(lines[i])
                    if lines[i].strip().endswith("$$") or lines[i].strip().endswith("\\]"):
                        i += 1
                        break
                    i += 1
                formula_text = "\n".join(formula_lines).strip()
                blocks.append(
                    {
                        "block_id": f"b{order}",
                        "page": None,
                        "type": "formula",
                        "bbox": None,
                        "confidence": None,
                        "raw_content": formula_text,
                        "normalized_content": formula_text,
                        "source": "mineru",
                        "order": order,
                    }
                )
                order += 1
                continue

            if stripped.startswith("|") and stripped.endswith("|"):
                flush_text()
                table_lines = [line]
                i += 1
                while i < len(lines):
                    curr = lines[i].strip()
                    if curr.startswith("|") and curr.endswith("|"):
                        table_lines.append(lines[i])
                        i += 1
                    else:
                        break
                table_text = "\n".join(table_lines)
                blocks.append(
                    {
                        "block_id": f"b{order}",
                        "page": None,
                        "type": "table",
                        "bbox": None,
                        "confidence": None,
                        "raw_content": table_text,
                        "normalized_content": table_text,
                        "source": "mineru",
                        "order": order,
                    }
                )
                order += 1
                continue

            buf.append(line)
            i += 1

        flush_text()
        return blocks

    def _fallback_parse_with_fitz(self, pdf_path: Path) -> Tuple[str, List[Dict[str, Any]], List[str]]:
        warnings: List[str] = []
        blocks: List[Dict[str, Any]] = []
        markdown_parts: List[str] = []
        order = 0

        try:
            import fitz

            doc = fitz.open(str(pdf_path))
            for page_index, page in enumerate(doc, start=1):
                text = page.get_text("text") or ""
                cleaned = re.sub(r"\n{3,}", "\n\n", text).strip()
                if cleaned:
                    md_block_text = cleaned
                    blocks.append(
                        {
                            "block_id": f"b{order}",
                            "page": page_index,
                            "type": "text",
                            "bbox": None,
                            "confidence": None,
                            "raw_content": md_block_text,
                            "normalized_content": md_block_text,
                            "source": "fitz",
                            "order": order,
                        }
                    )
                    markdown_parts.append(md_block_text)
                    order += 1

                image_list = page.get_images(full=True)
                for image_idx, _img in enumerate(image_list, start=1):
                    label = f"[IMAGE p{page_index}-{image_idx}]"
                    blocks.append(
                        {
                            "block_id": f"b{order}",
                            "page": page_index,
                            "type": "image",
                            "bbox": None,
                            "confidence": None,
                            "raw_content": label,
                            "normalized_content": label,
                            "source": "fitz",
                            "order": order,
                        }
                    )
                    markdown_parts.append(f"![]({label})")
                    order += 1

            doc.close()
            if not blocks:
                warnings.append("fitz fallback produced empty content")

            return "\n\n".join(markdown_parts).strip(), blocks, warnings
        except Exception as exc:
            warnings.append(f"fitz fallback failed: {exc}")
            return "", [], warnings

    def _render_page_images(self, pdf_path: Path, work_dir: str) -> Dict[int, str]:
        page_images: Dict[int, str] = {}
        try:
            import fitz

            doc = fitz.open(str(pdf_path))
            for i, page in enumerate(doc):
                pix = page.get_pixmap(dpi=150)
                out = os.path.join(work_dir, f"page_{i + 1}.png")
                pix.save(out)
                page_images[i + 1] = out
            doc.close()
        except Exception:
            return {}
        return page_images

    def _enhance_non_text_blocks(
        self,
        blocks: List[Dict[str, Any]],
        page_images: Dict[int, str],
    ) -> Tuple[List[Dict[str, Any]], int, List[str]]:
        warnings: List[str] = []
        qwen_calls = 0

        for block in blocks:
            block_type = block.get("type")

            if block_type == "table":
                table_text = block.get("normalized_content", "")
                block["semantic_description"] = self._summarize_table(table_text)

            elif block_type == "formula":
                formula_text = block.get("normalized_content", "")
                block["semantic_description"] = self._explain_formula(formula_text)

            elif block_type == "image":
                page = block.get("page")
                page_image = page_images.get(page) if isinstance(page, int) else None
                if page_image and qwen_calls < self.cfg.max_qwen_calls_per_doc:
                    prompt = (
                        "请描述图像中的核心对象、关系和业务语义，"
                        "如果是流程图/结构图请输出可检索的关键描述。"
                    )
                    desc = self.qwen.describe_image(page_image, prompt)
                    qwen_calls += 1
                    if desc:
                        block["semantic_description"] = desc
                        continue
                    warnings.append(f"Qwen image description failed for block {block.get('block_id')}")

                block["semantic_description"] = "图片区域，建议结合上下文补充业务描述。"

        return blocks, qwen_calls, warnings

    def _summarize_table(self, table_md: str) -> str:
        rows = [line for line in table_md.splitlines() if line.strip().startswith("|")]
        if not rows:
            return "表格区域，未识别到结构化行。"
        header = rows[0].strip("|").split("|")
        header = [c.strip() for c in header if c.strip()]
        return f"表格包含 {max(len(rows) - 2, 0)} 行数据，列字段可能包括：{', '.join(header[:8])}。"

    def _explain_formula(self, formula: str) -> str:
        compact = re.sub(r"\s+", " ", formula).strip()
        if not compact:
            return "公式区域，建议结合上下文补充语义说明。"
        preview = compact[:180]
        return f"公式表达式摘要：{preview}。建议在检索中关联变量定义与约束条件。"

    def _compose_markdown(self, blocks: List[Dict[str, Any]]) -> str:
        parts: List[str] = []
        for block in sorted(blocks, key=lambda x: x.get("order", 0)):
            text = block.get("normalized_content") or block.get("raw_content") or ""
            if not text:
                continue
            parts.append(text)
        return "\n\n".join(parts).strip()

    def _build_chunks(self, blocks: List[Dict[str, Any]], max_chars: int, overlap_chars: int) -> List[Dict[str, Any]]:
        entries: List[Dict[str, Any]] = []
        for block in blocks:
            btype = block.get("type", "text")
            raw = (block.get("normalized_content") or block.get("raw_content") or "").strip()
            desc = (block.get("semantic_description") or "").strip()

            if btype == "text":
                text = raw
            elif btype == "table":
                text = f"[表格]\n{desc}\n\n{raw}".strip()
            elif btype == "image":
                text = f"[图片]\n{desc}".strip()
            elif btype == "formula":
                text = f"[公式]\n{desc}\n\n{raw}".strip()
            else:
                text = raw or desc

            if text:
                entries.append(
                    {
                        "block_id": block.get("block_id"),
                        "page": block.get("page"),
                        "type": btype,
                        "text": text,
                    }
                )

        chunks: List[Dict[str, Any]] = []
        current = ""
        refs: List[str] = []
        pages: List[int] = []

        def flush_chunk() -> None:
            nonlocal current, refs, pages
            if not current:
                return
            chunk_id = f"c{len(chunks)}"
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "text": current,
                    "block_refs": [r for r in refs if r],
                    "page_refs": sorted(set([p for p in pages if isinstance(p, int)])),
                    "token_estimate": max(1, len(current) // 4),
                    "quality_score": 0.8,
                }
            )
            current = ""
            refs = []
            pages = []

        for entry in entries:
            piece = entry["text"]
            piece_page = entry.get("page")
            piece_ref = entry.get("block_id")

            if not current:
                current = piece
                refs = [piece_ref] if piece_ref else []
                pages = [piece_page] if isinstance(piece_page, int) else []
                continue

            if len(current) + len(piece) + 2 <= max_chars:
                current += "\n\n" + piece
                if piece_ref:
                    refs.append(piece_ref)
                if isinstance(piece_page, int):
                    pages.append(piece_page)
                continue

            flush_chunk()
            if overlap_chars > 0 and len(piece) > overlap_chars:
                current = piece[-overlap_chars:]
            else:
                current = piece
            refs = [piece_ref] if piece_ref else []
            pages = [piece_page] if isinstance(piece_page, int) else []

        flush_chunk()
        return chunks


service = PDF2MDService()
mcp = FastMCP(name="PDF2MD", mask_error_details=True)


@mcp.tool("health_check")
async def health_check() -> str:
    return json.dumps(service.health_check(), ensure_ascii=False)


@mcp.tool("parse_standard_pdf")
async def parse_standard_pdf(file_path: str, options: Optional[Dict[str, Any]] = None) -> str:
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, service.parse_standard_pdf, file_path, options)
    except Exception as exc:
        result = {
            "success": False,
            "error": str(exc),
            "warnings": [],
            "errors": [str(exc)],
        }
    return json.dumps(result, ensure_ascii=False)


@mcp.tool("prepare_rag_chunks")
async def prepare_rag_chunks(file_path: str, options: Optional[Dict[str, Any]] = None) -> str:
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, service.prepare_rag_chunks, file_path, options)
    except Exception as exc:
        result = {
            "success": False,
            "error": str(exc),
            "warnings": [],
            "errors": [str(exc)],
        }
    return json.dumps(result, ensure_ascii=False)
