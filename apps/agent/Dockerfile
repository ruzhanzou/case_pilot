FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/apps/agent/src

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-chi-sim \
    && rm -rf /var/lib/apt/lists/*
COPY apps/agent/pyproject.toml /tmp/casepilot-agent/pyproject.toml
RUN mkdir -p /tmp/casepilot-agent/src/casepilot_agent \
    && touch /tmp/casepilot-agent/src/casepilot_agent/__init__.py \
    && pip install --no-cache-dir /tmp/casepilot-agent

COPY apps/agent /app/apps/agent

CMD ["celery", "-A", "casepilot_agent.tasks:celery_app", "worker", "--loglevel=INFO", "--concurrency=2"]
