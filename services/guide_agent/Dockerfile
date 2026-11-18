# Build from the repo root:  docker build -f services/guide_agent/Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/shared \
    SERVICE_NAME=guide_agent \
    PORT=9999

WORKDIR /app
COPY shared/requirements.txt shared/requirements.txt
COPY services/guide_agent/requirements.txt services/guide_agent/requirements.txt
RUN pip install -r services/guide_agent/requirements.txt

COPY shared/ shared/
COPY services/guide_agent/ services/guide_agent/

# Run as a non-root user
RUN useradd --uid 10001 --create-home app
USER app
WORKDIR /app/services/guide_agent

EXPOSE 9999
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import os, urllib.request as u; u.urlopen('http://127.0.0.1:%s/health' % os.environ['PORT'], timeout=2)"
CMD ["python", "agent.py"]
