#!/usr/bin/env python3
"""快速测试：只处理第1页"""
import os
import sys
from pathlib import Path

# 加载环境变量
from dotenv import load_dotenv
current_dir = Path(__file__).parent.absolute()
load_dotenv(current_dir / '.env')

# 导入模块
sys.path.insert(0, str(current_dir))
from parser import GBDocumentParser

def main():
    parser = GBDocumentParser()

    print(f"VLM enabled: {parser.vlm.enabled}")
    print(f"allow_external_vlm: {parser.cfg.allow_external_vlm}")

    pdf_path = str(current_dir / "data/input/GBT16749-2018.pdf")
    print(f"\nPDF路径: {pdf_path}")
    print(f"开始解析第1页...\n")

    # 运行解析
    result = parser.parse_standard_pdf(pdf_path)

    print(f"\n✅ 解析完成:")
    print(f"Success: {result.get('success')}")

    md = result.get('markdown', '')
    print(f"Markdown大小: {len(md):,} 字符")

    # 检查页码标记
    page_markers = md.count('## 第')
    print(f"页码标记数量: {page_markers}")

    # 检查页眉
    header_count = md.count('GB/T 16749')
    print(f"页眉出现次数: {header_count}")

    # 显示前30行
    print(f"\n📄 前30行预览:")
    print("=" * 70)
    lines = md.split('\n')
    for i, line in enumerate(lines[:30], 1):
        print(f"{i:3d}: {line}")
    print("=" * 70)

if __name__ == "__main__":
    main()
