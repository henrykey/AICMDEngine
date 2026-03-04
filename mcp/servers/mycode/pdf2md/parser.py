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

try:
    from .vlm_client import UnifiedVLMClient
except ImportError:
    # 直接导入（作为脚本运行时）
    from vlm_client import UnifiedVLMClient


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

    def process_single_page(
        self,
        pdf_path: str,
        page_num: int
    ) -> Dict[str, Any]:
        """
        处理PDF单页，返回结构化结果

        这是PDF2MD的核心方法，被MCP工具调用

        Args:
            pdf_path: PDF文件路径
            page_num: 页码（从1开始）

        Returns:
            {
                "page_num": 18,
                "page_type": "normal",  # cover | toc | blank | normal
                "chapters": [...],
                "rag": {
                    "summary": "...",
                    "content": "...",
                    "elements": [...],
                    "keywords": [...]
                },
                "render": {
                    "markdown": "## 6.5 装运杆、装运螺栓或螺母\n\n..."
                },
                "elements": {
                    "tables": [...],
                    "figures": [...],
                    "formulas": [...]
                },
                "layout": {
                    "header": [...],
                    "footer": [...],
                    "page_number": "14"
                }
            }
        """
        started = time.time()
        resolved = self._validate_file(pdf_path)

        # 提取单页到临时PDF
        with tempfile.TemporaryDirectory(prefix="pdf2md_single_page_") as work_dir:
            # 1. 提取单页
            single_page_pdf = self._extract_single_page(resolved, page_num, work_dir)

            # 2. 渲染页面图像
            page_image = self._render_page_image(single_page_pdf, page_num, work_dir)

            # 3. VLM布局识别
            layout_info = self._recognize_page_layout(page_image)

            # 4. 解析单页内容
            markdown, blocks, parser_engine = self._parse_single_page_content(single_page_pdf, work_dir)

            # 5. 提取章节信息
            chapters = self._extract_chapters_from_markdown(markdown)

            # 6. 识别结构化元素（表/图/公式）
            elements = self._extract_elements_from_page(markdown, page_image, work_dir)

            # 7. 生成RAG文本
            rag_content = self._generate_rag_content(markdown, chapters, elements)

            # 8. 生成Render MD
            render_content = self._generate_render_content(markdown, layout_info)

            elapsed_ms = int((time.time() - started) * 1000)

            return {
                "page_num": page_num,
                "page_type": layout_info.get("page_type", "normal"),
                "chapters": chapters,
                "rag": {
                    "summary": self._generate_page_summary(markdown, chapters),
                    "content": rag_content["content"],
                    "elements": rag_content["elements"],
                    "keywords": self._extract_keywords(markdown)
                },
                "render": {
                    "markdown": render_content
                },
                "elements": elements,
                "layout": {
                    "header": layout_info.get("header", []),
                    "footer": layout_info.get("footer", []),
                    "page_number": layout_info.get("page_number", "")
                },
                "stats": {
                    "elapsed_ms": elapsed_ms,
                    "parser_engine": parser_engine
                }
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
            print(f"[DEBUG] VLM enabled: {self.vlm.enabled}, allow_external_vlm: {self.cfg.allow_external_vlm}")
            if self.cfg.allow_external_vlm and self.vlm.enabled:
                print(f"[DEBUG] 调用VLM布局识别过滤...")
                markdown_before = markdown
                markdown = self._filter_markdown_with_vlm_layout(
                    markdown, resolved, work_dir
                )
                print(f"[DEBUG] VLM过滤前: {len(markdown_before)} 字符, 过滤后: {len(markdown)} 字符, 减少: {len(markdown_before) - len(markdown)} 字符")

                # 图像描述：用VLM描述替换图片乱码
                print(f"[DEBUG] 调用VLM图像描述...")
                markdown_before_images = markdown
                markdown = self._replace_image_garbage_with_vlm_caption(
                    markdown, resolved, work_dir
                )
                print(f"[DEBUG] 图像描述前: {len(markdown_before_images)} 字符, 描述后: {len(markdown)} 字符, 变化: {len(markdown) - len(markdown_before_images)} 字符")

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
        toc_pages = set()  # 记录目录页的页码
        for page_num, image_path in sorted_pages:
            try:
                layout_info = self.vlm.recognize_layout(str(image_path))
                page_type = layout_info.get("page_type", "normal")

                print(f"[DEBUG] 第{page_num}页: page_type={page_type}")

                # 如果是目录页，记录下来，并特殊处理
                if page_type == "toc":
                    toc_pages.add(page_num)
                    print(f"[DEBUG] 检测到目录页: 第{page_num}页")

                    # 对目录页，过滤掉页眉中的目录标题（"目 次"、"目录"等）
                    toc_keywords = {"目 次", "目录", "contents", "table of contents"}
                    headers = layout_info.get("header", [])
                    for header in headers:
                        # 只添加不是目录标题的页眉
                        if header.lower() not in toc_keywords:
                            filter_patterns["headers"].add(header)
                        else:
                            print(f"[DEBUG] 跳过目录标题: '{header}'")
                else:
                    # 非目录页，正常收集页眉模式
                    for header in layout_info.get("header", []):
                        filter_patterns["headers"].add(header)

                # 收集页脚模式（所有页面都收集）
                for footer in layout_info.get("footer", []):
                    filter_patterns["footers"].add(footer)

                # 收集页码模式
                page_num_text = layout_info.get("page_number", "")
                if page_num_text:
                    filter_patterns["page_numbers"].add(page_num_text)

            except Exception as e:
                # 布局识别失败时继续处理下一页
                print(f"[DEBUG] 第{page_num}页布局识别失败: {e}")
                pass

        if toc_pages:
            print(f"[DEBUG] 检测到目录页: {toc_pages}")

        # 阶段2: 根据收集的模式过滤markdown
        if not any(filter_patterns.values()):
            # 没有识别到任何需要过滤的内容
            print(f"[DEBUG] 没有识别到需要过滤的内容")
            return markdown

        print(f"[DEBUG] 过滤模式: {filter_patterns}")

        lines = markdown.split('\n')
        filtered_lines = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                filtered_lines.append(line)
                continue

            should_filter = False

            # 检查是否匹配页眉（使用双向包含检查）
            for header in filter_patterns["headers"]:
                # 检查header是否包含在line中，或line是否包含header的核心部分
                header_lower = header.lower()
                stripped_lower = stripped.lower()

                # 完全包含
                if header_lower in stripped_lower:
                    should_filter = True
                    print(f"[DEBUG] 过滤页眉: '{stripped}' 匹配 '{header}'")
                    break

                # 检查标准编号的核心部分（如"GB/T 16749"）
                # 提取header和line中的数字字母部分进行匹配
                # 保留字母数字汉字，但去除常见的OCR干扰字符
                header_core = re.sub(r'[^\w\u4e00-\u9fff]', '', header_lower)
                line_core = re.sub(r'[^\w\u4e00-\u9fff]', '', stripped_lower)

                # 进一步去除常见的中文字符干扰（如"一"可能是破折号的误识别）
                # 只保留字母、数字和有意义的汉字（长度>1的汉字）
                def extract_meaningful_core(text):
                    # 提取字母数字序列
                    alnum_parts = re.findall(r'[a-z0-9]+', text)
                    alnum_core = ''.join(alnum_parts)

                    # 提取有意义的汉字（排除单个常见字符）
                    chinese_parts = re.findall(r'[\u4e00-\u9fff]{2,}', text)
                    chinese_core = ''.join(chinese_parts)

                    return alnum_core + chinese_core

                header_core_clean = extract_meaningful_core(header_core)
                line_core_clean = extract_meaningful_core(line_core)

                # 双向匹配：header_core在line_core中 或 line_core在header_core中
                if header_core_clean and line_core_clean:
                    if header_core_clean in line_core_clean or line_core_clean in header_core_clean:
                        should_filter = True
                        print(f"[DEBUG] 过滤页眉(核心匹配): '{stripped}' 匹配 '{header}'")
                        print(f"[DEBUG]   header_core='{header_core_clean}' line_core='{line_core_clean}'")
                        break

            # 检查是否匹配页脚（使用双向包含检查）
            if not should_filter:
                for footer in filter_patterns["footers"]:
                    footer_lower = footer.lower()
                    stripped_lower = stripped.lower()

                    # 完全包含
                    if footer_lower in stripped_lower:
                        should_filter = True
                        print(f"[DEBUG] 过滤页脚: '{stripped}' 匹配 '{footer}'")
                        break

                    # 核心部分匹配（双向匹配）
                    footer_core = re.sub(r'[^\w\u4e00-\u9fff]', '', footer_lower)
                    line_core = re.sub(r'[^\w\u4e00-\u9fff]', '', stripped_lower)

                    if footer_core and line_core and len(footer_core) > 5 and len(line_core) > 5:
                        if footer_core in line_core or line_core in footer_core:
                            should_filter = True
                            print(f"[DEBUG] 过滤页脚(核心匹配): '{stripped}' 匹配 '{footer}'")
                            print(f"[DEBUG]   footer_core='{footer_core}' line_core='{line_core}'")
                            break

            # 检查是否匹配页码（包括"## 第X页"格式）
            if not should_filter:
                for page_num in filter_patterns["page_numbers"]:
                    if page_num in stripped:
                        should_filter = True
                        print(f"[DEBUG] 过滤页码: '{stripped}' 匹配 '{page_num}'")
                        break

                # 检查"## 第X页"格式
                if re.match(r'^##\s*第\s*\d+\s*页\s*$', stripped):
                    should_filter = True
                    print(f"[DEBUG] 过滤页码标记: '{stripped}'")

            if not should_filter:
                filtered_lines.append(line)

        print(f"[DEBUG] 过滤前: {len(lines)} 行, 过滤后: {len(filtered_lines)} 行")

        return '\n'.join(filtered_lines)

    def _replace_image_garbage_with_vlm_caption(self, markdown: str, pdf_path: Path, work_dir: str) -> str:
        """用VLM图像/表格描述替换markdown中的OCR乱码。

        策略：
        1. 先收集所有包含=的行（公式），一次性让VLM转LaTeX
        2. 检测连续的乱码行（短行、符号多、内容无意义）
        3. 查找上下文中的"图X"或"表X"引用
        4. 根据是图还是表，调用不同的VLM描述
        5. 用描述替换乱码部分
        """
        import re

        lines = markdown.split('\n')

        # 渲染页面图片（如果需要VLM描述）
        page_images = {}
        try:
            page_images = self._render_page_images_to_dir(pdf_path, Path(work_dir), max_pages=None)
        except Exception as e:
            print(f"[DEBUG] 渲染页面图片失败: {e}")
            return markdown

        # 第一步：收集所有包含=的行（公式）
        formula_line_indices = []
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped and '=' in stripped:
                formula_line_indices.append(i)

        # 如果有公式行，让VLM一次性识别整页的所有公式
        all_formulas_latex = []
        if formula_line_indices and page_images:
            first_page = min(page_images.keys())
            image_path = str(page_images[first_page])

            print(f"[DEBUG] 检测到 {len(formula_line_indices)} 个包含等号的行")
            print(f"[DEBUG] 调用VLM识别整页的所有公式...")

            try:
                caption = self.vlm.recognize_complex_content(image_path, "formula")
                if caption and caption.strip():
                    # VLM返回的公式（可能包含多个公式）
                    all_formulas_latex.append(caption)
                    print(f"[DEBUG] VLM识别到的公式:\n{caption}")
            except Exception as e:
                print(f"[DEBUG] VLM公式识别异常: {e}")

        # 第二步：处理所有行
        result_lines = []
        formula_inserted = False  # 标记公式是否已插入

        for i, line in enumerate(lines):
            stripped = line.strip()

            # 公式行：只在第一次遇到时插入LaTeX公式
            if i in formula_line_indices and all_formulas_latex and not formula_inserted:
                # 使用VLM识别的公式（所有公式在一次调用中返回）
                result_lines.append(f"\n$$\n{all_formulas_latex[0]}\n$$\n")
                print(f"[DEBUG] 第{i+1}行：插入VLM识别的公式")
                formula_inserted = True
                continue
            elif i in formula_line_indices and formula_inserted:
                # 后续的公式行跳过（不再重复插入）
                print(f"[DEBUG] 第{i+1}行：跳过（公式已插入）")
                continue

            # 新增：连续短行块检测（图片乱码特征）
            if stripped and len(stripped) < 5:
                # 检查是否是连续的短行块（>=5行连续短行）
                short_block_start = i
                short_lines_count = 0

                while i < len(lines):
                    next_line = lines[i].strip()
                    if next_line and len(next_line) < 5:
                        short_lines_count += 1
                        i += 1
                    else:
                        break

                # 如果连续短行>=5行，判定为图片/表格乱码
                if short_lines_count >= 5:
                    print(f"[DEBUG] 检测到短行块: {short_block_start+1}-{i}行，共{short_lines_count}行")

                    # 查找前面或后面的"图X"或"表X"引用
                    figure_name = self._find_figure_or_table_name(result_lines, short_block_start)

                    if page_images:
                        first_page = min(page_images.keys())
                        image_path = str(page_images[first_page])

                        task_type = "figure_caption"
                        if figure_name and "表" in figure_name:
                            task_type = "table"

                        print(f"[DEBUG] 调用VLM描述第{first_page}页的{task_type}...")

                        try:
                            if task_type == "table":
                                caption = self.vlm.recognize_complex_content(image_path, "table")
                                if caption and caption.strip():
                                    result_lines.append(f"\n**{figure_name}：** {caption}\n")
                                    print(f"[DEBUG] 表格描述: {caption}")
                                else:
                                    result_lines.append(f"\n**{figure_name}** (表格识别失败)\n")
                            else:
                                caption = self.vlm.recognize_complex_content(image_path, "figure_caption")
                                if caption and caption.strip():
                                    result_lines.append(f"\n**{figure_name}：** {caption}\n")
                                    print(f"[DEBUG] 图像描述: {caption}")
                                else:
                                    result_lines.append(f"\n**{figure_name}** (图像识别失败)\n")
                        except Exception as e:
                            print(f"[DEBUG] VLM描述异常: {e}")
                            if figure_name:
                                result_lines.append(f"\n**{figure_name}** (识别失败)\n")
                            else:
                                result_lines.append(f"\n**[图像]** (识别失败)\n")
                    else:
                        result_lines.append(f"\n**[图像]** (无可用图像)\n")

                    continue

            # 原有的乱码行检测（长行或符号密集行）
            if stripped and self._is_garbage_line(stripped):
                # 收集连续的乱码行
                garbage_start = i
                garbage_lines = []

                while i < len(lines) and self._is_garbage_line(lines[i].strip()):
                    garbage_lines.append(lines[i])
                    i += 1

                print(f"[DEBUG] 检测到乱码块: {garbage_start+1}-{i}行，共{len(garbage_lines)}行")

                # 检查是否是公式乱码块
                is_formula_block = self._is_formula_block(garbage_lines)

                # 查找前面最近的"图X"或"表X"引用
                figure_name = self._find_figure_or_table_name(result_lines, garbage_start)

                if page_images:
                    # 取第一个页面图像
                    first_page = min(page_images.keys())
                    image_path = str(page_images[first_page])

                    # 如果是公式块，使用公式描述
                    if is_formula_block:
                        print(f"[DEBUG] 检测到公式块，使用formula描述")
                        task_type = "formula"
                    else:
                        # 根据是图还是表，使用不同的描述任务
                        task_type = "figure_caption"  # 默认为图片
                        if figure_name and "表" in figure_name:
                            task_type = "table"

                    print(f"[DEBUG] 调用VLM描述第{first_page}页的{task_type}...")

                    try:
                        caption = self.vlm.recognize_complex_content(image_path, task_type)
                        if caption and caption.strip():
                            if task_type == "formula":
                                # 公式使用LaTeX格式
                                result_lines.append(f"\n$$\n{caption}\n$$\n")
                                print(f"[DEBUG] 公式(LaTeX): {caption}")
                            elif task_type == "table":
                                result_lines.append(f"\n**{figure_name}：** {caption}\n")
                                print(f"[DEBUG] 表格描述: {caption}")
                            else:
                                result_lines.append(f"\n**{figure_name}：** {caption}\n")
                                print(f"[DEBUG] 图像描述: {caption}")
                        else:
                            if task_type == "formula":
                                result_lines.append(f"\n$$\n\\text{{公式识别失败}}\n$$\n")
                            elif figure_name:
                                result_lines.append(f"\n**{figure_name}** (识别失败)\n")
                            else:
                                result_lines.append(f"\n**[图像]** (无法识别内容)\n")
                    except Exception as e:
                        print(f"[DEBUG] VLM描述异常: {e}")
                        if figure_name:
                            result_lines.append(f"\n**{figure_name}** (识别失败)\n")
                        else:
                            result_lines.append(f"\n**[图像]** (识别失败)\n")
                else:
                    result_lines.append(f"\n**[图像]** (无可用图像)\n")

                continue

            result_lines.append(line)
            i += 1

        return '\n'.join(result_lines)

    def _find_figure_or_table_name(self, lines: List[str], current_pos: int) -> str:
        """查找当前位置附近最近的"图X"或"表X"引用。

        向前和向后查找，寻找包含"图X"或"表X"的行
        """
        import re

        # 向前查找最多20行
        lookback = min(20, current_pos)
        start_idx = max(0, current_pos - lookback)

        for i in range(current_pos - 1, start_idx - 1, -1):
            if i < 0 or i >= len(lines):
                continue
            line = lines[i].strip()

            # 查找"图 数字"或"表 数字"模式
            figure_match = re.search(r'图\s*(\d+)', line)
            table_match = re.search(r'表\s*(\d+)', line)

            if figure_match:
                return f"图{figure_match.group(1)}"
            elif table_match:
                return f"表{table_match.group(1)}"

        # 向后查找最多10行
        lookforward = min(10, len(lines) - current_pos)
        for i in range(current_pos, min(current_pos + lookforward, len(lines))):
            line = lines[i].strip()

            # 查找"图 数字"或"表 数字"模式
            figure_match = re.search(r'图\s*(\d+)', line)
            table_match = re.search(r'表\s*(\d+)', line)

            if figure_match:
                return f"图{figure_match.group(1)}"
            elif table_match:
                return f"表{table_match.group(1)}"

        return ""

    def _is_garbage_line(self, line: str) -> bool:
        """判断一行文本是否是乱码。

        改进标准（更宽松）：
        1. 短行（长度<5）且主要是符号/数字
        2. 或者符号占比>60%
        3. 不包含完整的中文字句（2个以上连续汉字）
        """
        if not line:
            return False

        # 短行判定
        if len(line) < 5:
            # 检查是否包含有意义的中文
            chinese_matches = re.findall(r'[\u4e00-\u9fff]{2,}', line)
            if chinese_matches:
                return False  # 有连续2个以上汉字，不是乱码

            # 检查是否主要是符号和数字
            alnum_count = sum(1 for c in line if c.isalnum())
            symbol_count = len(line) - alnum_count

            # 符号占比>50% 或 纯数字/符号
            return symbol_count / len(line) > 0.5 if len(line) > 0 else True

        # 长行判定：符号占比>60%
        symbol_chars = 0
        has_chinese = False
        has_long_word = False

        for char in line:
            if char in '．·~`\'"-+=|!@#$%^&*()[]{}<>?/\\,.;: 　\t\n\r':
                symbol_chars += 1
            elif '\u4e00' <= char <= '\u9fff':
                has_chinese = True
            elif char.isalpha():
                if len(re.findall(r'[a-z]{4,}', line)) > 0:
                    has_long_word = True

        if has_chinese or has_long_word:
            return False

        return (symbol_chars / len(line)) > 0.6

    def _is_formula_block(self, lines: List[str]) -> bool:
        """判断一个文本块是否是数学公式。

        公式特征（改进版，更宽松以适应OCR错误）：
        1. 包含等号 =、≈、≠
        2. 包含希腊字母（α, β, γ, Δ, Σ, π等）
        3. 包含数学符号（+, -, ×, ÷, ±, ∫, √, ∑, ∏等）
        4. 包含上标下标标记（^, _）
        5. 变量+数字模式（OCR友好的公式特征）
        6. 括号/方括号密度高
        """
        import re

        if not lines:
            return False

        # 合并所有行用于分析
        combined = ' '.join(lines)

        # 检查是否包含等号或近似符号（公式的关键特征）
        has_equality = '=' in combined or '≈' in combined or '≠' in combined
        if not has_equality:
            # 即使没有等号，如果有多个公式特征也可能是公式
            pass

        # 检查公式特征指标
        formula_indicators = 0

        # 有等号或近似符号，强指标
        if has_equality:
            formula_indicators += 2

        # 希腊字母（OCR可能识别错误，降低权重）
        greek_pattern = r'[α-ωΑ-Ω]'
        if re.search(greek_pattern, combined):
            formula_indicators += 2

        # 数学符号（扩展：包含常见符号）
        math_symbols = r'[+\-×÷±∫√∑∏∂∇∈∞∩∪≈≠≤≥*/]'
        # 统计数学符号出现次数
        math_symbol_count = len(re.findall(math_symbols, combined))
        if math_symbol_count >= 2:
            formula_indicators += 2
        elif math_symbol_count >= 1:
            formula_indicators += 1

        # 分数格式（a/b 或类似）
        if re.search(r'\w+\s*/\s*\w+', combined):
            formula_indicators += 1

        # 上标下标
        if '^' in combined or '_' in combined:
            formula_indicators += 1

        # 括号/方括号嵌套（公式常见特征）
        # 检测嵌套括号 ( ... ( ... ) ... ) 或 [ ... [ ... ] ... ]
        if re.search(r'\(.+\(.+.*\)', combined) or re.search(r'\[.+\[.+.*\]', combined):
            formula_indicators += 1

        # 平方/立方等（OCR可能识别为数字2、3）
        if re.search(r'\^2|\^3|\²|\³|\s2\s|\s3\s', combined):
            formula_indicators += 1

        # 变量+数字模式（OCR友好）：字母后紧跟数字
        # 例如: A2, r3, m2 等
        if re.search(r'[a-zA-Z]\s*\d', combined):
            formula_indicators += 1

        # 判定：公式指标>=1 即认为是公式（降低阈值以适应OCR）
        return formula_indicators >= 1

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

    # ========== 单页处理辅助方法 ==========

    def _extract_single_page(self, pdf_path: Path, page_num: int, work_dir: str) -> Path:
        """从PDF中提取指定页到单独的PDF文件"""
        import fitz  # PyMuPDF
        
        output_path = Path(work_dir) / f"page_{page_num}.pdf"
        
        doc = fitz.open(str(pdf_path))
        if page_num < 1 or page_num > len(doc):
            doc.close()
            raise ValueError(f"页码{page_num}超出范围（1-{len(doc)}）")
        
        # 创建新文档只包含指定页
        new_doc = fitz.open()
        new_doc.insert_pdf(doc, from_page=page_num-1, to_page=page_num-1)
        new_doc.save(str(output_path))
        new_doc.close()
        doc.close()
        
        return output_path

    def _render_page_image(self, pdf_path: Path, page_num: int, work_dir: str) -> Path:
        """渲染PDF页面为图像"""
        import fitz
        
        output_path = Path(work_dir) / f"page_{page_num}.png"
        
        doc = fitz.open(str(pdf_path))
        page = doc[0]  # 只有一页
        mat = fitz.Matrix(2.0, 2.0)  # 2倍缩放
        pix = page.get_pixmap(matrix=mat)
        pix.save(str(output_path))
        doc.close()
        
        return output_path

    def _recognize_page_layout(self, image_path: Path) -> Dict[str, Any]:
        """使用VLM识别页面布局"""
        if not self.vlm.enabled:
            return {
                "page_type": "normal",
                "header": [],
                "footer": [],
                "page_number": "",
                "confidence": "low"
            }
        
        try:
            layout_info = self.vlm.recognize_layout(str(image_path))
            return layout_info
        except Exception as e:
            print(f"[ERROR] VLM布局识别失败: {e}")
            return {
                "page_type": "normal",
                "header": [],
                "footer": [],
                "page_number": "",
                "confidence": "low"
            }

    def _parse_single_page_content(self, pdf_path: Path, work_dir: str) -> Tuple[str, List[Dict], str]:
        """解析单页PDF内容"""
        # 使用现有的parse方法，但只处理单页
        markdown, blocks, warnings, parser_engine = self._parse_with_mineru(pdf_path, work_dir)
        
        if not markdown.strip() or not blocks:
            fb_markdown, fb_blocks, fb_warning = self._fallback_parse_with_fitz(pdf_path)
            warnings.extend(fb_warning)
            if fb_markdown.strip() and fb_blocks:
                markdown, blocks = fb_markdown, fb_blocks
                parser_engine = "fitz-fallback"
        
        markdown = self._fix_markdown_format(markdown or self._compose_markdown(blocks))
        
        # VLM过滤
        if self.cfg.allow_external_vlm and self.vlm.enabled:
            markdown = self._filter_markdown_with_vlm_layout(markdown, pdf_path, work_dir)
            markdown = self._replace_image_garbage_with_vlm_caption(markdown, pdf_path, work_dir)
        
        return markdown, blocks, parser_engine

    def _extract_chapters_from_markdown(self, markdown: str) -> List[Dict[str, Any]]:
        """从markdown中提取章节信息"""
        chapters = []
        lines = markdown.split('\n')
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            
            # 匹配章节号：数字.数字 或 附录X
            match = re.match(r'^(\d+(?:\.\d+)*)\s+(.+)$', stripped)
            if not match:
                # 尝试匹配附录
                match = re.match(r'^(附录[A-Z]?)\s*(.*)$', stripped)
            
            if match:
                chapter_num = match.group(1)
                chapter_title = match.group(2) if len(match.groups()) > 1 else ""
                
                # 计算层级
                level = 1
                if '.' in chapter_num:
                    level = chapter_num.count('.') + 1
                elif chapter_num.startswith("附录"):
                    level = 1
                
                chapters.append({
                    "num": chapter_num,
                    "title": chapter_title,
                    "level": level,
                    "line_start": i
                })
        
        return chapters

    def _extract_elements_from_page(
        self,
        markdown: str,
        image_path: Path,
        work_dir: str
    ) -> Dict[str, List[Dict]]:
        """识别页面中的结构化元素（表/图/公式）"""
        elements = {
            "tables": [],
            "figures": [],
            "formulas": []
        }
        
        lines = markdown.split('\n')
        
        # 查找表
        for i, line in enumerate(lines):
            if '|' in line and line.count('|') >= 4:
                table_match = re.search(r'(表\s*\d+[:：])', line)
                if table_match or self._is_table_block(lines, i):
                    table_name = self._find_figure_or_table_name(lines, i)
                    elements["tables"].append({
                        "id": f"table_{len(elements['tables']) + 1}",
                        "name": table_name or f"表{len(elements['tables']) + 1}",
                        "line": i,
                        "content": line
                    })
        
        # 查找公式
        for i, line in enumerate(lines):
            if '=' in line and len(line.strip()) > 5:
                elements["formulas"].append({
                    "id": f"formula_{len(elements['formulas']) + 1}",
                    "name": f"公式({len(elements['formulas']) + 1})",
                    "line": i,
                    "content": line.strip()
                })
        
        # 查找图（通过VLM描述）
        for i, line in enumerate(lines):
            if line.startswith("**") and "图" in line and "：" in line:
                elements["figures"].append({
                    "id": f"figure_{len(elements['figures']) + 1}",
                    "name": line.split("：")[0].replace("*", "").strip(),
                    "line": i,
                    "caption": line
                })
        
        return elements

    def _is_table_block(self, lines: List[str], start_idx: int) -> bool:
        """判断是否是表格块"""
        count = 0
        for i in range(start_idx, min(start_idx + 5, len(lines))):
            if '|' in lines[i]:
                count += 1
        return count >= 3

    def _generate_rag_content(
        self,
        markdown: str,
        chapters: List[Dict],
        elements: Dict
    ) -> Dict[str, Any]:
        """生成RAG内容"""
        # 清理markdown
        cleaned = self._clean_content_for_rag(markdown)
        
        # 生成元素描述
        element_descriptions = []
        
        for table in elements.get("tables", []):
            element_descriptions.append(f"{table.get('name', '表')}：表格内容")
        
        for figure in elements.get("figures", []):
            element_descriptions.append(f"{figure.get('name', '图')}：图像内容")
        
        for formula in elements.get("formulas", []):
            content = formula.get('content', '')
            # 简化公式（去掉LaTeX复杂格式）
            simplified = re.sub(r'\$.*?\$', '[公式]', content)
            element_descriptions.append(f"{formula.get('name', '公式')}：{simplified}")
        
        return {
            "content": cleaned,
            "elements": element_descriptions
        }

    def _clean_content_for_rag(self, markdown: str) -> str:
        """清理内容用于RAG（去除格式，保留纯文本）"""
        # 去除markdown格式标记
        cleaned = re.sub(r'\*\*(.+?)\*\*', r'\1', markdown)  # **bold** -> bold
        cleaned = re.sub(r'\$(.+?)\$', r'\1', cleaned)  # $formula$ -> formula
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)  # 合并多余空行
        return cleaned.strip()

    def _generate_render_content(self, markdown: str, layout_info: Dict) -> str:
        """生成Render内容（保留格式）"""
        return markdown

    def _generate_page_summary(self, markdown: str, chapters: List[Dict]) -> str:
        """生成页面摘要"""
        if chapters:
            chapter_titles = [f"{ch['num']} {ch['title']}" for ch in chapters]
            return f"该页包含章节：{', '.join(chapter_titles)}"
        
        # 如果没有章节，返回前100个字符
        preview = markdown.strip()[:100]
        return f"内容：{preview}..."

    def _extract_keywords(self, markdown: str) -> List[str]:
        """提取关键词"""
        # 简单实现：提取中文术语（2-4个字的中文）
        keywords = re.findall(r'[\u4e00-\u9fff]{2,4}', markdown)
        
        # 去重并限制数量
        unique_keywords = list(set(keywords))[:20]
        return unique_keywords
