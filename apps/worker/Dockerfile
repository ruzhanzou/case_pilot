FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/apps/api/src

WORKDIR /app

COPY apps/api/requirements.txt /app/apps/api/requirements.txt
RUN pip install --no-cache-dir -r /app/apps/api/requirements.txt

COPY apps/api /app/apps/api

CMD ["celery", "-A", "casepilot_api.worker:celery_app", "worker", "--loglevel=INFO", "--concurrency=2"]
