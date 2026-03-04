#!/usr/bin/env python3
"""简单测试PDF2MD在.venv中的工作情况"""
import sys
import os
from pathlib import Path
from dotenv import load_dotenv
import time
import fitz

# 加载环境变量
load_dotenv('.env')

from parser import GBDocumentParser

# 测试文件
pdf_path = Path.home() / "Documents/GB/GB∕T 150.1~4-2024 压力容器 扫描版.pdf"

print(f"测试文件: {pdf_path}")
print(f"文件存在: {pdf_path.exists()}")

# 提取第1页
print("\n提取第1页...")
doc = fitz.open(str(pdf_path))
single_page = fitz.open()
single_page.insert_pdf(doc, from_page=0, to_page=0)
pdf_bytes = single_page.write()
print(f"提取完成: {len(pdf_bytes)} bytes")

# 创建parser
print("\n创建parser...")
parser = GBDocumentParser()
print(f"VLM enabled: {parser.vlm.enabled}")

# 处理第1页
print("\n处理第1页...")
start = time.time()
result = parser.process_single_page(pdf_bytes, 1)
elapsed = time.time() - start

print(f"\n处理完成，耗时: {elapsed:.2f}秒")
print(f"Success: {result.get('success')}")
print(f"Page type: {result.get('page_type')}")
print(f"Parser engine: {result.get('stats', {}).get('parser_engine')}")

render_md = result.get('render', {}).get('markdown', '')
print(f"\nRender markdown长度: {len(render_md)}")
print(f"Render预览:\n{render_md[:500]}")

rag_content = result.get('rag', {}).get('content', '')
print(f"\nRAG content长度: {len(rag_content)}")
print(f"RAG预览:\n{rag_content[:500]}")
