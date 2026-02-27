#!/bin/bash
# 用于启动Docker PyPaddleOCR MCP 的包装脚本
# 这个脚本保持容器内的MCP服务持久运行

set -e

# 启动paddleocr-mcp容器中的MCP服务（使用docker run保持完整连接）
# 使用 -i --interactive 标志保持stdin打开
# 使用 -t --tty     标志保持tty连接

echo "启动Docker PaddleOCR MCP（stdio模式，持久连接）..."

# 杀死任何现有的进程
docker kill paddleocr-mcp-stdio 2>/dev/null || true
sleep 1

# 启动新容器，保持完整的stdin/stdout连接
# 关键：使用 --rm 参数，进程结束时自动删除容器
# 使用 -i 保持stdin打开（即使没有tty）
docker run \
  --rm \
  -i \
  --name paddleocr-mcp-stdio \
  --volumes-from paddleocr-mcp \
  paddleocr-mcp:latest \
  python -m paddleocr_mcp --verbose

echo "✓ MCP服务已启动 (PID: $!)"
