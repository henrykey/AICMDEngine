# PDF2MD MCP Server - Dockerfile
# HTTP/SSE 模式运行

FROM python:3.12-slim

WORKDIR /app

# 替换 apt 源为阿里云
RUN echo "deb http://mirrors.aliyun.com/debian/ bookworm main contrib non-free non-free-firmware" > /etc/apt/sources.list && \
    echo "deb http://mirrors.aliyun.com/debian-security bookworm-security main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
    apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

# 安装Python依赖
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ -r /tmp/requirements.txt

# 创建正确的包结构
WORKDIR /app/PDF2MD
COPY . /app/PDF2MD/

# 环境变量
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# VLM 配置（生产环境应使用环境变量或配置中心）
ENV VLM_MODEL_PROVIDER=qwen
ENV QWEN_API_KEY=${QWEN_API_KEY}
ENV QWEN_BASE_URL=${QWEN_BASE_URL:-https://dashscope.aliyuncs.com/compatible-mode/v1}
ENV QWEN_MODEL_NAME=${QWEN_MODEL_NAME:-qwen3-vl-flash-2026-01-22}
ENV PDF2MD_ALLOW_EXTERNAL_VLM=${PDF2MD_ALLOW_EXTERNAL_VLM:-true}

# 健康检查 - 使用 nc (netcat) 检查端口
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD nc -z localhost 9003 || exit 1

# 启动 - 使用 -m 模式
CMD ["python", "-m", "PDF2MD.__main__", "--http", "--host", "0.0.0.0", "--port", "9003"]
