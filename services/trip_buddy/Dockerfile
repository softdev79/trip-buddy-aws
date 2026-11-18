# Build from the repo root:  docker build -f services/trip_buddy/Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/shared \
    SERVICE_NAME=trip_buddy \
    PORT=8000

WORKDIR /app
COPY shared/requirements.txt shared/requirements.txt
COPY services/trip_buddy/requirements.txt services/trip_buddy/requirements.txt
RUN pip install -r services/trip_buddy/requirements.txt

COPY shared/ shared/
COPY services/trip_buddy/ services/trip_buddy/

# Run as a non-root user
RUN useradd --uid 10001 --create-home app
USER app
WORKDIR /app/services/trip_buddy

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import os, urllib.request as u; u.urlopen('http://127.0.0.1:%s/health' % os.environ['PORT'], timeout=2)"
CMD ["python", "app.py"]
