FROM python:3.12-slim

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PDF2MD_ENH_OUTPUT_DIR=/app/data/output \
    PYTHONPATH=/app

WORKDIR /app

# 🔥 核心修复：手动写入阿里云 apt 源，彻底解决网络问题
# 注意：bookworm 是 Debian 12 的代号，python:3.12-slim 基于 Debian Bookworm
RUN echo "deb http://mirrors.aliyun.com/debian/ bookworm main contrib non-free non-free-firmware" > /etc/apt/sources.list && \
    echo "deb http://mirrors.aliyun.com/debian-security bookworm-security main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
    apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

# 1. 先复制 requirements.txt，利用 Docker 缓存层
COPY requirements.txt .

# 2. 安装 Python 依赖
# 指定阿里云 pip 源，防止下载超时
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt

# 3. 复制剩余代码
COPY . /app/PDF2MDEnhanced

# 4. 创建数据目录
RUN mkdir -p /app/data/input /app/data/output /app/data/tasks

EXPOSE 9010

CMD ["python", "-m", "PDF2MDEnhanced.__main__", "--http", "--host", "0.0.0.0", "--port", "9010"]
