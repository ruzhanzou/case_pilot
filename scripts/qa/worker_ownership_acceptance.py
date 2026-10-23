"""SIGKILL ownership/recovery checks in a fresh disposable PostgreSQL database."""
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import UUID, uuid4

root = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(root / 'apps/api/src'), str(root / 'apps/agent/src')]
if len(sys.argv) > 1:
    from casepilot_agent.store import JobStore
    store = JobStore(os.environ['DATABASE_URL'], os.environ['REDIS_URL'])
    with store.execution_guard(UUID(sys.argv[1])) as acquired:
        assert acquired
        with store.connection() as connection:
            assert store.claim_job(connection, UUID(sys.argv[1]))
        print('claimed', flush=True)
        import time
        time.sleep(120)
    raise SystemExit(0)

from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

url = make_url(dotenv_values(root / '.env')['DATABASE_URL']).set(host='127.0.0.1')
name = 'casepilot_ownership_' + uuid4().hex[:10]
admin = create_engine(url.set(database='postgres'), isolation_level='AUTOCOMMIT')
with admin.connect() as connection:
    connection.execute(text(f'CREATE DATABASE {name}'))
os.environ.update(DATABASE_URL=url.set(database=name).render_as_string(hide_password=False),
                  REDIS_URL='redis://127.0.0.1:6392/0', CASEPILOT_AGENT_PROVIDER='mock')
child = None
try:
    subprocess.run([str(root/'.venv/bin/alembic'), '-c', 'apps/api/alembic.ini', 'upgrade', 'head'],
                   cwd=root, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    from casepilot_api.models import Space, GenerationJob
    from casepilot_agent.store import JobStore
    from casepilot_agent import tasks
    engine = create_engine(os.environ['DATABASE_URL'])
    with Session(engine) as db:
        space = Space(name='Process-loss acceptance')
        db.add(space); db.flush(); space_id = space.id
        job = GenerationJob(space_id=space_id, operation='knowledge_qa', status='queued',
                            input_payload={}, output_payload={'preserved': 'partial evidence'})
        db.add(job); db.commit(); job_id = job.id
    child = subprocess.Popen([sys.executable, __file__, str(job_id)], stdout=subprocess.PIPE, text=True)
    assert child.stdout.readline().strip() == 'claimed'
    store = JobStore(os.environ['DATABASE_URL'], os.environ['REDIS_URL'])
    with store.execution_guard(job_id) as acquired:
        assert not acquired, 'A duplicate must not steal a live task'
    assert tasks.recover_interrupted_jobs() == {'recovered': 0}
    child.kill(); child.wait(timeout=10)
    assert child.returncode < 0
    assert tasks.recover_interrupted_jobs() == {'recovered': 1}
    with store.connection() as connection:
        saved = store.get_job(connection, job_id)
    assert saved['status'] == 'failed'
    assert saved['error_code'] == 'WorkerInterrupted'
    assert saved['output_payload'] == {'preserved': 'partial evidence'}
    assert tasks.recover_interrupted_jobs() == {'recovered': 0}
    # A surviving worker must not write after losing its ownership connection.
    from casepilot_agent.store import _execution_connection
    from sqlalchemy.exc import DBAPIError
    with Session(engine) as db:
        second = GenerationJob(space_id=space_id, operation='knowledge_qa', status='queued',
                               input_payload={}, output_payload={'preserved': 'before disconnect'})
        db.add(second); db.commit(); second_id = second.id
    lost_connection = False
    try:
        with store.execution_guard(second_id) as acquired:
            assert acquired
            with store.connection() as connection:
                assert store.claim_job(connection, second_id)
            backend = _execution_connection.get().scalar(text('select pg_backend_pid()'))
            with engine.begin() as killer:
                assert killer.scalar(text('select pg_terminate_backend(:pid)'), {'pid': backend})
            with store.connection() as connection:
                store.update_job(connection, second_id, status='completed', output_payload={'unsafe': True})
    except DBAPIError:
        lost_connection = True
    assert lost_connection, 'Ownership loss must block a late write'
    assert tasks.recover_interrupted_jobs() == {'recovered': 1}
    with store.connection() as connection:
        disconnected = store.get_job(connection, second_id)
    assert disconnected['status'] == 'failed'
    assert disconnected['output_payload'] == {'preserved': 'before disconnect'}
    from casepilot_api.models import KnowledgeSource, KnowledgeDocument
    with Session(engine) as db:
        source = KnowledgeSource(space_id=space_id, name='Partial upload', status='parsing')
        db.add(source); db.flush(); source_id = source.id
        doc_ids = []
        for status in ('ready', 'parsing', 'uploaded'):
            document = KnowledgeDocument(source_id=source_id, space_id=space_id,
                original_name=status+'.txt', mime_type='text/plain', storage_key=uuid4().hex,
                size_bytes=1, checksum='synthetic', status=status)
            db.add(document); db.flush(); doc_ids.append(document.id)
        db.commit()
    # A separate DB connection must not recover a currently owned upload.
    from concurrent.futures import ThreadPoolExecutor
    with store.execution_guard(source_id) as acquired:
        assert acquired
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(tasks.recover_interrupted_uploads).result() == {'recovered': 0}
    assert tasks.recover_interrupted_uploads() == {'recovered': 1}
    assert tasks.recover_interrupted_uploads() == {'recovered': 0}
    with Session(engine) as db:
        assert [db.get(KnowledgeDocument, item).status for item in doc_ids] == ['ready', 'failed', 'failed']
        assert db.get(KnowledgeSource, source_id).error_code == 'WorkerInterrupted'
    # Constructors fail before claim: these must not strand queued/uploaded rows.
    with Session(engine) as db:
        early_job = GenerationJob(space_id=space_id, operation='draft_brief', status='queued', input_payload={})
        early_source = KnowledgeSource(space_id=space_id, name='Initialization failure', status='uploaded', persistence='space')
        db.add_all([early_job, early_source]); db.flush()
        early_doc = KnowledgeDocument(source_id=early_source.id, space_id=space_id,
            original_name='initialization.txt', mime_type='text/plain', storage_key=uuid4().hex,
            size_bytes=1, checksum='synthetic', status='uploaded')
        db.add(early_doc); db.flush()
        early_job_id, early_source_id, early_doc_id = early_job.id, early_source.id, early_doc.id
        db.commit()
    original_factory, original_embedding, original_settings = tasks.create_provider, tasks.create_embedding_provider, tasks.settings
    def broken_factory(*args, **kwargs):
        raise ValueError('synthetic_initialization_failure')
    try:
        tasks.create_provider = broken_factory
        tasks.create_embedding_provider = broken_factory
        tasks.settings = tasks.settings.model_copy(update={'embedding_fallback_enabled': False})
        for action, item in ((tasks.draft_test_brief, early_job_id), (tasks.index_knowledge_source, early_source_id)):
            try:
                action(str(item))
            except ValueError as error:
                assert str(error) == 'synthetic_initialization_failure'
            else:
                raise AssertionError('Expected initialization failure')
    finally:
        tasks.create_provider, tasks.create_embedding_provider, tasks.settings = original_factory, original_embedding, original_settings
    with Session(engine) as db:
        assert db.get(GenerationJob, early_job_id).status.value == 'failed'
        assert db.get(KnowledgeSource, early_source_id).status == 'failed'
        assert db.get(KnowledgeDocument, early_doc_id).status == 'failed'
    evidence = {'live_task_not_stolen': True, 'killed_process_exit': child.returncode,
                'orphan_recovered_once': True, 'partial_output_preserved': True,
                'status': saved['status'], 'error_code': saved['error_code'],
                'ownership_connection_loss_blocks_late_write': True,
                'upload_recovery_preserves_ready_documents': True, 'live_upload_not_stolen': True, 'initialization_failures_are_retryable': True}
    path = root/'output/maturity-acceptance-20261023/worker-ownership.json'
    path.write_text(json.dumps(evidence, indent=2)+'\n')
    print(json.dumps(evidence))
finally:
    if child is not None and child.poll() is None:
        child.kill(); child.wait(timeout=10)
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE {name} WITH (FORCE)'))
