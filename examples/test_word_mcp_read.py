#!/usr/bin/env python3
"""
测试 Word MCP 读取功能
"""

import asyncio
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.mcp.registry import MCPRegistry


async def test_word_reading():
    """测试 Word 文档读取功能"""

    print("=== Word MCP 读取功能测试 ===\n")

    # 初始化 MCP 注册表
    registry = MCPRegistry()

    # 等待所有 MCP 加载完成
    print("1. 加载 MCP 服务器...")
    await registry.initialize()
    await asyncio.sleep(2)  # 等待外部 MCP 连接

    # 检查 Word MCP 是否已注册
    if "word" not in registry.mcps:
        print("❌ Word MCP 未注册")
        return

    print("✅ Word MCP 已注册\n")

    # 创建测试文档
    test_file = "/tmp/test_word_read.docx"

    print("2. 创建测试文档...")
    try:
        result = await registry.execute_command(
            mcp_name="word",
            tool_name="create_document",
            filename=test_file,
            title="测试文档",
            author="AICMDEngine"
        )

        if result.success:
            print(f"✅ 测试文档创建成功: {test_file}\n")
        else:
            print(f"❌ 创建文档失败: {result.content}")
            return
    except Exception as e:
        print(f"❌ 创建文档异常: {e}")
        return

    # 添加测试内容
    print("3. 添加测试内容...")
    try:
        # 添加标题
        await registry.execute_command(
            mcp_name="word",
            tool_name="add_heading",
            filename=test_file,
            text="第一章：测试标题",
            level=1
        )

        # 添加段落
        await registry.execute_command(
            mcp_name="word",
            tool_name="add_paragraph",
            filename=test_file,
            text="这是一个测试段落，用于验证 Word MCP 的读取功能。"
        )

        # 添加二级标题
        await registry.execute_command(
            mcp_name="word",
            tool_name="add_heading",
            filename=test_file,
            text="1.1 小节",
            level=2
        )

        # 添加更多段落
        await registry.execute_command(
            mcp_name="word",
            tool_name="add_paragraph",
            filename=test_file,
            text="这是第二个测试段落。"
        )

        print("✅ 测试内容添加完成\n")
    except Exception as e:
        print(f"❌ 添加内容异常: {e}")
        return

    # 测试读取功能
    print("4. 测试读取功能...\n")

    # 测试 1: get_document_text
    print("📄 读取文档文本 (get_document_text):")
    print("-" * 50)
    try:
        result = await registry.execute_command(
            mcp_name="word",
            tool_name="get_document_text",
            filename=test_file
        )

        if result.success:
            print(result.content)
        else:
            print(f"❌ 读取失败: {result.content}")
    except Exception as e:
        print(f"❌ 异常: {e}")

    print("\n" + "-" * 50 + "\n")

    # 测试 2: get_document_info
    print("📋 读取文档信息 (get_document_info):")
    print("-" * 50)
    try:
        result = await registry.execute_command(
            mcp_name="word",
            tool_name="get_document_info",
            filename=test_file
        )

        if result.success:
            print(result.content)
        else:
            print(f"❌ 读取失败: {result.content}")
    except Exception as e:
        print(f"❌ 异常: {e}")

    print("\n" + "-" * 50 + "\n")

    # 测试 3: get_document_outline
    print("📑 读取文档结构 (get_document_outline):")
    print("-" * 50)
    try:
        result = await registry.execute_command(
            mcp_name="word",
            tool_name="get_document_outline",
            filename=test_file
        )

        if result.success:
            print(result.content)
        else:
            print(f"❌ 读取失败: {result.content}")
    except Exception as e:
        print(f"❌ 异常: {e}")

    print("\n" + "=" * 50)
    print("✅ 测试完成！")
    print(f"测试文档保存在: {test_file}")


if __name__ == "__main__":
    asyncio.run(test_word_reading())
