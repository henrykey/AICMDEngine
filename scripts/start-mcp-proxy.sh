#!/bin/bash
# MCP Proxy 启动脚本
# 用于启动和管理 MCP Proxy 服务

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 脚本目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "========================================"
echo "     MCP Proxy 启动脚本"
echo "========================================"
echo ""

# 检查 Python 环境
if ! command -v python &> /dev/null; then
    echo -e "${RED}错误: Python 未安装${NC}"
    exit 1
fi

# 检查配置文件
CONFIG_FILE="$PROJECT_DIR/mcp/proxy/config/mcp-proxy-config.yml"
if [ ! -f "$CONFIG_FILE" ]; then
    echo -e "${RED}错误: 配置文件不存在: $CONFIG_FILE${NC}"
    exit 1
fi

# 显示当前模式
echo -e "${YELLOW}当前配置:${NC}"
if grep -q "type: docker" "$CONFIG_FILE"; then
    echo -e "  模式: ${GREEN}容器模式 (Docker)${NC}"
    echo "  MCP Proxy 将连接到 Docker 容器中的 MCP servers"
else
    echo -e "  模式: ${GREEN}进程模式 (Process)${NC}"
    echo "  MCP Proxy 将启动本地 MCP 进程"
fi
echo ""

# 检查 Docker 模式是否需要启动容器
if grep -q "type: docker" "$CONFIG_FILE"; then
    echo -e "${YELLOW}检查 Docker 容器...${NC}"

    # 检查容器是否运行
    CONTAINERS=$(docker ps --filter "name=paddleocr-mcp" --filter "name=office-word-mcp" --format "{{.Names}}" | wc -l)

    if [ "$CONTAINERS" -eq 0 ]; then
        echo -e "${YELLOW}未检测到运行中的 MCP 容器${NC}"
        echo "是否启动容器? (y/n)"
        read -r response
        if [[ "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
            echo "启动容器..."
            cd "$PROJECT_DIR"
            docker-compose -f docker-compose.mcp-servers.yml up -d
            echo -e "${GREEN}✅ 容器已启动${NC}"
            echo ""
        else
            echo -e "${RED}取消启动${NC}"
            exit 1
        fi
    else
        echo -e "${GREEN}✅ 检测到 $CONTAINERS 个运行中的容器${NC}"
        echo ""
    fi
fi

# 启动 MCP Proxy
echo -e "${YELLOW}启动 MCP Proxy...${NC}"
cd "$PROJECT_DIR/mcp/proxy"
python src/mcp_proxy.py
