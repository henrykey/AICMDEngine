#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

PADDLE_DIR="$PROJECT_DIR/mcp/servers/paddleocr"
WORD_DIR="$PROJECT_DIR/mcp/servers/office-word"

PADDLE_LOG="/tmp/paddleocr-host.log"
WORD_LOG="/tmp/office-word-host.log"

PADDLE_PID_FILE="/tmp/paddleocr-mcp.pid"
WORD_PID_FILE="/tmp/office-word-mcp.pid"

start_service() {
  local name="$1"
  local work_dir="$2"
  local log_file="$3"
  local pid_file="$4"
  shift 4
  local cmd=("$@")

  if [ -f "$pid_file" ]; then
    local old_pid
    old_pid=$(cat "$pid_file")
    if kill -0 "$old_pid" 2>/dev/null; then
      echo "✓ $name 已在运行 (PID: $old_pid)"
      return 0
    fi
  fi

  nohup env "${cmd[@]}" > "$log_file" 2>&1 &
  local new_pid=$!
  echo "$new_pid" > "$pid_file"
  sleep 2

  if kill -0 "$new_pid" 2>/dev/null; then
    echo "✅ $name 启动成功 (PID: $new_pid)"
    echo "   日志: $log_file"
  else
    echo "❌ $name 启动失败"
    tail -n 40 "$log_file" 2>/dev/null || true
    return 1
  fi
}

echo "🚀 启动 Host MCP 服务（后台模式）"
echo "================================"

start_service \
  "PaddleOCR MCP" \
  "$PADDLE_DIR" \
  "$PADDLE_LOG" \
  "$PADDLE_PID_FILE" \
  PYTHONUNBUFFERED=1 \
  PADDLEOCR_MCP_PIPELINE=OCR \
  PADDLEOCR_MCP_PPOCR_SOURCE=local \
  PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True \
  bash -lc "cd '$PADDLE_DIR' && python server.py"

start_service \
  "Office Word MCP" \
  "$WORD_DIR" \
  "$WORD_LOG" \
  "$WORD_PID_FILE" \
  PYTHONUNBUFFERED=1 \
  MCP_TRANSPORT=sse \
  MCP_HOST=0.0.0.0 \
  MCP_PORT=9002 \
  FASTMCP_LOG_LEVEL=INFO \
  bash -lc "cd '$WORD_DIR' && python -m word_mcp_server"

echo ""
echo "🎉 Host MCP 服务启动完成"
echo "   PaddleOCR: http://127.0.0.1:9001/sse"
echo "   OfficeWord: http://127.0.0.1:9002/sse"
