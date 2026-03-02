#!/usr/bin/env python3
import hashlib
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .vlm_client import UnifiedVLMClient


@dataclass
class RuntimeConfig:
    input_dir: str = os.getenv("PDF2MD_INPUT_DIR", "./data/input")
    output_dir: str = os.getenv("MINERU_OUTPUT_DIR", os.getenv("PDF2MD_OUTPUT_DIR", "./data/output"))
    max_file_size_mb: int = int(os.getenv("PDF2MD_MAX_FILE_SIZE_MB", "100"))
    max_pages: int = int(os.getenv("PDF2MD_MAX_PAGES", "500"))
    max_vlm_calls_per_doc: int = int(os.getenv("PDF2MD_MAX_VLM_CALLS_PER_DOC", "40"))
    vlm_timeout_sec: int = int(os.getenv("PDF2MD_VLM_TIMEOUT_SEC", "60"))
    vlm_max_retries: int = int(os.getenv("PDF2MD_VLM_MAX_RETRIES", "2"))
    allow_external_vlm: bool = os.getenv("PDF2MD_ALLOW_EXTERNAL_VLM", "true").lower() in {"1", "true", "yes"}


class GBDocumentParser:
    def __init__(self) -> None:
        self.cfg = RuntimeConfig()
        Path(self.cfg.output_dir).mkdir(parents=True, exist_ok=True)
        self.vlm = UnifiedVLMClient(timeout_sec=self.cfg.vlm_timeout_sec, max_retries=self.cfg.vlm_max_retries)

    def health(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "service": "PDF2MD",
            "version": "2.1.0",
            "mineru_available": bool(importlib.util.find_spec("magic_pdf") or importlib.util.find_spec("mineru")),
            "vlm_enabled": self.vlm.enabled and self.cfg.allow_external_vlm,
            "vlm": self.vlm.get_effective_config(),
        }

    def parse_standard_pdf(self, file_path: str) -> Dict[str, Any]:
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

            markdown = self._fix_markdown_format(markdown or self._compose_markdown(blocks))

            # 两阶段VLM处理：布局识别 + 内容过滤（如果启用）
            if self.cfg.allow_external_vlm and self.vlm.enabled:
                markdown = self._filter_markdown_with_vlm_layout(
                    markdown, resolved, work_dir
                )

            elapsed_ms = int((time.time() - started) * 1000)
            return {
                "success": True,
                "run_id": run_id,
                "markdown": markdown,
                "layout_blocks": blocks,
                "stats": {
                    "elapsed_ms": elapsed_ms,
                    "block_count": len(blocks),
                    "parser_engine": parser_engine,
                },
                "warnings": warnings,
                "errors": [],
            }

    def export_renderable_markdown(self, file_path: str, output_path: Optional[str] = None) -> Dict[str, Any]:
        result = self.parse_standard_pdf(file_path)
        if not result.get("success"):
            return result

        markdown = self._fix_markdown_format(result.get("markdown", ""))
        if output_path:
            out = Path(output_path).expanduser().resolve()
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(markdown, encoding="utf-8")
            return {"success": True, "path": str(out), "markdown": markdown}
        return {"success": True, "markdown": markdown}

    def extract_formulas(self, file_path: str, pages: Optional[List[int]] = None) -> List[Dict[str, Any]]:
        resolved = self._validate_file(file_path)
        result = self.parse_standard_pdf(str(resolved))
        if not result.get("success"):
            return [{"error": "; ".join(result.get("errors", [])) or "parse failed"}]

        selected = self._page_selector(pages)
        formulas: List[Dict[str, Any]] = []

        for block in result.get("layout_blocks", []):
            if block.get("type") != "formula":
                continue
            page = block.get("page")
            if selected is not None and isinstance(page, int) and page not in selected:
                continue
            formulas.append(
                {
                    "page": page,
                    "latex": (block.get("normalized_content") or block.get("raw_content") or "").strip(),
                    "bbox": block.get("bbox"),
                }
            )

        if not formulas:
            formulas.extend(self._extract_formulas_from_markdown(result.get("markdown", ""), selected))

        # Final fallback: ask VLM to extract page-level formulas where formula-like text exists.
        if not formulas and self.cfg.allow_external_vlm and self.vlm.enabled:
            formulas.extend(self._extract_formulas_via_vlm(resolved, selected))

        return formulas

    def extract_tables(self, file_path: str, pages: Optional[List[int]] = None) -> List[Dict[str, Any]]:
        resolved = self._validate_file(file_path)
        result = self.parse_standard_pdf(str(resolved))
        if not result.get("success"):
            return [{"error": "; ".join(result.get("errors", [])) or "parse failed"}]

        selected = self._page_selector(pages)
        tables: List[Dict[str, Any]] = []

        for block in result.get("layout_blocks", []):
            if block.get("type") != "table":
                continue
            page = block.get("page")
            if selected is not None and isinstance(page, int) and page not in selected:
                continue
            tables.append(
                {
                    "page": page,
                    "markdown": (block.get("normalized_content") or block.get("raw_content") or "").strip(),
                    "bbox": block.get("bbox"),
                }
            )

        if not tables:
            tables.extend(self._extract_tables_from_markdown(result.get("markdown", ""), selected))

        if not tables and self.cfg.allow_external_vlm and self.vlm.enabled:
            tables.extend(self._extract_tables_via_vlm(resolved, selected))

        return tables

    def extract_images_with_caption(self, file_path: str, pages: Optional[List[int]] = None) -> List[Dict[str, Any]]:
        resolved = self._validate_file(file_path)
        selected = self._page_selector(pages)
        run_dir = Path(self.cfg.output_dir) / f"images_{int(time.time())}_{hashlib.sha1(str(resolved).encode()).hexdigest()[:8]}"
        run_dir.mkdir(parents=True, exist_ok=True)

        page_images = self._render_page_images_to_dir(resolved, run_dir)
        results: List[Dict[str, Any]] = []
        calls = 0
        for page, image_path in sorted(page_images.items()):
            if selected is not None and page not in selected:
                continue

            caption = ""
            if self.cfg.allow_external_vlm and self.vlm.enabled and calls < self.cfg.max_vlm_calls_per_doc:
                caption = self.vlm.recognize_complex_content(image_path, "figure_caption")
                calls += 1

            results.append(
                {
                    "page": page,
                    "path": str(image_path),
                    "caption": caption or f"第 {page} 页图像区域",
                    "bbox": None,
                }
            )

        return results

    def chunk_for_rag(self, file_path: str, chunk_size: int = 500, include_images: bool = True) -> List[Dict[str, Any]]:
        resolved = self._validate_file(file_path)
        result = self.parse_standard_pdf(str(resolved))
        if not result.get("success"):
            return [{"error": "; ".join(result.get("errors", [])) or "parse failed"}]

        blocks = result.get("layout_blocks", [])
        chunks = self._build_chunks(blocks, max_chars=max(200, chunk_size), overlap_chars=max(0, chunk_size // 10))

        image_lookup: Dict[int, List[Dict[str, Any]]] = {}
        if include_images:
            for item in self.extract_images_with_caption(str(resolved)):
                page = item.get("page")
                if isinstance(page, int):
                    image_lookup.setdefault(page, []).append(item)

        final: List[Dict[str, Any]] = []
        source = resolved.name
        for i, chunk in enumerate(chunks):
            page_refs = chunk.get("page_refs", [])
            image_refs: List[Dict[str, Any]] = []
            if include_images:
                for p in page_refs:
                    image_refs.extend(image_lookup.get(p, []))
            final.append(
                {
                    "content": chunk.get("text", ""),
                    "metadata": {
                        "source": source,
                        "page_refs": page_refs,
                        "block_refs": chunk.get("block_refs", []),
                        "types": chunk.get("types", []),
                    },
                    "image_refs": image_refs,
                    "chunk_id": f"chunk_{i}",
                }
            )
        return final

    def check_watermark(self, file_path: str) -> Dict[str, Any]:
        resolved = self._validate_file(file_path)
        locations: List[Dict[str, Any]] = []
        keywords = ["watermark", "机密", "仅供", "内部", "confidential", "复印无效"]

        try:
            import fitz

            doc = fitz.open(str(resolved))
            for i, page in enumerate(doc, start=1):
                text = (page.get_text("text") or "").lower()
                if any(k.lower() in text for k in keywords):
                    locations.append({"page": i, "signal": "text-keyword"})
            doc.close()
        except Exception as exc:
            return {"has_watermark": False, "locations": [], "warning": str(exc)}

        # VLM hint fallback (first page only) when text signal absent.
        if not locations and self.cfg.allow_external_vlm and self.vlm.enabled:
            try:
                run_dir = Path(self.cfg.output_dir) / f"wm_{int(time.time())}"
                run_dir.mkdir(parents=True, exist_ok=True)
                pages = self._render_page_images_to_dir(resolved, run_dir, max_pages=1)
                first_image = pages.get(1)
                if first_image:
                    desc = self.vlm.recognize_complex_content(str(first_image), "general").lower()
                    if any(k in desc for k in ["watermark", "水印", "机密"]):
                        locations.append({"page": 1, "signal": "vlm-hint"})
            except Exception:
                pass

        return {"has_watermark": len(locations) > 0, "locations": locations}

    def get_layout_info(self, file_path: str, page: int = 1) -> Dict[str, Any]:
        resolved = self._validate_file(file_path)
        result = self.parse_standard_pdf(str(resolved))
        if not result.get("success"):
            return {"blocks": [], "error": "; ".join(result.get("errors", [])) or "parse failed"}

        blocks = result.get("layout_blocks", [])
        filtered = [b for b in blocks if b.get("page") in {None, page}]
        return {
            "page": page,
            "blocks": filtered,
            "count": len(filtered),
            "stats": self._layout_stats(filtered),
        }

    def get_document_info(self, file_path: str) -> Dict[str, Any]:
        resolved = self._validate_file(file_path)
        try:
            import fitz

            doc = fitz.open(str(resolved))
            first = doc[0]
            page_count = len(doc)
            info = {
                "pages": page_count,
                "width": first.rect.width,
                "height": first.rect.height,
                "is_scanned": self._check_is_scanned(doc),
                "file_size_bytes": resolved.stat().st_size,
                "filename": resolved.name,
            }
            doc.close()
            return info
        except Exception as exc:
            return {"error": str(exc)}

    def _validate_file(self, file_path: str) -> Path:
        path = Path(file_path).expanduser()
        if not path.is_absolute():
            path = Path(self.cfg.input_dir).joinpath(path)
        path = path.resolve()

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

        legacy_md, legacy_blocks, legacy_warning = self._parse_with_legacy_magic_pdf(pdf_path, work_dir)
        warnings.extend(legacy_warning)
        if legacy_md.strip() and legacy_blocks:
            return legacy_md, legacy_blocks, warnings, "magic-pdf"

        cli_md, cli_blocks, cli_warning = self._parse_with_mineru_cli(pdf_path, work_dir)
        warnings.extend(cli_warning)
        if cli_md.strip() and cli_blocks:
            return cli_md, cli_blocks, warnings, "mineru-cli"

        return "", [], warnings, "mineru-unavailable"

    def _parse_with_legacy_magic_pdf(self, pdf_path: Path, work_dir: str) -> Tuple[str, List[Dict[str, Any]], List[str]]:
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
            return markdown, blocks, warnings
        except Exception as exc:
            warnings.append(f"Legacy magic_pdf parse failed: {exc}")
            return "", [], warnings

    def _parse_with_mineru_cli(self, pdf_path: Path, work_dir: str) -> Tuple[str, List[Dict[str, Any]], List[str]]:
        warnings: List[str] = []
        try:
            cmd = [
                os.getenv("PDF2MD_PYTHON_BIN", sys.executable or "python"),
                "-m",
                "mineru.cli.client",
                "-p",
                str(pdf_path),
                "-o",
                work_dir,
                "-b",
                os.getenv("PDF2MD_MINERU_BACKEND", "pipeline"),
                "-m",
                os.getenv("PDF2MD_MINERU_METHOD", "auto"),
                "-l",
                os.getenv("PDF2MD_MINERU_LANG", "ch"),
            ]
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=int(os.getenv("PDF2MD_MINERU_TIMEOUT_SEC", "300")),
                check=False,
            )
            if completed.returncode != 0:
                warnings.append(
                    f"MinerU CLI parse failed (exit={completed.returncode}): {(completed.stderr or '').strip()[:400]}"
                )
                return "", [], warnings

            markdown = self._read_mineru_cli_markdown(pdf_path=pdf_path, output_dir=Path(work_dir))
            blocks = self._markdown_to_blocks(markdown)
            if not markdown.strip() or not blocks:
                warnings.append("MinerU CLI completed but produced empty markdown")
                return "", [], warnings
            return markdown, blocks, warnings
        except Exception as exc:
            warnings.append(f"MinerU CLI invocation failed: {exc}")
            return "", [], warnings

    def _read_mineru_cli_markdown(self, pdf_path: Path, output_dir: Path) -> str:
        name = pdf_path.stem
        candidates = [
            output_dir / name / "auto" / f"{name}.md",
            output_dir / name / "txt" / f"{name}.md",
            output_dir / name / "ocr" / f"{name}.md",
            output_dir / name / "hybrid_auto" / f"{name}.md",
            output_dir / name / "hybrid_txt" / f"{name}.md",
            output_dir / name / "hybrid_ocr" / f"{name}.md",
            output_dir / name / "vlm" / f"{name}.md",
        ]
        for path in candidates:
            if path.exists() and path.is_file():
                return path.read_text(encoding="utf-8", errors="ignore")
        return ""

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
        page_num = 1

        def flush_text() -> None:
            nonlocal order
            text = "\n".join(buf).strip()
            if text:
                blocks.append(
                    {
                        "block_id": f"b{order}",
                        "page": page_num,
                        "type": "text",
                        "bbox": None,
                        "raw_content": text,
                        "normalized_content": text,
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

            page_match = re.match(r"^\s*#*\s*第\s*(\d+)\s*页", stripped)
            if page_match:
                flush_text()
                page_num = int(page_match.group(1))
                i += 1
                continue

            if stripped.startswith("!") and "(" in stripped and ")" in stripped:
                flush_text()
                blocks.append(
                    {
                        "block_id": f"b{order}",
                        "page": page_num,
                        "type": "image",
                        "bbox": None,
                        "raw_content": stripped,
                        "normalized_content": stripped,
                        "order": order,
                    }
                )
                order += 1
                i += 1
                continue

            if stripped.startswith("$$"):
                flush_text()
                formula_lines = [line]
                i += 1
                while i < len(lines):
                    formula_lines.append(lines[i])
                    if lines[i].strip().endswith("$$") and lines[i].strip() != "$$":
                        i += 1
                        break
                    if lines[i].strip() == "$$":
                        i += 1
                        break
                    i += 1
                formula_text = "\n".join(formula_lines).strip()
                blocks.append(
                    {
                        "block_id": f"b{order}",
                        "page": page_num,
                        "type": "formula",
                        "bbox": None,
                        "raw_content": formula_text,
                        "normalized_content": formula_text,
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
                table_text = "\n".join(table_lines).strip()
                blocks.append(
                    {
                        "block_id": f"b{order}",
                        "page": page_num,
                        "type": "table",
                        "bbox": None,
                        "raw_content": table_text,
                        "normalized_content": table_text,
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
                if not cleaned:
                    continue
                blocks.append(
                    {
                        "block_id": f"b{order}",
                        "page": page_index,
                        "type": "text",
                        "bbox": None,
                        "raw_content": cleaned,
                        "normalized_content": cleaned,
                        "order": order,
                    }
                )
                markdown_parts.append(cleaned)
                order += 1

            doc.close()
            if not blocks:
                warnings.append("fitz fallback produced empty content")
            return "\n\n".join(markdown_parts).strip(), blocks, warnings
        except Exception as exc:
            warnings.append(f"fitz fallback failed: {exc}")
            return "", [], warnings

    def _render_page_images_to_dir(self, pdf_path: Path, out_dir: Path, max_pages: Optional[int] = None) -> Dict[int, Path]:
        page_images: Dict[int, Path] = {}
        try:
            import fitz

            doc = fitz.open(str(pdf_path))
            total = len(doc)
            end = min(total, max_pages) if isinstance(max_pages, int) and max_pages > 0 else total
            for i in range(end):
                page = doc[i]
                out = out_dir / f"page_{i + 1}.png"
                page.get_pixmap(dpi=150).save(str(out))
                page_images[i + 1] = out
            doc.close()
        except Exception:
            return {}
        return page_images

    def _compose_markdown(self, blocks: List[Dict[str, Any]]) -> str:
        parts: List[str] = []
        for block in sorted(blocks, key=lambda x: x.get("order", 0)):
            text = block.get("normalized_content") or block.get("raw_content") or ""
            if text:
                parts.append(text)
        return "\n\n".join(parts).strip()

    def _build_chunks(self, blocks: List[Dict[str, Any]], max_chars: int, overlap_chars: int) -> List[Dict[str, Any]]:
        entries: List[Dict[str, Any]] = []
        for block in blocks:
            text = (block.get("normalized_content") or block.get("raw_content") or "").strip()
            if not text:
                continue
            btype = block.get("type", "text")
            if btype == "formula":
                payload = f"[FORMULA]\n{text}"
            elif btype == "table":
                payload = f"[TABLE]\n{text}"
            elif btype == "image":
                payload = f"[IMAGE]\n{text}"
            else:
                payload = text

            entries.append(
                {
                    "block_id": block.get("block_id"),
                    "page": block.get("page"),
                    "type": btype,
                    "text": payload,
                }
            )

        chunks: List[Dict[str, Any]] = []
        current = ""
        refs: List[str] = []
        pages: List[int] = []
        types: List[str] = []

        def flush_chunk() -> None:
            nonlocal current, refs, pages, types
            if not current:
                return
            chunks.append(
                {
                    "text": current,
                    "block_refs": [r for r in refs if r],
                    "page_refs": sorted(set([p for p in pages if isinstance(p, int)])),
                    "types": sorted(set(types)),
                }
            )
            current = ""
            refs = []
            pages = []
            types = []

        for entry in entries:
            piece = entry["text"]
            btype = entry.get("type", "text")
            atomic = btype in {"formula", "table", "image"}

            if not current:
                current = piece
                refs = [entry.get("block_id")] if entry.get("block_id") else []
                pages = [entry.get("page")] if isinstance(entry.get("page"), int) else []
                types = [btype]
                continue

            if not atomic and len(current) + len(piece) + 2 <= max_chars:
                current += "\n\n" + piece
                if entry.get("block_id"):
                    refs.append(entry.get("block_id"))
                if isinstance(entry.get("page"), int):
                    pages.append(entry.get("page"))
                types.append(btype)
                continue

            flush_chunk()
            current = piece[-overlap_chars:] if (not atomic and overlap_chars > 0 and len(piece) > overlap_chars) else piece
            refs = [entry.get("block_id")] if entry.get("block_id") else []
            pages = [entry.get("page")] if isinstance(entry.get("page"), int) else []
            types = [btype]

        flush_chunk()
        return chunks

    def _filter_markdown_with_vlm_layout(self, markdown: str, pdf_path: Path, work_dir: str) -> str:
        """使用两阶段VLM处理过滤页眉/页脚/页码。

        阶段1: 对每页图片进行布局识别，标记页眉/页脚/页码区域
        阶段2: 使用布局信息过滤markdown中的噪音

        Args:
            markdown: 原始markdown文本
            pdf_path: PDF文件路径
            work_dir: 工作目录，用于保存临时图片

        Returns:
            过滤后的干净markdown文本
        """
        import re

        # 渲染页面图片
        page_images = self._render_page_images_to_dir(
            pdf_path, Path(work_dir), max_pages=None
        )

        if not page_images:
            return markdown

        # 按页码排序
        sorted_pages = sorted(page_images.items())

        # 收集所有需要过滤的文本模式
        filter_patterns = {
            "headers": set(),
            "footers": set(),
            "page_numbers": set()
        }

        # 阶段1: 对每页进行布局识别
        for page_num, image_path in sorted_pages:
            try:
                layout_info = self.vlm.recognize_layout(str(image_path))

                # 收集页眉模式
                for header in layout_info.get("header", []):
                    filter_patterns["headers"].add(header)

                # 收集页脚模式
                for footer in layout_info.get("footer", []):
                    filter_patterns["footers"].add(footer)

                # 收集页码模式
                page_num_text = layout_info.get("page_number", "")
                if page_num_text:
                    filter_patterns["page_numbers"].add(page_num_text)

            except Exception as e:
                # 布局识别失败时继续处理下一页
                pass

        # 阶段2: 根据收集的模式过滤markdown
        if not any(filter_patterns.values()):
            # 没有识别到任何需要过滤的内容
            return markdown

        lines = markdown.split('\n')
        filtered_lines = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                filtered_lines.append(line)
                continue

            should_filter = False

            # 检查是否匹配页眉
            for header in filter_patterns["headers"]:
                if header.lower() in stripped.lower():
                    should_filter = True
                    break

            # 检查是否匹配页脚
            if not should_filter:
                for footer in filter_patterns["footers"]:
                    if footer.lower() in stripped.lower():
                        should_filter = True
                        break

            # 检查是否匹配页码（包括"## 第X页"格式）
            if not should_filter:
                for page_num in filter_patterns["page_numbers"]:
                    if page_num in stripped:
                        should_filter = True
                        break

                # 检查"## 第X页"格式
                if re.match(r'^##\s*第\s*\d+\s*页\s*$', stripped):
                    should_filter = True

            if not should_filter:
                filtered_lines.append(line)

        return '\n'.join(filtered_lines)

    def _fix_markdown_format(self, markdown: str) -> str:
        md = markdown.replace("\r\n", "\n")
        md = re.sub(r"\n{3,}", "\n\n", md)
        return md.strip() + "\n"

    def _extract_formulas_from_markdown(self, markdown: str, selected_pages: Optional[set[int]]) -> List[Dict[str, Any]]:
        formulas: List[Dict[str, Any]] = []
        for m in re.finditer(r"\$\$([\s\S]*?)\$\$", markdown):
            latex = m.group(1).strip()
            if latex:
                formulas.append({"page": None, "latex": latex, "bbox": None})
        for m in re.finditer(r"\\\[([\s\S]*?)\\\]", markdown):
            latex = m.group(1).strip()
            if latex:
                formulas.append({"page": None, "latex": latex, "bbox": None})
        return formulas

    def _extract_tables_from_markdown(self, markdown: str, selected_pages: Optional[set[int]]) -> List[Dict[str, Any]]:
        tables: List[Dict[str, Any]] = []
        current: List[str] = []
        for line in markdown.splitlines():
            stripped = line.strip()
            if stripped.startswith("|") and stripped.endswith("|"):
                current.append(line)
                continue
            if current:
                table_md = "\n".join(current).strip()
                if table_md:
                    tables.append({"page": None, "markdown": table_md, "bbox": None})
                current = []
        if current:
            table_md = "\n".join(current).strip()
            if table_md:
                tables.append({"page": None, "markdown": table_md, "bbox": None})
        return tables

    def _extract_formulas_via_vlm(self, pdf_path: Path, selected_pages: Optional[set[int]]) -> List[Dict[str, Any]]:
        run_dir = Path(self.cfg.output_dir) / f"formula_{int(time.time())}"
        run_dir.mkdir(parents=True, exist_ok=True)
        page_images = self._render_page_images_to_dir(pdf_path, run_dir)

        results: List[Dict[str, Any]] = []
        calls = 0
        for page, image in sorted(page_images.items()):
            if selected_pages is not None and page not in selected_pages:
                continue
            if calls >= self.cfg.max_vlm_calls_per_doc:
                break
            latex = self.vlm.recognize_complex_content(str(image), "formula")
            calls += 1
            if latex.strip():
                results.append({"page": page, "latex": latex.strip(), "bbox": None})
        return results

    def _extract_tables_via_vlm(self, pdf_path: Path, selected_pages: Optional[set[int]]) -> List[Dict[str, Any]]:
        run_dir = Path(self.cfg.output_dir) / f"table_{int(time.time())}"
        run_dir.mkdir(parents=True, exist_ok=True)
        page_images = self._render_page_images_to_dir(pdf_path, run_dir)

        results: List[Dict[str, Any]] = []
        calls = 0
        for page, image in sorted(page_images.items()):
            if selected_pages is not None and page not in selected_pages:
                continue
            if calls >= self.cfg.max_vlm_calls_per_doc:
                break
            table_md = self.vlm.recognize_complex_content(str(image), "table")
            calls += 1
            if "|" in table_md:
                results.append({"page": page, "markdown": table_md.strip(), "bbox": None})
        return results

    def _page_selector(self, pages: Optional[List[int]]) -> Optional[set[int]]:
        if pages is None:
            return None
        valid = set()
        for p in pages:
            if isinstance(p, int) and p > 0:
                valid.add(p)
        return valid

    def _layout_stats(self, blocks: List[Dict[str, Any]]) -> Dict[str, int]:
        stats = {"text": 0, "table": 0, "formula": 0, "image": 0, "other": 0}
        for b in blocks:
            t = b.get("type", "other")
            if t not in stats:
                t = "other"
            stats[t] += 1
        return stats

    def _check_is_scanned(self, doc: Any) -> bool:
        try:
            text = doc[0].get_text("text") or ""
            return len(text.strip()) < 50
        except Exception:
            return False
