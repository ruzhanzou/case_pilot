"""Isolated real-provider acceptance services; credentials stay in the existing environment."""
import os
import sys
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

root = Path(__file__).resolve().parents[2]
output = root / "output/generation-strategy-acceptance-20261021"
output.mkdir(parents=True, exist_ok=True)
values = {**dotenv_values(root / ".env"), **os.environ}
url = make_url(values["DATABASE_URL"]).set(host="127.0.0.1", database="casepilot_strategy_acceptance_20261021")
env = {**values, "DATABASE_URL": url.render_as_string(hide_password=False),
    "REDIS_URL": "redis://127.0.0.1:6388/0", "CELERY_BROKER_URL": "redis://127.0.0.1:6388/1",
    "CELERY_RESULT_BACKEND": "redis://127.0.0.1:6388/2",
    "CASEPILOT_KNOWLEDGE_STORAGE_PATH": str(output / "knowledge"),
    "CASEPILOT_WEB_ORIGIN": "http://localhost:3018", "CASEPILOT_SEED_DEMO_DATA": "true",
    "CASEPILOT_SESSION_COOKIE_NAME": "casepilot_strategy_acceptance", "CASEPILOT_ENV": "development",
    "PYTHONPATH": f"{root / 'apps/api/src'}:{root / 'apps/agent/src'}"}
mode = sys.argv[1]
python_bin = Path(sys.executable).parent
if mode == "migrate":
    engine = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with engine.connect() as connection:
        if not connection.execute(text("select 1 from pg_database where datname=:name"), {"name": url.database}).scalar():
            connection.execute(text('CREATE DATABASE "casepilot_strategy_acceptance_20261021"'))
    executable, args = python_bin / "alembic", ["alembic", "-c", "apps/api/alembic.ini", "upgrade", "head"]
elif mode == "api":
    executable, args = python_bin / "uvicorn", ["uvicorn", "casepilot_api.main:app", "--host", "127.0.0.1", "--port", "8018"]
elif mode == "worker":
    executable, args = python_bin / "celery", ["celery", "-A", "casepilot_agent.tasks:celery_app", "worker", "--beat", "--pool=solo", "--loglevel=INFO", "--schedule", str(output / "beat")]
else:
    raise SystemExit("mode: migrate | api | worker")
os.execve(str(executable), args, env)
