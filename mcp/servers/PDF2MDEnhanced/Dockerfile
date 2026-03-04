# PDF2MD Enhanced MCP Server - Dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app/PDF2MDEnhanced

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV PDF2MD_ENH_OUTPUT_DIR=/app/data/output

RUN mkdir -p /app/data/input /app/data/output /app/data/tasks

EXPOSE 9010

CMD ["python", "-m", "PDF2MDEnhanced.__main__", "--http", "--host", "0.0.0.0", "--port", "9010"]
