FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/apps/agent/src

WORKDIR /app

COPY apps/agent/requirements.txt /app/apps/agent/requirements.txt
RUN pip install --no-cache-dir -r /app/apps/agent/requirements.txt

COPY apps/agent /app/apps/agent

CMD ["celery", "-A", "casepilot_agent.tasks:celery_app", "worker", "--loglevel=INFO", "--concurrency=2"]
