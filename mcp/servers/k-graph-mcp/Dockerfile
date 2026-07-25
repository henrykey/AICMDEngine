ARG PYTHON_BASE_IMAGE=python:3.12-slim
FROM ${PYTHON_BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MCP_TRANSPORT=streamable-http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=9013

WORKDIR /app

ARG PIP_INDEX_URL=

COPY pyproject.toml ./

RUN --mount=type=cache,target=/root/.cache/pip \
    python -c 'import subprocess, sys, tomllib; config = tomllib.load(open("pyproject.toml", "rb")); requirements = config["build-system"]["requires"] + config["project"]["dependencies"]; subprocess.check_call([sys.executable, "-m", "pip", "install", *requirements])'

COPY README.md ./
COPY k_graph_mcp/ ./k_graph_mcp/

RUN pip install --no-build-isolation --no-deps .

EXPOSE 9013

CMD ["python", "-m", "k_graph_mcp"]
