#!/usr/bin/env python3
"""PDF2MD HTTP Server 启动脚本（Docker容器专用）"""

import asyncio
import sys
import os
from pathlib import Path
import importlib.util

# 当前目录
current_dir = Path(__file__).parent

# 解决相对导入问题：创建一个虚拟的包结构
# 通过修改 sys.meta_path 来拦截导入请求

class PDF2MDImporter:
    """自定义导入器，处理相对导入"""
    
    def find_module(self, fullname, path=None):
        if fullname == 'PDF2MD' or fullname.startswith('PDF2MD.'):
            return self
        return None
    
    def load_module(self, fullname):
        if fullname in sys.modules:
            return sys.modules[fullname]
        
        # 处理 PDF2MD.parser 这样的导入
        if fullname.startswith('PDF2MD.'):
            # 去掉 PDF2MD. 前缀
            module_name = fullname[8:]  # 去掉 'PDF2MD.'
            module_file = current_dir / f"{module_name.replace('.', '/')}.py"
            
            if module_file.exists():
                spec = importlib.util.spec_from_file_location(fullname, module_file)
                module = importlib.util.module_from_spec(spec)
                sys.modules[fullname] = module
                spec.loader.exec_module(module)
                return module
        
        # 处理 PDF2MD 包本身
        elif fullname == 'PDF2MD':
            # 创建包模块
            module = type(sys)(fullname)
            module.__path__ = [str(current_dir)]
            sys.modules[fullname] = module
            return module
        
        return None

# 注册自定义导入器
sys.meta_path.insert(0, PDF2MDImporter())

# 添加当前目录到 Python 搜索路径
sys.path.insert(0, str(current_dir))

# 加载环境变量
from dotenv import load_dotenv
env_path = current_dir / '.env'
load_dotenv(env_path)

# 导入MCP服务器
from server import mcp

async def main():
    """启动HTTP/SSE服务器"""
    # 使用 streamable-http 传输
    await mcp.run_async(
        transport="streamable-http",
        host="0.0.0.0",
        port=9003,
    )

if __name__ == "__main__":
    asyncio.run(main())
