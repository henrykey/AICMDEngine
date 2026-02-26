#!/bin/bash
# MCP WebSocket Proxy 启动脚本

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROXY_DIR="$SCRIPT_DIR/proxy"

echo "🚀 启动 MCP WebSocket Proxy..."
echo "工作目录: $PROXY_DIR"
echo ""

# 检查配置文件
if [ ! -f "$PROXY_DIR/config/mcp-proxy-config.yml" ]; then
    echo "❌ 错误: 配置文件不存在: $PROXY_DIR/config/mcp-proxy-config.yml"
    exit 1
fi

# 检查 Python
if ! command -v python &> /dev/null; then
    echo "❌ 错误: 未找到 python"
    exit 1
fi

# 进入代理目录
cd "$PROXY_DIR"

# 安装依赖（如果需要）
if [ ! -d "venv" ]; then
    echo "📦 创建虚拟环境并安装依赖..."
    python -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
fi

# 激活虚拟环境
source venv/bin/activate

# 启动代理
echo "▶️  启动代理服务..."
python -m src
