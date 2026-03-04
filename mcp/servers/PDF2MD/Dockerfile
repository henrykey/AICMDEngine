# PDF2MD MCP Server - Dockerfile
# HTTP/SSE 模式运行，供独立部署或 mcp-router 直连

FROM python:3.12-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgomp1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# 安装Python依赖
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# 复制应用代码
COPY . /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# VLM配置（生产环境应使用环境变量或配置中心）
ENV VLM_MODEL_PROVIDER=qwen
ENV QWEN_API_KEY=${QWEN_API_KEY}
ENV QWEN_BASE_URL=${QWEN_BASE_URL:-https://dashscope.aliyuncs.com/compatible-mode/v1}
ENV QWEN_MODEL_NAME=${QWEN_MODEL_NAME:-qwen3-vl-flash-2026-01-22}
ENV PDF2MD_ALLOW_EXTERNAL_VLM=${PDF2MD_ALLOW_EXTERNAL_VLM:-true}

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:9003/sse || exit 1

# HTTP/SSE 模式启动，监听 9003 端口
CMD ["python", "-m", "PDF2MD.__main__", "--http", "--host", "0.0.0.0", "--port", "9003"]
