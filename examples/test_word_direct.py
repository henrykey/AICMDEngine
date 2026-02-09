#!/usr/bin/env python3
"""
直接测试 Word MCP 服务器功能
"""

import sys
import os

# 添加 Word MCP 路径
word_mcp_path = "/Users/kehongwei/workspace/AICMDEngine/mcp/Office-Word-MCP-Server"
sys.path.insert(0, word_mcp_path)

# 导入 Word MCP 工具
from word_document_server.tools import document_tools, content_tools


def test_word_reading():
    """测试 Word 文档读取功能"""

    print("=== Word MCP 读取功能测试 ===\n")

    # 创建测试文档
    test_file = "/tmp/test_word_read.docx"

    print("1. 创建测试文档...")
    try:
        result = document_tools.create_document(
            filename=test_file,
            title="测试文档",
            author="AICMDEngine"
        )
        print(f"✅ 测试文档创建成功\n")
    except Exception as e:
        print(f"❌ 创建文档失败: {e}\n")
        return

    # 添加测试内容
    print("2. 添加测试内容...")
    try:
        # 添加标题
        content_tools.add_heading(
            filename=test_file,
            text="第一章：测试标题",
            level=1
        )

        # 添加段落
        content_tools.add_paragraph(
            filename=test_file,
            text="这是一个测试段落，用于验证 Word MCP 的读取功能。"
        )

        # 添加二级标题
        content_tools.add_heading(
            filename=test_file,
            text="1.1 小节",
            level=2
        )

        # 添加更多段落
        content_tools.add_paragraph(
            filename=test_file,
            text="这是第二个测试段落。"
        )

        print("✅ 测试内容添加完成\n")
    except Exception as e:
        print(f"❌ 添加内容失败: {e}\n")
        return

    # 测试读取功能
    print("3. 测试读取功能...\n")

    # 测试 1: get_document_text
    print("📄 读取文档文本 (get_document_text):")
    print("-" * 50)
    try:
        result = document_tools.get_document_text(test_file)
        print(result)
    except Exception as e:
        print(f"❌ 读取失败: {e}")

    print("\n" + "-" * 50 + "\n")

    # 测试 2: get_document_info
    print("📋 读取文档信息 (get_document_info):")
    print("-" * 50)
    try:
        result = document_tools.get_document_info(test_file)
        print(result)
    except Exception as e:
        print(f"❌ 读取失败: {e}")

    print("\n" + "-" * 50 + "\n")

    # 测试 3: get_document_outline
    print("📑 读取文档结构 (get_document_outline):")
    print("-" * 50)
    try:
        result = document_tools.get_document_outline(test_file)
        print(result)
    except Exception as e:
        print(f"❌ 读取失败: {e}")

    print("\n" + "=" * 50)
    print("✅ 测试完成！")
    print(f"测试文档保存在: {test_file}")


if __name__ == "__main__":
    test_word_reading()
