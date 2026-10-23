"""Remove exactly one synthetic job message after publication, with watchdog unpause."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import UUID

root = Path(__file__).resolve().parents[2]
container = 'casepilot-maturity-ocr-20261023'
if sys.argv[1] == 'unpause_after':
    time.sleep(45)
    subprocess.run(['docker','unpause',container],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    raise SystemExit(0)
if sys.argv[1] == 'prepare':
    subprocess.run(['docker','pause',container],check=True,stdout=subprocess.DEVNULL)
    subprocess.Popen([sys.executable,__file__,'unpause_after'],stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    print('Isolated acceptance worker paused')
    raise SystemExit(0)

try:
    from dotenv import dotenv_values
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from celery import Celery
    from redis import Redis
    job_id = str(UUID(sys.argv[2]));email = sys.argv[3]
    if not email.startswith('broker-') or not email.endswith('@casepilot.test'):
        raise SystemExit('Synthetic broker account required')
    url=make_url(dotenv_values(root/'.env')['DATABASE_URL']).set(host='127.0.0.1',database='casepilot_maturity_acceptance_20261023')
    with create_engine(url).begin() as connection:
        row=connection.execute(text('''SELECT o.id,o.task_name,o.task_args,o.task_id
          FROM task_outbox o JOIN generation_jobs j ON j.id::text=o.task_id
          JOIN space_memberships m ON m.space_id=j.space_id JOIN accounts a ON a.id=m.account_id
          WHERE j.id=:job AND a.email=:email AND j.status='queued' AND o.status='pending'
          FOR UPDATE OF o'''),{'job':job_id,'email':email}).mappings().one()
        app=Celery('acceptance-drop',broker='redis://127.0.0.1:6392/1')
        app.send_task(row['task_name'],args=row['task_args'],task_id=row['task_id'],retry=False)
        connection.execute(text("UPDATE task_outbox SET status='dispatched',dispatched_at=now() WHERE id=:id"),{'id':row['id']})
    redis=Redis(host='127.0.0.1',port=6392,db=1,socket_timeout=3)
    removed=0
    for raw in redis.lrange('celery',0,-1):
        if json.loads(raw).get('headers',{}).get('id')==job_id:
            removed+=redis.lrem('celery',1,raw)
    assert removed==1, f'Expected one specific queued delivery, removed {removed}'
    print(json.dumps({'job_id':job_id,'removed_deliveries':removed}))
finally:
    subprocess.run(['docker','unpause',container],check=True,stdout=subprocess.DEVNULL)
