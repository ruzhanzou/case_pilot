"""Retry the preserved failed synthetic acceptance job through its public API."""
import json,time
from pathlib import Path
import httpx
from dotenv import dotenv_values
from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url
root=Path(__file__).resolve().parents[2];v=dotenv_values(root/'.env')
e=create_engine(make_url(v['DATABASE_URL']).set(host='127.0.0.1',database='casepilot_strategy_acceptance_20261021'))
job='833cf75c-4078-4547-a6c7-5110808754b6'
with e.connect() as c:
 email,cid=c.execute(text("select a.email,j.input_payload->>'conversation_id' from generation_jobs j join accounts a on a.id=j.account_id where j.id=:job"),{'job':job}).one()
assert email.startswith('transition-') and email.endswith('@casepilot.test')
with httpx.Client(base_url='http://127.0.0.1:8018/api/v1',timeout=180) as c:
 r=c.post('/auth/login',json={'email':email,'password':'CasePilot123!'});r.raise_for_status()
 before=c.get(f'/conversations/{cid}').json();prior=before['candidates']
 r=c.post(f'/generation-jobs/{job}/retry');r.raise_for_status();retry=r.json();active=retry['id']
 start=time.monotonic()
 while time.monotonic()-start<360:
  state=c.get(f'/generation-jobs/{active}').json()
  if state['status'] in ['completed','failed','cancelled']:break
  time.sleep(1)
 after=c.get(f'/conversations/{cid}').json()
 record={'original_job':job,'retry_job':active,'status':state['status'],'seconds':time.monotonic()-start,'before':prior,'after':after['candidates'],'job':state}
 (root/'output/journey-acceptance-20261021/failed-job-retry.json').write_text(json.dumps(record,ensure_ascii=False,indent=2))
 assert state['status']=='completed',state.get('error_code')
 assert len(after['candidates'])==len(prior)==2
 target={point['id'] for point in state['test_points']}
 assert target
 for old in prior:
  if not target.intersection(old['snapshot']['test_point_ids']):assert old in after['candidates']
 print('Retry completed; candidate count and unrelated work retained')
