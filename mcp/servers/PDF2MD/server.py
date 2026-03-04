#!/usr/bin/env python3
import asyncio
import base64
import json
import os
import re
from pathlib import Path
from typing import List, Optional, Dict

from fastmcp import FastMCP

from .parser import GBDocumentParser

mcp = FastMCP(name="GB-Standard-Parser", mask_error_details=True)
parser = GBDocumentParser()


def _is_base64_pdf(s: str) -> bool:
    """检查字符串是否是 Base64 编码的 PDF 数据"""
    return s.startswith("JVBERi0")


def _resolve_input_path(file_path: str) -> str:
    path = Path(file_path).expanduser()
    if path.is_absolute():
        return str(path)
    input_dir = Path(os.getenv("PDF2MD_INPUT_DIR", "./data/input")).expanduser()
    return str(input_dir.joinpath(file_path).resolve())


def _decode_pdf_input(pdf_input: str) -> tuple[Optional[bytes], Optional[str]]:
    """
    解析 PDF 输入，返回 (bytes 数据，临时文件路径) 的元组
    
    Args:
        pdf_input: 文件路径或 Base64 编码的 PDF 数据
    
    Returns:
        (pdf_bytes, temp_path) 元组：
        - 如果是 Base64：返回 (bytes, 临时文件路径)
        - 如果是文件路径：返回 (None, 解析后的文件路径)
    """
    if _is_base64_pdf(pdf_input):
        pdf_bytes = base64.b64decode(pdf_input)
        temp_fd, temp_path = tempfile.mkstemp(suffix='.pdf')
        with os.fdopen(temp_fd, 'wb') as f:
            f.write(pdf_bytes)
            f.flush()
            os.fsync(f.fileno())
        return pdf_bytes, temp_path
    else:
        return None, _resolve_input_path(pdf_input)


@mcp.tool("parse_standard_pdf")
async def parse_standard_pdf(file_path: str) -> str:
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, parser.parse_standard_pdf, _resolve_input_path(file_path))
        if result.get("success"):
            return result.get("markdown", "")
        return f"Error: {'; '.join(result.get('errors', [])) or 'parse failed'}"
    except Exception as exc:
        return f"Error: {exc}"


@mcp.tool("export_renderable_markdown")
async def export_renderable_markdown(file_path: str, output_path: Optional[str] = None) -> str:
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None, parser.export_renderable_markdown, _resolve_input_path(file_path), output_path
        )
    except Exception as exc:
        result = {"success": False, "error": str(exc)}
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool("extract_formulas")
async def extract_formulas(file_path: str, pages: Optional[List[int]] = None) -> str:
    loop = asyncio.get_event_loop()
    try:
        formulas = await loop.run_in_executor(None, parser.extract_formulas, _resolve_input_path(file_path), pages)
    except Exception as exc:
        formulas = [{"error": str(exc)}]
    return json.dumps(formulas, ensure_ascii=False, indent=2)


@mcp.tool("extract_tables")
async def extract_tables(file_path: str, pages: Optional[List[int]] = None) -> str:
    loop = asyncio.get_event_loop()
    try:
        tables = await loop.run_in_executor(None, parser.extract_tables, _resolve_input_path(file_path), pages)
    except Exception as exc:
        tables = [{"error": str(exc)}]
    return json.dumps(tables, ensure_ascii=False, indent=2)


@mcp.tool("extract_images_with_caption")
async def extract_images_with_caption(file_path: str, pages: Optional[List[int]] = None) -> str:
    loop = asyncio.get_event_loop()
    try:
        images = await loop.run_in_executor(
            None, parser.extract_images_with_caption, _resolve_input_path(file_path), pages
        )
    except Exception as exc:
        images = [{"error": str(exc)}]
    return json.dumps(images, ensure_ascii=False, indent=2)


@mcp.tool("chunk_for_rag")
async def chunk_for_rag(file_path: str, chunk_size: int = 500, include_images: bool = True) -> str:
    loop = asyncio.get_event_loop()
    try:
        chunks = await loop.run_in_executor(
            None, parser.chunk_for_rag, _resolve_input_path(file_path), chunk_size, include_images
        )
    except Exception as exc:
        chunks = [{"error": str(exc)}]
    return json.dumps(chunks, ensure_ascii=False, indent=2)


@mcp.tool("check_watermark")
async def check_watermark(file_path: str) -> str:
    loop = asyncio.get_event_loop()
    try:
        info = await loop.run_in_executor(None, parser.check_watermark, _resolve_input_path(file_path))
    except Exception as exc:
        info = {"error": str(exc)}
    return json.dumps(info, ensure_ascii=False, indent=2)


@mcp.tool("get_layout_info")
async def get_layout_info(file_path: str, page: int = 1) -> str:
    loop = asyncio.get_event_loop()
    try:
        info = await loop.run_in_executor(None, parser.get_layout_info, _resolve_input_path(file_path), page)
    except Exception as exc:
        info = {"error": str(exc)}
    return json.dumps(info, ensure_ascii=False, indent=2)


@mcp.tool("get_document_info")
async def get_document_info(file_path: str) -> str:
    loop = asyncio.get_event_loop()
    try:
        info = await loop.run_in_executor(None, parser.get_document_info, _resolve_input_path(file_path))
    except Exception as exc:
        info = {"error": str(exc)}
    return json.dumps(info, ensure_ascii=False, indent=2)


@mcp.tool("health_check")
async def health_check() -> str:
    return "OK"


@mcp.tool("process_pdf_page")
async def process_pdf_page(page_num: int, pdf_input: str) -> str:
    """
    处理PDF单页，返回结构化结果

    Args:
        page_num: 页码（从1开始）
        pdf_input: PDF输入，可以是文件路径或base64编码的PDF数据

    Returns:
        JSON字符串，包含单页的结构化信息（chapters, rag, render, elements）
    """
    loop = asyncio.get_event_loop()
    try:
        # 判断是base64还是文件路径
        if _is_base64_pdf(pdf_input):
            # 解码base64为bytes
            pdf_bytes = base64.b64decode(pdf_input)
            result = await loop.run_in_executor(
                None, parser.process_single_page, pdf_bytes, page_num
            )
        else:
            # 作为文件路径处理
            result = await loop.run_in_executor(
                None, parser.process_single_page, _resolve_input_path(pdf_input), page_num
            )
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as exc:
        error_result = {
            "success": False,
            "error": str(exc),
            "page_num": page_num
        }
        return json.dumps(error_result, ensure_ascii=False, indent=2)


@mcp.tool("process_pdf_document")
async def process_pdf_document(file_path: Optional[str] = None, file_data: Optional[str] = None, pages: Optional[List[int]] = None) -> str:
    """
    处理整个PDF文档，返回完整结构化结果

    Args:
        file_path: PDF文件路径（与file_data二选一）
        file_data: base64编码的PDF数据（与file_path二选一）
        pages: 可选，指定处理的页码列表（None=全部页）

    Returns:
        JSON字符串，包含文档的完整结构化信息（title, toc, chapters）
    """
    # 参数验证
    if not file_path and not file_data:
        return json.dumps({"success": False, "error": "必须提供file_path或file_data参数"}, ensure_ascii=False)
    if file_path and file_data:
        return json.dumps({"success": False, "error": "不能同时提供file_path和file_data参数"}, ensure_ascii=False)

    loop = asyncio.get_event_loop()
    try:
        # 处理输入
        if file_data:
            # 解码base64
            pdf_bytes = base64.b64decode(file_data)
            # 使用临时文件或直接使用bytes获取总页数
            import fitz
            import tempfile
            import os

            # 创建临时文件用于获取页数
            temp_fd, temp_path = tempfile.mkstemp(suffix='.pdf')
            try:
                with os.fdopen(temp_fd, 'wb') as f:
                    f.write(pdf_bytes)
                    f.flush()
                    os.fsync(f.fileno())

                # 获取总页数
                doc = fitz.open(temp_path)
                total_pages = len(doc)
                doc.close()

                # 确定要处理的页码
                if pages is None:
                    pages_to_process = list(range(1, total_pages + 1))
                else:
                    pages_to_process = pages

                # 逐页处理，使用bytes输入
                page_results = []
                for page_num in pages_to_process:
                    try:
                        page_result = await loop.run_in_executor(
                            None, parser.process_single_page, pdf_bytes, page_num
                        )
                        page_results.append(page_result)
                    except Exception as e:
                        print(f"[ERROR] 处理第{page_num}页失败: {e}")
                        page_results.append({
                            "page_num": page_num,
                            "error": str(e),
                            "page_type": "error"
                        })
            finally:
                # 清理临时文件
                try:
                    os.unlink(temp_path)
                except:
                    pass
        else:
            # 文件路径模式
            resolved_path = _resolve_input_path(file_path)

            # 获取总页数
            import fitz
            doc = fitz.open(resolved_path)
            total_pages = len(doc)
            doc.close()

            # 确定要处理的页码
            if pages is None:
                pages_to_process = list(range(1, total_pages + 1))
            else:
                pages_to_process = pages

            # 逐页处理
            page_results = []
            for page_num in pages_to_process:
                try:
                    page_result = await loop.run_in_executor(
                        None, parser.process_single_page, resolved_path, page_num
                    )
                    page_results.append(page_result)
                except Exception as e:
                    print(f"[ERROR] 处理第{page_num}页失败: {e}")
                    page_results.append({
                        "page_num": page_num,
                        "error": str(e),
                        "page_type": "error"
                    })

        # 聚合为文档级结果
        document_result = _aggregate_pages_to_document(page_results)

        return json.dumps(document_result, ensure_ascii=False, indent=2)

    except Exception as exc:
        error_result = {
            "success": False,
            "error": str(exc),
            "document": None
        }
        return json.dumps(error_result, ensure_ascii=False, indent=2)


def _aggregate_pages_to_document(page_results: List[Dict]) -> Dict:
    """
    将页面级别的结果聚合成文档级别的结果

    Args:
        page_results: 所有页面的处理结果列表

    Returns:
        文档级别的结构化结果
    """
    import fitz

    # 获取标题（从第一页）
    first_page = page_results[0]
    title = ""
    if first_page.get("page_type") == "cover":
        # 从封面提取标题
        if first_page.get("rag", {}).get("content"):
            content = first_page["rag"]["content"]
            lines = content.split('\n')
            for line in lines[:10]:  # 检查前10行
                if len(line) > 5 and "GB/T" in line or "标准" in line:
                    title = line
                    break
            if not title:
                title = lines[0] if lines else "未知标题"
    else:
        title = "PDF文档"

    # 提取目录（从toc页面）
    toc = []
    for page in page_results:
        if page.get("page_type") == "toc":
            # 从chapters中提取目录
            for ch in page.get("chapters", []):
                toc.append({
                    "chapter": ch["num"],
                    "title": ch["title"]
                })

    # 聚合章节（跨页合并）
    chapters_by_num = {}
    for page in page_results:
        for ch in page.get("chapters", []):
            num = ch["num"]
            if num not in chapters_by_num:
                chapters_by_num[num] = {
                    "num": num,
                    "title": ch["title"],
                    "level": ch["level"],
                    "pages": [],
                    "rag": [],
                    "render": ""
                }

            chapters_by_num[num]["pages"].append(page["page_num"])
            chapters_by_num[num]["rag"].append(page.get("rag", {}).get("content", ""))

    # 合并RAG内容并生成Render
    sorted_chapters = _sort_chapters(list(chapters_by_num.values()))

    for ch in sorted_chapters:
        ch["rag"] = "\n\n".join(ch["rag"])
        # Render从对应页面获取
        page_with_chapter = next(
            (p for p in page_results if p["page_num"] == ch["pages"][0]),
            None
        )
        if page_with_chapter:
            ch["render"] = page_with_chapter.get("render", {}).get("markdown", "")

    # 聚合elements
    all_elements = {
        "tables": [],
        "figures": [],
        "formulas": []
    }

    for page in page_results:
        page_elements = page.get("elements", {})
        all_elements["tables"].extend(page_elements.get("tables", []))
        all_elements["figures"].extend(page_elements.get("figures", []))
        all_elements["formulas"].extend(page_elements.get("formulas", []))

    return {
        "success": True,
        "document": {
            "title": title,
            "toc": toc,
            "chapters": sorted_chapters
        },
        "elements": all_elements,
        "metadata": {
            "total_pages": len(page_results),
            "processed_pages": len([p for p in page_results if "error" not in p])
        }
    }


def _sort_chapters(chapters: List[Dict]) -> List[Dict]:
    """章节排序"""
    def chapter_key(ch):
        num = ch["num"]

        # 数字章节
        if re.match(r'^\d+(\.\d+)*$', num):
            parts = num.split('.')
            return (0, [int(p) for p in parts])

        # 附录
        if num.startswith("附录"):
            letter = num.replace("附录", "")[0]
            return (1, ord(letter))

        # 参考文献
        if num == "参考文献":
            return (2, 0)

        return (3, num)

    return sorted(chapters, key=chapter_key)


if __name__ == "__main__":
    # MCP stdio server entry point
    mcp.run()
