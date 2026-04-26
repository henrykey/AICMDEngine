ARG PYTHON_BASE_IMAGE=python:3.12-slim
FROM ${PYTHON_BASE_IMAGE}

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PDF2MD_ENH_OUTPUT_DIR=/app/data/output \
    PYTHONPATH=/app

WORKDIR /app

ARG PIP_INDEX_URL=
ARG APT_MIRROR=

RUN if [ -n "${APT_MIRROR}" ]; then \
      if [ -f /etc/apt/sources.list ]; then \
        sed -i "s|http://deb.debian.org/debian|${APT_MIRROR}|g; s|http://security.debian.org/debian-security|${APT_MIRROR}-security|g" /etc/apt/sources.list; \
      fi; \
      if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i "s|http://deb.debian.org/debian|${APT_MIRROR}|g; s|http://security.debian.org/debian-security|${APT_MIRROR}-security|g" /etc/apt/sources.list.d/debian.sources; \
      fi; \
    fi \
    && apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

# 1. 先复制 requirements.txt，利用 Docker 缓存层
COPY requirements.txt .
COPY .wheelhouse/ /opt/wheelhouse/

# 2. 安装 Python 依赖
RUN if find /opt/wheelhouse -type f ! -name '.gitkeep' | grep -q .; then \
      pip install --no-index --find-links=/opt/wheelhouse -r requirements.txt; \
    elif [ -n "${PIP_INDEX_URL}" ]; then \
      pip install -i "${PIP_INDEX_URL}" --no-cache-dir -r requirements.txt; \
    else \
      pip install --no-cache-dir -r requirements.txt; \
    fi

# 3. 复制剩余代码
COPY . /app/PDF2MDEnhanced

# 4. 创建数据目录
RUN mkdir -p /app/data/input /app/data/output /app/data/tasks

EXPOSE 9010

CMD ["python", "-m", "PDF2MDEnhanced.__main__", "--http", "--host", "0.0.0.0", "--port", "9010"]
