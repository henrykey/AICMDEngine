#!/usr/bin/env python3
"""创建一个测试用的扫描版PDF（只包含图片，没有文本层）"""
import fitz  # PyMuPDF
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

def create_scanned_pdf(output_path: str):
    """创建一个包含文字图片的扫描版PDF（无文本层）"""

    # 创建一个简单的图片，上面有文字
    width, height = 595, 842  # A4 size in points
    img = Image.new('RGB', (width, height), color='white')
    draw = ImageDraw.Draw(img)

    # 绘制一些文字（这些文字会被渲染为图片，不是PDF的文本层）
    text_lines = [
        "This is a scanned PDF",
        "It contains only images",
        "No text layer available",
        "VLM should recognize this content"
    ]

    y_position = 100
    for line in text_lines:
        # 使用默认字体
        draw.text((100, y_position), line, fill='black')
        y_position += 50

    # 保存图片到临时文件
    temp_img = '/tmp/scanned_page.png'
    img.save(temp_img)

    # 创建PDF，只包含这个图片
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)

    # 将图片插入到页面（不添加任何文本）
    page.insert_image(page.rect, filename=temp_img)

    # 保存PDF
    doc.save(output_path)
    doc.close()

    print(f"✅ 创建扫描版PDF: {output_path}")

    # 验证没有文本层
    verify_doc = fitz.open(output_path)
    text = verify_doc[0].get_text()
    verify_doc.close()

    print(f"   验证: 文本层长度 = {len(text)} 字符")
    if len(text) < 10:
        print(f"   ✅ 确认为扫描版（无文本层）")
    else:
        print(f"   ⚠️  警告: 可能包含文本层")

if __name__ == "__main__":
    output = "/Users/kehongwei/workspace/AICMDEngine/mcp/servers/PDF2MD/data/input/test_scanned.pdf"
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    create_scanned_pdf(output)
