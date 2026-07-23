ARG PYTHON_BASE_IMAGE=python:3.11-slim
FROM ${PYTHON_BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MCP_TRANSPORT=sse \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=9012

ARG APP_UID=1000
ARG APP_GID=1000
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
    && apt-get update \
    && apt-get install -y --no-install-recommends \
      libreoffice-writer \
      fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid "${APP_GID}" app \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" --create-home app

WORKDIR /app
COPY . /app
RUN if [ -n "${PIP_INDEX_URL}" ]; then \
      pip install --no-cache-dir -i "${PIP_INDEX_URL}" .; \
    else \
      pip install --no-cache-dir .; \
    fi \
    && mkdir -p /documents \
    && chown app:app /documents

USER app

EXPOSE 9012
VOLUME ["/documents"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import socket; s=socket.create_connection(('127.0.0.1', 9012), 2); s.close()"

CMD ["docs-converter"]
