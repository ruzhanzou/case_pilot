"""Isolated real-provider acceptance services; credentials stay in the existing environment."""
import os
import sys
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

root = Path(__file__).resolve().parents[2]
output = root / "output/maturity-acceptance-20261023"
output.mkdir(parents=True, exist_ok=True)
values = {**dotenv_values(root / ".env"), **os.environ}
url = make_url(values["DATABASE_URL"]).set(host="127.0.0.1", database="casepilot_maturity_acceptance_20261023")
env = {**values, "DATABASE_URL": url.render_as_string(hide_password=False),
    "REDIS_URL": "redis://127.0.0.1:6392/0", "CELERY_BROKER_URL": "redis://127.0.0.1:6392/1",
    "CELERY_RESULT_BACKEND": "redis://127.0.0.1:6392/2",
    "CASEPILOT_KNOWLEDGE_STORAGE_PATH": str(output / "knowledge"),
    "CASEPILOT_WEB_ORIGIN": "http://localhost:3029", "CASEPILOT_SEED_DEMO_DATA": "true",
    "CASEPILOT_SESSION_COOKIE_NAME": "casepilot_maturity_acceptance", "CASEPILOT_ENV": "development",
    "PYTHONPATH": f"{root / 'apps/api/src'}:{root / 'apps/agent/src'}"}
mode = sys.argv[1]
python_bin = Path(sys.executable).parent
if mode == "migrate":
    engine = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with engine.connect() as connection:
        if not connection.execute(text("select 1 from pg_database where datname=:name"), {"name": url.database}).scalar():
            connection.execute(text('CREATE DATABASE "casepilot_maturity_acceptance_20261023"'))
    executable, args = python_bin / "alembic", ["alembic", "-c", "apps/api/alembic.ini", "upgrade", "head"]
elif mode == "api":
    executable, args = python_bin / "uvicorn", ["uvicorn", "casepilot_api.main:app", "--host", "localhost", "--port", "8029"]
elif mode == "worker-crash":
    # Supervise only the isolated acceptance worker; kill its orphan beat child
    # after the intentional process loss, then restart the normal real worker.
    import signal
    import subprocess
    crash_env = {**env, "CASEPILOT_QA_FAULT_MODE": "sigkill"}
    child = subprocess.Popen([sys.executable, __file__, "worker-fault"],
                             env=crash_env, start_new_session=True)
    result = child.wait()
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    if result != -signal.SIGKILL:
        raise SystemExit(f"Expected synthetic SIGKILL, got {result}")
    print("Synthetic worker killed; restarting normal worker", flush=True)
    os.execve(sys.executable, [sys.executable, __file__, "worker"], env)
elif mode == "worker-fault":
    # Opt-in, one-shot worker fault on synthetic acceptance input only. All
    # subsequent calls use the configured real provider unchanged.
    import json
    token = os.environ["CASEPILOT_QA_FAULT_TOKEN"]
    if not token.startswith("maturity-") or not token.replace("-", "").isalnum():
        raise SystemExit("invalid QA fault token")
    os.environ.update(env)
    sys.path[:0] = [str(root / "apps/api/src"), str(root / "apps/agent/src")]
    from casepilot_agent import tasks
    real_factory = tasks.create_provider
    marker = output / f"{token}.json"

    class FaultOnceProvider:
        def __init__(self, provider):
            self.provider = provider

        def __getattr__(self, name):
            return getattr(self.provider, name)

        def complete(self, **kwargs):
            if kwargs.get("stage") == "rewrite.batch" and token in json.dumps(kwargs.get("payload", {})):
                try:
                    with marker.open("x") as stream:
                        json.dump({"injected_stage": "rewrite.batch", "token": token}, stream)
                except FileExistsError:
                    pass
                else:
                    if os.environ.get("CASEPILOT_QA_FAULT_MODE") == "sigkill":
                        import signal
                        os.kill(os.getpid(), signal.SIGKILL)
                    raise RuntimeError("synthetic_acceptance_worker_failure")
            return self.provider.complete(**kwargs)

    if os.environ.get("CASEPILOT_QA_FAULT_STAGE") == "parse":
        original_parse = tasks.parse_document

        def crash_during_parse(path, mime_type):
            if path.suffix == ".txt" and token in path.read_text():
                try:
                    with marker.open("x") as stream:
                        json.dump({"injected_stage": "attachment.parse", "token": token}, stream)
                except FileExistsError:
                    pass
                else:
                    import signal
                    os.kill(os.getpid(), signal.SIGKILL)
            return original_parse(path, mime_type)

        tasks.parse_document = crash_during_parse

    tasks.create_provider = lambda *args, **kwargs: FaultOnceProvider(real_factory(*args, **kwargs))
    tasks.celery_app.worker_main(["worker", "--beat", "--pool=solo", "--loglevel=INFO",
                                 "--schedule", str(output / "beat")])
    raise SystemExit(0)
elif mode == "worker-container":
    # Use the shipped OCR dependencies with current source, isolated DB/storage,
    # and scoped environment names (credentials never appear in process arguments).
    import shutil
    container_env = {**env,
        "DATABASE_URL": url.set(host="host.docker.internal").render_as_string(hide_password=False),
        "REDIS_URL": "redis://host.docker.internal:6392/0",
        "CELERY_BROKER_URL": "redis://host.docker.internal:6392/1",
        "CELERY_RESULT_BACKEND": "redis://host.docker.internal:6392/2",
        "CASEPILOT_KNOWLEDGE_STORAGE_PATH": "/acceptance/knowledge",
        "PYTHONPATH": "/app/apps/agent/src"}
    names = set(dotenv_values(root / ".env")) | {
        "DATABASE_URL", "REDIS_URL", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND",
        "CASEPILOT_KNOWLEDGE_STORAGE_PATH", "CASEPILOT_ENV", "PYTHONPATH"}
    executable = shutil.which("docker")
    if not executable:
        raise SystemExit("Docker is required for the OCR acceptance worker")
    secondary = os.environ.get("CASEPILOT_QA_SECONDARY_WORKER") == "1"
    container_name = "casepilot-maturity-ocr-20261023" + ("-secondary" if secondary else "")
    args = ["docker", "run", "--rm", "--name", container_name,
        "-v", f"{root / 'apps/agent/src'}:/app/apps/agent/src:ro",
        "-v", f"{output / 'knowledge'}:/acceptance/knowledge"]
    host_ip = os.environ.get("CASEPILOT_QA_DOCKER_HOST_IP")
    if host_ip:
        import ipaddress
        args.extend(["--add-host", f"host.docker.internal:{ipaddress.ip_address(host_ip)}"])
    for name in sorted(names):
        if name in container_env and container_env[name] is not None:
            args.extend(["--env", name])
    args.extend(["casepilot-agent:local", "celery", "-A", "casepilot_agent.tasks:celery_app",
        "worker", "--pool=solo", "--prefetch-multiplier=1", "--loglevel=INFO"])
    if not secondary:
        args.extend(["--beat", "--schedule", "/tmp/acceptance-beat"])
    env = container_env
elif mode == "worker":
    executable, args = python_bin / "celery", ["celery", "-A", "casepilot_agent.tasks:celery_app", "worker", "--beat", "--pool=solo", "--loglevel=INFO", "--schedule", str(output / "beat")]
else:
    raise SystemExit("mode: migrate | api | worker")
os.execve(str(executable), args, env)
