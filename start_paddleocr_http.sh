#!/bin/bash

# Start PaddleOCR MCP Server in HTTP Mode on Host
# 用于 HTTP/SSE 直连测试

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Prefer project virtualenv Python when available.
PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
    PYTHON_BIN="$(command -v python3 || true)"
fi

echo "=========================================="
echo "Starting PaddleOCR MCP Server (HTTP Mode)"
echo "=========================================="
echo ""

# Check if python is available
if [ -z "$PYTHON_BIN" ]; then
    echo "Error: no usable Python found (.venv/bin/python or python3)"
    exit 1
fi

# Set environment variables
export PYTHONPATH="$SCRIPT_DIR:${PYTHONPATH:-}"
export PYTHONUNBUFFERED=1
export PADDLEOCR_MCP_PIPELINE="OCR"
export PADDLEOCR_MCP_PPOCR_SOURCE="local"
export PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK="True"

echo "Environment:"
echo "  Python: $($PYTHON_BIN --version)"
echo "  PYTHONPATH: $PYTHONPATH"
echo ""

echo "Starting server..."
echo "  Host: 0.0.0.0"
echo "  Port: 9001"
echo "  Transport: HTTP/SSE (streamable-http)"
echo ""

# Start the server using explicit script entrypoint
"$PYTHON_BIN" "$SCRIPT_DIR/mcp/servers/paddleocr/server.py"

