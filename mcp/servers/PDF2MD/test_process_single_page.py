#!/usr/bin/env python3
"""直接测试 process_single_page 方法（绕过MCP）"""
import sys
import time
from pathlib import Path

# 加载环境变量
from dotenv import load_dotenv
env_file = Path(__file__).parent / '.env'
load_dotenv(env_file)

# 导入parser
sys.path.insert(0, str(Path(__file__).parent))
from parser import GBDocumentParser

def main():
    """测试 process_single_page"""
    print("=" * 70)
    print("直接测试 process_single_page 方法")
    print("=" * 70)

    # 初始化parser
    parser = GBDocumentParser()

    print(f"\n配置检查:")
    print(f"  - VLM enabled: {parser.vlm.enabled}")
    print(f"  - VLM provider: {parser.vlm.provider}")
    print(f"  - allow_external_vlm: {parser.cfg.allow_external_vlm}")

    # 使用扫描版测试PDF
    pdf_path = "/Users/kehongwei/workspace/AICMDEngine/mcp/servers/PDF2MD/data/input/test_scanned.pdf"
    page_num = 1

    print(f"\n测试参数:")
    print(f"  - PDF文件: {pdf_path}")
    print(f"  - 页码: {page_num}")

    # 调用 process_single_page
    print(f"\n开始调用 process_single_page...")
    print("=" * 70)

    start = time.time()
    result = parser.process_single_page(pdf_path, page_num)
    elapsed = time.time() - start

    print("=" * 70)
    print(f"\n✅ 调用完成! 耗时: {elapsed:.2f} 秒")

    # 显示结果
    print(f"\n结果:")
    print(f"  - page_num: {result.get('page_num')}")
    print(f"  - page_type: {result.get('page_type')}")
    print(f"  - parser_engine: {result.get('stats', {}).get('parser_engine')}")
    print(f"  - elapsed_ms: {result.get('stats', {}).get('elapsed_ms')}")

    render_md = result.get('render', {}).get('markdown', '')
    rag_content = result.get('rag', {}).get('content', '')

    print(f"\n内容:")
    print(f"  - render markdown 长度: {len(render_md)} 字符")
    print(f"  - rag content 长度: {len(rag_content)} 字符")

    # 显示前20行render内容
    if render_md:
        print(f"\nrender 内容前20行:")
        print("-" * 70)
        lines = render_md.split('\n')
        for i, line in enumerate(lines[:20], 1):
            print(f"{i:3d}: {line}")
        print("-" * 70)
    else:
        print(f"\n⚠️  render 内容为空!")

    # 显示前20行rag内容
    if rag_content:
        print(f"\nRAG 内容前20行:")
        print("-" * 70)
        lines = rag_content.split('\n')
        for i, line in enumerate(lines[:20], 1):
            print(f"{i:3d}: {line}")
        print("-" * 70)
    else:
        print(f"\n⚠️  RAG 内容为空!")

if __name__ == "__main__":
    main()
