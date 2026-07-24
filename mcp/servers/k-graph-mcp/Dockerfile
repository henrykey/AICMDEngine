ARG PYTHON_BASE_IMAGE=python:3.12-slim
FROM ${PYTHON_BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MCP_TRANSPORT=streamable-http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=9013

WORKDIR /app

ARG PIP_INDEX_URL=

COPY pyproject.toml README.md ./
COPY k_graph_mcp/ ./k_graph_mcp/

RUN if [ -n "${PIP_INDEX_URL}" ]; then \
      pip install --no-cache-dir -i "${PIP_INDEX_URL}" .; \
    else \
      pip install --no-cache-dir .; \
    fi

EXPOSE 9013

CMD ["python", "-m", "k_graph_mcp"]
