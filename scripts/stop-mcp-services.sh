#!/bin/bash
# MCP 服务停止脚本

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
echo "     MCP 服务停止脚本"
echo "========================================"
echo ""

# 停止 Docker 容器
echo -e "${YELLOW}停止 MCP Docker 容器...${NC}"
cd "$PROJECT_DIR"
if [ -f "docker-compose.mcp-servers.yml" ]; then
    docker-compose -f docker-compose.mcp-servers.yml down
    echo -e "${GREEN}✅ 容器已停止${NC}"
else
    echo -e "${YELLOW}⚠️  docker-compose.mcp-servers.yml 不存在${NC}"
fi
echo ""

# 停止手动运行的 MCP 进程
echo -e "${YELLOW}检查 MCP 进程...${NC}"
MCP_PROCESSES=$(ps aux | grep -E "paddleocr_mcp|word_mcp_server" | grep -v grep | awk '{print $2}')

if [ -n "$MCP_PROCESSES" ]; then
    echo "发现运行中的 MCP 进程:"
    echo "$MCP_PROCESSES" | xargs ps -p 2>/dev/null | grep -v "PID"
    echo ""
    echo "是否停止这些进程? (y/n)"
    read -r response
    if [[ "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
        echo "$MCP_PROCESSES" | xargs kill 2>/dev/null || true
        echo -e "${GREEN}✅ MCP 进程已停止${NC}"
    else
        echo -e "${YELLOW}跳过进程停止${NC}"
    fi
else
    echo -e "${GREEN}✅ 没有运行中的 MCP 进程${NC}"
fi
echo ""

# 停止 MCP Proxy（如果通过脚本运行）
MCP_PROXY_PID=$(pgrep -f "mcp_proxy.py" || true)
if [ -n "$MCP_PROXY_PID" ]; then
    echo -e "${YELLOW}发现运行中的 MCP Proxy (PID: $MCP_PROXY_PID)${NC}"
    echo "是否停止? (y/n)"
    read -r response
    if [[ "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
        kill "$MCP_PROXY_PID"
        echo -e "${GREEN}✅ MCP Proxy 已停止${NC}"
    fi
else
    echo -e "${GREEN}✅ MCP Proxy 未运行${NC}"
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}     清理完成${NC}"
echo -e "${GREEN}========================================${NC}"
