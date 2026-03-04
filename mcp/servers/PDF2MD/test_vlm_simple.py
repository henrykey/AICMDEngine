#!/usr/bin/env python3
"""快速测试 VLM API 是否可用"""
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)

# 测试 VLM 客户端
from vlm_client import UnifiedVLMClient
import time

def test_vlm():
    print(f"VLM Provider: {os.getenv('VLM_MODEL_PROVIDER')}")
    print(f"Allow External VLM: {os.getenv('PDF2MD_ALLOW_EXTERNAL_VLM')}")

    vlm = UnifiedVLMClient(timeout_sec=30, max_retries=1)
    print(f"VLM enabled: {vlm.enabled}")

    if not vlm.enabled:
        print("❌ VLM not enabled!")
        return

    # 简单测试：识别一个空白页面的布局
    print("\n测试VLM布局识别...")
    start = time.time()

    # 创建一个最小的测试图片文件
    from PIL import Image
    import tempfile

    # 创建 1024x768 白色图片
    img = Image.new('RGB', (1024, 768), color='white')

    # 保存到临时文件
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
        img.save(tmp, format='PNG')
        tmp_path = tmp.name

    try:
        result = vlm.recognize_layout(tmp_path)
        elapsed = time.time() - start
        print(f"✓ VLM响应成功！耗时: {elapsed:.2f}秒")
        print(f"结果: {result}")
    except Exception as e:
        elapsed = time.time() - start
        print(f"✗ VLM调用失败！耗时: {elapsed:.2f}秒")
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # 清理临时文件
        import os as os_mod
        try:
            if 'tmp_path' in locals():
                os_mod.unlink(tmp_path)
        except:
            pass

if __name__ == "__main__":
    test_vlm()
