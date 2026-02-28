#!/bin/bash
# 启动Host PaddleOCR MCP 服务
# 这是最稳定的部署方式（已验证）

set -e

echo "🚀 启动 PaddleOCR MCP Host 服务..."
echo "════════════════════════════════════"

# 配置
MCP_LOG="/tmp/paddleocr-host.log"
MCP_PID_FILE="/tmp/paddleocr-mcp.pid"

# 检查是否已在运行
if [ -f "$MCP_PID_FILE" ]; then
    OLD_PID=$(cat "$MCP_PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "✓ MCP 服务已在运行 (PID: $OLD_PID)"
        echo "  日志: tail -f $MCP_LOG"
        exit 0
    fi
fi

# 杀死旧进程（如果存在）
pkill -f "python -m paddleocr_mcp" || true
sleep 1

# 启动新的MCP服务（HTTP/SSE 模式，通过 MCP proxy 管理）
nohup python -m paddleocr_mcp --http --host 0.0.0.0 --port 9001 --verbose > "$MCP_LOG" 2>&1 &
MCP_PID=$!

# 保存PID
echo $MCP_PID > "$MCP_PID_FILE"

# 等待启动
sleep 3

# 验证启动
if kill -0 $MCP_PID 2>/dev/null; then
    echo "✅ MCP 服务已启动"
    echo "   PID: $MCP_PID"
    echo "   日志: tail -f $MCP_LOG"
    echo ""
    echo "验证日志："
    tail -5 "$MCP_LOG"
else
    echo "❌ MCP 服务启动失败"
    cat "$MCP_LOG" | tail -20
    exit 1
fi
