"""Verify durable publication recovery against disposable PostgreSQL, including concurrent sweepers."""
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

root = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(root / 'apps/api/src'), str(root / 'apps/agent/src')]
if len(sys.argv) > 1 and sys.argv[1] == 'sweep':
    from casepilot_agent.tasks import recover_unclaimed_deliveries
    print(json.dumps(recover_unclaimed_deliveries()))
    raise SystemExit(0)

from dotenv import dotenv_values
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

url = make_url(dotenv_values(root / '.env')['DATABASE_URL']).set(host='127.0.0.1')
name = 'casepilot_delivery_' + uuid4().hex[:10]
admin = create_engine(url.set(database='postgres'), isolation_level='AUTOCOMMIT')
with admin.connect() as connection:
    connection.execute(text(f'CREATE DATABASE {name}'))
os.environ.update(DATABASE_URL=url.set(database=name).render_as_string(hide_password=False),
                  REDIS_URL='redis://127.0.0.1:6392/0', CASEPILOT_AGENT_PROVIDER='mock')
try:
    subprocess.run([str(root/'.venv/bin/alembic'), '-c', 'apps/api/alembic.ini', 'upgrade', 'head'],
                   cwd=root, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    from casepilot_api.models import Space, GenerationJob, KnowledgeSource, TaskOutbox
    from casepilot_agent import tasks
    engine = create_engine(os.environ['DATABASE_URL'])
    expected = set()
    with Session(engine) as db:
        space = Space(name='Unclaimed publication acceptance');db.add(space);db.flush()
        for status in ['queued','running','completed','failed','cancelled','awaiting_input']:
            for old in [False,True]:
                job = GenerationJob(space_id=space.id, operation='knowledge_qa',status=status,input_payload={},output_payload={})
                db.add(job);db.flush()
                row = TaskOutbox(task_name='casepilot.agent.answer_question',task_args=[str(job.id)],task_id=str(job.id),status='dispatched',dispatched_at=datetime.now(UTC)-timedelta(seconds=120 if old else 0))
                db.add(row);db.flush()
                if status=='queued' and old:expected.add(row.id)
        for status in ['uploaded','parsing','ready','failed','deleted']:
            source = KnowledgeSource(space_id=space.id,name=status,status=status,deleted_at=datetime.now(UTC) if status=='deleted' else None)
            db.add(source);db.flush()
            row = TaskOutbox(task_name='casepilot.agent.index_knowledge_source',task_args=[str(source.id)],task_id='knowledge-index:'+str(source.id),status='dispatched',dispatched_at=datetime.now(UTC)-timedelta(seconds=120))
            db.add(row);db.flush()
            if status=='uploaded':expected.add(row.id)
        for args in [[],['not-a-uuid'],[str(uuid4())]]:
            db.add(TaskOutbox(task_name='casepilot.agent.generate',task_args=args,task_id=str(uuid4()),status='dispatched',dispatched_at=datetime.now(UTC)-timedelta(seconds=120)))
        db.commit()
    children=[subprocess.Popen([sys.executable,__file__,'sweep'],stdout=subprocess.PIPE,text=True) for _ in range(3)]
    results=[]
    for child in children:
        stdout,_=child.communicate(timeout=30);assert child.returncode==0;results.append(json.loads(stdout))
    assert sum(r['requeued'] for r in results)==len(expected)==2, results
    with Session(engine) as db:
        actual={r.id for r in db.scalars(select(TaskOutbox).where(TaskOutbox.status=='pending'))}
        assert actual==expected
    assert tasks.recover_unclaimed_deliveries()=={'requeued':0}
    published=[]
    tasks.celery_app.send_task=lambda name,**kwargs:published.append((name,kwargs))
    assert tasks.dispatch_task_outbox()['dispatched']==2
    assert len(published)==2
    assert tasks.recover_unclaimed_deliveries()=={'requeued':0}
    evidence={'status':'passed','concurrent_sweepers':results,'requeued':2,'published':len(published),'verified':['Only stale queued jobs and uploaded nondeleted sources requeued','Running, terminal, awaiting-input and recent publication untouched','Malformed/missing IDs do not crash recovery','Three concurrent sweepers transition each entry only once','Normal outbox publisher sends recovered entries']}
    (root/'output/maturity-acceptance-20261023/unclaimed-delivery.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print(json.dumps(evidence))
finally:
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE {name} WITH (FORCE)'))
