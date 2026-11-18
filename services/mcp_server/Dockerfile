# Build from the repo root:  docker build -f services/mcp_server/Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/shared \
    SERVICE_NAME=mcp_server \
    PORT=8001

WORKDIR /app
COPY shared/requirements.txt shared/requirements.txt
COPY services/mcp_server/requirements.txt services/mcp_server/requirements.txt
RUN pip install -r services/mcp_server/requirements.txt

COPY shared/ shared/
COPY services/mcp_server/ services/mcp_server/

# Run as a non-root user
RUN useradd --uid 10001 --create-home app
USER app
WORKDIR /app/services/mcp_server

EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import os, urllib.request as u; u.urlopen('http://127.0.0.1:%s/health' % os.environ['PORT'], timeout=2)"
CMD ["python", "server.py"]
