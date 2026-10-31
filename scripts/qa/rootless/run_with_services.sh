#!/bin/bash
set -euo pipefail
umask 077
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
BASE=${CASEPILOT_QA_RUNTIME:-"$REPO/../workbench-infra"}
ROOT=$BASE/root
export LD_LIBRARY_PATH="$ROOT/usr/lib/x86_64-linux-gnu"
export ORT_DISABLE_TELEMETRY=1 OTEL_SDK_DISABLED=true
export OTEL_TRACES_EXPORTER=none OTEL_METRICS_EXPORTER=none OTEL_LOGS_EXPORTER=none
export NEXT_TELEMETRY_DISABLED=1 WRANGLER_SEND_METRICS=false WRANGLER_SEND_ERROR_REPORTS=false
export DO_NOT_TRACK=1 OPENAI_AGENTS_DISABLE_TRACING=1
DATA=$(mktemp -d "$BASE/pg-run-XXXXXX")
DATA=$(cd "$DATA" && pwd -P)
"$ROOT/usr/lib/postgresql/17/bin/initdb" -D "$DATA" -L "$ROOT/usr/share/postgresql/17" --auth=trust --no-locale --encoding=UTF8 >"$DATA-init.log"
"$ROOT/usr/lib/postgresql/17/bin/postgres" -D "$DATA" -p 5432 -h 127.0.0.1 -c unix_socket_directories='' >"$DATA/postgres.log" 2>&1 & PG=$!
"$ROOT/usr/bin/redis-server" --bind 127.0.0.1 --port 6379 --dir "$DATA" >"$DATA/redis.log" 2>&1 & RD=$!
cleanup() {
  kill "$PG" "$RD" 2>/dev/null || true
  wait "$PG" 2>/dev/null || true
  wait "$RD" 2>/dev/null || true
  if ! kill -0 "$PG" 2>/dev/null && ! kill -0 "$RD" 2>/dev/null; then
    printf '%s\n' '{"owned_services_stopped":true}' >"$DATA/qa-cleanup.json"
  fi
}
trap cleanup EXIT
for unused in {1..30}; do
  kill -0 "$PG" "$RD" 2>/dev/null || { echo "qa_service_start_failed" >&2; exit 1; }
  if "$ROOT/usr/lib/postgresql/17/bin/pg_isready" -h 127.0.0.1 -p 5432 >/dev/null; then break; fi
  sleep .2
done
# Never initialize/migrate an unrelated service already listening on the fixed port.
kill -0 "$PG" "$RD" 2>/dev/null || { echo "qa_service_start_failed" >&2; exit 1; }
ACTUAL_DATA=$("$ROOT/usr/lib/postgresql/17/bin/psql" -h 127.0.0.1 -U "$(id -un)" -d postgres -Atc 'SHOW data_directory')
[[ "$ACTUAL_DATA" == "$DATA" ]] || { echo "qa_database_identity_mismatch" >&2; exit 1; }
ACTUAL_REDIS_PID=$("$ROOT/usr/bin/redis-cli" -h 127.0.0.1 -p 6379 INFO server | sed -n 's/^process_id://p' | tr -d '\r')
[[ "$ACTUAL_REDIS_PID" == "$RD" ]] || { echo "qa_redis_identity_mismatch" >&2; exit 1; }
"$ROOT/usr/lib/postgresql/17/bin/psql" -h 127.0.0.1 -U "$(id -un)" -d postgres -c "CREATE USER casepilot SUPERUSER PASSWORD 'casepilot-local';" -c "CREATE DATABASE casepilot OWNER casepilot;" >/dev/null
cd "$REPO"
export PYTHONPATH=apps/api/src:apps/agent/src
export CASEPILOT_AGENT_PROVIDER=mock CASEPILOT_AI_MODE=mock
export CASEPILOT_KNOWLEDGE_STORAGE_PATH="$DATA/knowledge"
.venv/bin/python -c 'from casepilot_api.config import Settings; Settings.model_config["env_file"] = None; from alembic.config import main; main(argv=["-c", "apps/api/alembic.ini", "upgrade", "head"])' >"$DATA/migrations.log" 2>&1
if [[ "${CASEPILOT_QA_MARK_SYNTHETIC:-0}" == "1" ]]; then
  "$ROOT/usr/lib/postgresql/17/bin/psql" -h 127.0.0.1 -U casepilot -d casepilot \
    -c 'CREATE TABLE casepilot_qa_identity (id uuid PRIMARY KEY DEFAULT gen_random_uuid()); INSERT INTO casepilot_qa_identity DEFAULT VALUES;' >/dev/null
  SYSTEM_ID=$("$ROOT/usr/lib/postgresql/17/bin/psql" -h 127.0.0.1 -U casepilot -d casepilot -Atc 'SELECT system_identifier::text FROM pg_control_system()')
  SYNTHETIC_ID=$("$ROOT/usr/lib/postgresql/17/bin/psql" -h 127.0.0.1 -U casepilot -d casepilot -Atc 'SELECT id FROM casepilot_qa_identity')
  .venv/bin/python - "$DATA" "$SYSTEM_ID" "$SYNTHETIC_ID" "$(git rev-parse HEAD)" "$PG" "$RD" <<'PYIDENTITY'
import json, pathlib, subprocess, sys
from uuid import UUID
data, system_id, marker, head, pg, redis = sys.argv[1:]
assert system_id.isdecimal() and str(UUID(marker)) == marker
assert len(head) == 40 and all(c in "0123456789abcdef" for c in head)
assert pathlib.Path(data).resolve() == pathlib.Path(data)
with open(pathlib.Path(data) / "qa-startup-identity.json", "x") as output:
    json.dump({"datadir": data, "system_identifier": system_id, "synthetic_id": marker,
               "source_commit": head, "source_dirty": bool(subprocess.check_output(
                   ["git", "status", "--porcelain"])), "pg_pid": int(pg), "redis_pid": int(redis),
               "pg_datadir_verified": True, "redis_pid_verified": True}, output)
PYIDENTITY
fi
"$@"
