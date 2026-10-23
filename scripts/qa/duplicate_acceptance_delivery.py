"""Publish duplicates or inspect output counts for an owned synthetic acceptance job."""
import json
import sys
from pathlib import Path
from uuid import UUID
from celery import Celery
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

root=Path(__file__).resolve().parents[2]
mode,job_id,email=sys.argv[1],str(UUID(sys.argv[2])),sys.argv[3]
if not email.startswith('broker-') or not email.endswith('@casepilot.test'):
    raise SystemExit('Synthetic broker account required')
url=make_url(dotenv_values(root/'.env')['DATABASE_URL']).set(host='127.0.0.1',database='casepilot_maturity_acceptance_20261023')
with create_engine(url).connect() as connection:
    row=connection.execute(text('''SELECT j.status,o.task_name,o.task_args,o.task_id
        FROM task_outbox o JOIN generation_jobs j ON j.id::text=o.task_id
        JOIN space_memberships m ON m.space_id=j.space_id JOIN accounts a ON a.id=m.account_id
        WHERE j.id=:job AND a.email=:email'''),{'job':job_id,'email':email}).mappings().one()
    if mode=='duplicate':
        assert row['status']=='running', 'Duplicate delivery must overlap a live execution'
        app=Celery('acceptance-duplicates',broker='redis://127.0.0.1:6392/1')
        for _ in range(3):
            app.send_task(row['task_name'],args=row['task_args'],task_id=row['task_id'],retry=False)
        print(json.dumps({'job_id':job_id,'status_at_injection':row['status'],'duplicate_deliveries':3}))
    elif mode=='inspect':
        counts={table:connection.scalar(text(f'SELECT count(*) FROM {table} WHERE generation_job_id=:job'),{'job':job_id}) for table in ('case_change_sets','candidate_revisions')}
        assert counts=={'case_change_sets':1,'candidate_revisions':1},counts
        print(json.dumps(counts))
    else:
        raise SystemExit('mode: duplicate | inspect')
