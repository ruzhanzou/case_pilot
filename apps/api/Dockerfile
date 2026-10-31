FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/apps/api/src:/app/apps/agent/src

WORKDIR /app

COPY apps/api/pyproject.toml /tmp/casepilot-api/pyproject.toml
RUN mkdir -p /tmp/casepilot-api/src/casepilot_api \
    && touch /tmp/casepilot-api/src/casepilot_api/__init__.py \
    && pip install --no-cache-dir /tmp/casepilot-api

COPY apps/api /app/apps/api
# API Responses adapters and uploaded-case validation share pure Agent contracts.
COPY apps/agent/src /app/apps/agent/src

EXPOSE 8000

CMD ["uvicorn", "casepilot_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
