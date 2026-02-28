#!/bin/bash

# Start PaddleOCR MCP Server in HTTP Mode on Host
# 用于 HTTP/SSE 直连测试

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================="
echo "Starting PaddleOCR MCP Server (HTTP Mode)"
echo "=========================================="
echo ""

# Check if python is available
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 not found"
    exit 1
fi

# Set environment variables
export PYTHON_PATH="$SCRIPT_DIR:$PYTHON_PATH"
export PYTHONUNBUFFERED=1
export PADDLEOCR_MCP_PIPELINE="OCR"
export PADDLEOCR_MCP_PPOCR_SOURCE="local"
export PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK="True"

echo "Environment:"
echo "  Python: $(python3 --version)"
echo "  PATH: $PYTHON_PATH"
echo ""

echo "Starting server..."
echo "  Host: 0.0.0.0"
echo "  Port: 9001"
echo "  Transport: HTTP/SSE (streamable-http)"
echo ""

# Start the server using Python module
cd "$SCRIPT_DIR/mcp/servers/paddleocr"
python3 -m __main__ --http --host 0.0.0.0 --port 9001 --verbose

