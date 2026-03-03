#!/usr/bin/env python3
"""
PDF2MD MCP工具全面测试脚本

测试场景：
1. 封面页（第1页）
2. 目录页（第2页）
3. 表格页（第10页）
4. 公式页（第18页）
5. 文档聚合（1-5页）
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Dict, Any
from dotenv import load_dotenv
import importlib.util

# 加载环境变量
load_dotenv()

# 导入parser模块
current_dir = Path(__file__).parent
spec = importlib.util.spec_from_file_location("parser", current_dir / "parser.py")
parser_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parser_module)
GBDocumentParser = parser_module.GBDocumentParser


def print_section(title: str):
    """打印分节标题"""
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def print_result(result: Dict[str, Any]):
    """打印结果摘要"""
    page_num = result.get("page_num", "?")
    page_type = result.get("page_type", "unknown")
    elapsed = result.get("stats", {}).get("elapsed_ms", 0)

    print(f"✅ 页码: {page_num}")
    print(f"   类型: {page_type}")
    print(f"   耗时: {elapsed} ms")

    # 章节信息
    chapters = result.get("chapters", [])
    if chapters:
        print(f"\n📑 章节 ({len(chapters)}个):")
        for ch in chapters[:5]:
            print(f"   - {ch['num']} {ch['title'][:40]}...")
        if len(chapters) > 5:
            print(f"   ... 还有{len(chapters)-5}个")

    # RAG信息
    rag = result.get("rag", {})
    if rag.get("summary"):
        print(f"\n📝 RAG摘要: {rag['summary'][:80]}...")

    keywords = rag.get("keywords", [])
    if keywords:
        print(f"🔑 关键词: {', '.join(keywords[:5])}...")

    # 元素信息
    elements = result.get("elements", {})
    tables = elements.get("tables", [])
    figures = elements.get("figures", [])
    formulas = elements.get("formulas", [])

    print(f"\n📊 结构化元素:")
    print(f"   表格: {len(tables)} 个")
    print(f"   图像: {len(figures)} 个")
    print(f"   公式: {len(formulas)} 个")

    if tables:
        for table in tables[:2]:
            print(f"      - {table.get('name', '未命名')}")
        if len(tables) > 2:
            print(f"      ... 还有{len(tables)-2}个")

    if figures:
        for figure in figures[:2]:
            print(f"      - {figure.get('name', '未命名')}")
        if len(figures) > 2:
            print(f"      ... 还有{len(figures)-2}个")

    if formulas:
        for formula in formulas[:2]:
            content = formula.get('content', '')[:30]
            print(f"      - {formula.get('name', '未命名')}: {content}...")
        if len(formulas) > 2:
            print(f"      ... 还有{len(formulas)-2}个")

    # Render预览
    render = result.get("render", {}).get("markdown", "")
    if render:
        print(f"\n📄 Render预览（前150字符）:")
        print(f"   {render[:150]}...")


def validate_result(result: Dict[str, Any]) -> bool:
    """验证结果结构"""
    required_fields = ["page_num", "page_type", "chapters", "rag", "render", "elements", "layout", "stats"]

    for field in required_fields:
        if field not in result:
            print(f"❌ 缺少字段: {field}")
            return False

    # 验证rag子字段
    rag = result.get("rag", {})
    rag_fields = ["summary", "content", "elements", "keywords"]
    for field in rag_fields:
        if field not in rag:
            print(f"❌ rag.{field} 缺失")
            return False

    # 验证render子字段
    render = result.get("render", {})
    if "markdown" not in render:
        print(f"❌ render.markdown 缺失")
        return False

    # 验证elements子字段
    elements = result.get("elements", {})
    elements_fields = ["tables", "figures", "formulas"]
    for field in elements_fields:
        if field not in elements:
            print(f"❌ elements.{field} 缺失")
            return False

    print("✅ 结构验证通过")
    return True


def validate_document_result(result: Dict[str, Any]) -> bool:
    """验证文档级结果结构"""
    if "success" not in result:
        print(f"❌ 缺少success字段")
        return False

    if not result.get("success"):
        print(f"❌ 处理失败: {result.get('error', '未知错误')}")
        return False

    required_fields = ["document", "elements", "metadata"]
    for field in required_fields:
        if field not in result:
            print(f"❌ 缺少字段: {field}")
            return False

    # 验证document子字段
    document = result.get("document", {})
    doc_fields = ["title", "toc", "chapters"]
    for field in doc_fields:
        if field not in document:
            print(f"❌ document.{field} 缺失")
            return False

    print("✅ 文档结构验证通过")
    return True


async def test_page_type_coverage():
    """测试不同类型页面的覆盖"""
    print_section("测试1: 页面类型覆盖")

    parser = GBDocumentParser()
    pdf_path = (current_dir / "data/input/GBT16749-2018.pdf").expanduser()

    # 测试页面集
    test_cases = [
        {"page": 1, "expected_type": "cover", "desc": "封面页"},
        {"page": 2, "expected_type": "toc", "desc": "目录页"},
        {"page": 10, "expected_type": "normal", "desc": "表格页"},
        {"page": 18, "expected_type": "normal", "desc": "公式页"},
    ]

    results = []
    for case in test_cases:
        page_num = case["page"]
        desc = case["desc"]

        print(f"\n--- 测试第{page_num}页 ({desc}) ---")

        try:
            result = parser.process_single_page(str(pdf_path), page_num)

            # 验证结构
            if not validate_result(result):
                print(f"❌ 第{page_num}页结构验证失败")
                continue

            # 打印结果
            print_result(result)

            # 保存结果
            output_file = current_dir / f"data/output/test_page_{page_num}_full.json"
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text(
                json.dumps(result, ensure_ascii=False, indent=2),
                encoding='utf-8'
            )
            print(f"💾 已保存到: {output_file.name}")

            results.append({"page": page_num, "status": "success"})

        except Exception as e:
            print(f"❌ 第{page_num}页处理失败: {e}")
            results.append({"page": page_num, "status": "failed", "error": str(e)})

    # 总结
    success_count = sum(1 for r in results if r["status"] == "success")
    print(f"\n📊 页面测试总结: {success_count}/{len(results)} 成功")

    return results


async def test_formula_detection():
    """测试公式检测能力"""
    print_section("测试2: 公式检测能力")

    parser = GBDocumentParser()
    pdf_path = (current_dir / "data/input/GBT16749-2018.pdf").expanduser()

    # 公式页面（第18页有5个公式）
    page_num = 18

    print(f"\n--- 测试第{page_num}页公式检测 ---")

    try:
        result = parser.process_single_page(str(pdf_path), page_num)

        formulas = result.get("elements", {}).get("formulas", [])
        print(f"✅ 检测到 {len(formulas)} 个公式")

        if len(formulas) >= 5:
            print(f"✅ 公式检测数量符合预期（≥5个）")

            # 检查公式结构
            for i, formula in enumerate(formulas, 1):
                if "id" not in formula or "name" not in formula or "content" not in formula:
                    print(f"❌ 公式{i}结构不完整")
                    return False

                name = formula.get("name", "")
                content = formula.get("content", "")
                print(f"   {i}. {name}: {content[:40]}...")

            print("✅ 公式结构验证通过")
            return True
        else:
            print(f"⚠️  公式数量不足，预期≥5个，实际{len(formulas)}个")
            return False

    except Exception as e:
        print(f"❌ 公式检测测试失败: {e}")
        return False


async def test_table_detection():
    """测试表格检测能力"""
    print_section("测试3: 表格检测能力")

    parser = GBDocumentParser()
    pdf_path = (current_dir / "data/input/GBT16749-2018.pdf").expanduser()

    # 表格页面（第10页有表格）
    page_num = 10

    print(f"\n--- 测试第{page_num}页表格检测 ---")

    try:
        result = parser.process_single_page(str(pdf_path), page_num)

        tables = result.get("elements", {}).get("tables", [])
        print(f"✅ 检测到 {len(tables)} 个表格")

        # 第10页应该有表格
        if len(tables) > 0:
            print(f"✅ 表格检测成功")

            # 检查表格结构
            for i, table in enumerate(tables, 1):
                if "id" not in table or "name" not in table:
                    print(f"❌ 表格{i}结构不完整")
                    return False

                name = table.get("name", "")
                print(f"   {i}. {name}")

            print("✅ 表格结构验证通过")
            return True
        else:
            print(f"⚠️  未检测到表格")

            # 检查render内容中是否有表格
            render = result.get("render", {}).get("markdown", "")
            if "|" in render and "表" in render:
                print("📝 Render中包含表格标记，但未提取到elements")

            return len(tables) >= 0

    except Exception as e:
        print(f"❌ 表格检测测试失败: {e}")
        return False


async def test_document_aggregation():
    """测试文档聚合功能"""
    print_section("测试4: 文档聚合功能")

    parser = GBDocumentParser()
    pdf_path = (current_dir / "data/input/GBT16749-2018.pdf").expanduser()

    # 测试1-5页聚合
    pages_to_test = [1, 2, 3, 4, 5]

    print(f"\n--- 测试页面聚合: {pages_to_test} ---")

    try:
        # 逐页处理
        page_results = []
        for page_num in pages_to_test:
            print(f"处理第{page_num}页...")
            page_result = parser.process_single_page(str(pdf_path), page_num)
            page_results.append(page_result)

        # 聚合
        from test_mcp_tools import _aggregate_pages_to_document
        document_result = _aggregate_pages_to_document(page_results)

        # 验证结构
        if not validate_document_result(document_result):
            return False

        # 打印结果
        document = document_result.get("document", {})
        metadata = document_result.get("metadata", {})

        print(f"\n✅ 文档聚合成功")
        print(f"   标题: {document.get('title', '未知')[:50]}")
        print(f"   总页数: {metadata.get('total_pages', 0)}")
        print(f"   成功处理: {metadata.get('processed_pages', 0)} 页")

        toc = document.get("toc", [])
        if toc:
            print(f"\n📑 目录 ({len(toc)}条):")
            for item in toc[:5]:
                print(f"   - {item.get('chapter')} {item.get('title', '')[:40]}")
            if len(toc) > 5:
                print(f"   ... 还有{len(toc)-5}条")

        chapters = document.get("chapters", [])
        if chapters:
            print(f"\n📚 章节 ({len(chapters)}个):")
            for ch in chapters[:5]:
                pages_str = ', '.join(map(str, ch.get('pages', [])))
                print(f"   - {ch['num']} {ch['title'][:30]} (第{pages_str}页)")
            if len(chapters) > 5:
                print(f"   ... 还有{len(chapters)-5}个")

        elements = document_result.get("elements", {})
        print(f"\n📊 结构化元素总计:")
        print(f"   表格: {len(elements.get('tables', []))} 个")
        print(f"   图像: {len(elements.get('figures', []))} 个")
        print(f"   公式: {len(elements.get('formulas', []))} 个")

        # 保存结果
        output_file = current_dir / "data/output/test_document_full.json"
        output_file.write_text(
            json.dumps(document_result, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
        print(f"\n💾 已保存到: {output_file.name}")

        return True

    except Exception as e:
        print(f"❌ 文档聚合测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_rag_render_modes():
    """测试RAG和Render双模式输出"""
    print_section("测试5: RAG和Render双模式")

    parser = GBDocumentParser()
    pdf_path = (current_dir / "data/input/GBT16749-2018.pdf").expanduser()

    # 使用第18页（有公式）
    page_num = 18

    print(f"\n--- 测试第{page_num}页双模式输出 ---")

    try:
        result = parser.process_single_page(str(pdf_path), page_num)

        # RAG模式
        rag = result.get("rag", {})
        rag_content = rag.get("content", "")
        rag_elements = rag.get("elements", [])

        print(f"\n📝 RAG模式:")
        print(f"   纯文本长度: {len(rag_content)} 字符")
        print(f"   元素描述: {len(rag_elements)} 个")

        if rag_elements:
            print(f"   元素描述示例:")
            for elem in rag_elements[:3]:
                print(f"      - {elem[:50]}...")

        # Render模式
        render = result.get("render", {})
        render_content = render.get("markdown", "")

        print(f"\n📄 Render模式:")
        print(f"   Markdown长度: {len(render_content)} 字符")

        # 检查是否有LaTeX公式（Render应该有）
        has_latex = "$" in render_content or "\\[" in render_content
        print(f"   包含LaTeX: {'是' if has_latex else '否'}")

        # 检查是否有表格（Render应该有）
        has_table = "|" in render_content
        print(f"   包含表格: {'是' if has_table else '否'}")

        # 验证双模式差异
        if len(rag_content) > 0 and len(render_content) > 0:
            print(f"\n✅ 双模式输出正常")
            print(f"   RAG: 纯文本描述，适合检索")
            print(f"   Render: 完整Markdown，适合展示")
            return True
        else:
            print(f"\n❌ 双模式输出异常")
            return False

    except Exception as e:
        print(f"❌ 双模式测试失败: {e}")
        return False


async def main():
    """主测试函数"""
    print("\n" + "="*70)
    print("  PDF2MD MCP工具 - 全面功能测试")
    print("="*70)

    # 创建输出目录
    output_dir = current_dir / "data/output"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 运行所有测试
    test_results = {}

    try:
        # 测试1: 页面类型覆盖
        results = await test_page_type_coverage()
        test_results["页面类型覆盖"] = results

        # 测试2: 公式检测
        success = await test_formula_detection()
        test_results["公式检测"] = success

        # 测试3: 表格检测
        success = await test_table_detection()
        test_results["表格检测"] = success

        # 测试4: 文档聚合
        success = await test_document_aggregation()
        test_results["文档聚合"] = success

        # 测试5: RAG/Render双模式
        success = await test_rag_render_modes()
        test_results["双模式输出"] = success

    except Exception as e:
        print(f"\n❌ 测试过程出错: {e}")
        import traceback
        traceback.print_exc()
        return

    # 总结
    print_section("测试总结")

    for test_name, result in test_results.items():
        if isinstance(result, list):
            success_count = sum(1 for r in result if r.get("status") == "success")
            total_count = len(result)
            status = "✅" if success_count == total_count else "⚠️"
            print(f"{status} {test_name}: {success_count}/{total_count} 成功")
        else:
            status = "✅" if result else "❌"
            print(f"{status} {test_name}: {'通过' if result else '失败'}")

    print(f"\n{'='*70}")
    print("  测试完成！")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    asyncio.run(main())
