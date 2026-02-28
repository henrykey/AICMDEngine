#!/bin/bash

set -e

PADDLE_PID_FILE="/tmp/paddleocr-mcp.pid"
WORD_PID_FILE="/tmp/office-word-mcp.pid"

stop_by_pid_file() {
  local name="$1"
  local pid_file="$2"

  if [ ! -f "$pid_file" ]; then
    echo "- $name 未发现 PID 文件"
    return 0
  fi

  local pid
  pid=$(cat "$pid_file")
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    sleep 1
    if kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid" 2>/dev/null || true
    fi
    echo "✅ $name 已停止 (PID: $pid)"
  else
    echo "- $name 进程已不存在 (PID: $pid)"
  fi

  rm -f "$pid_file"
}

echo "🛑 停止 Host MCP 服务"
echo "===================="

stop_by_pid_file "PaddleOCR MCP" "$PADDLE_PID_FILE"
stop_by_pid_file "Office Word MCP" "$WORD_PID_FILE"

echo ""
echo "✅ Host MCP 服务停止完成"
