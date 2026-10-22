"""Add creation history to the existing isolated scale fixture, idempotently."""
import json
from pathlib import Path
from dotenv import dotenv_values
from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url
from uuid import UUID
url=make_url(dotenv_values('.env')['DATABASE_URL']).set(host='127.0.0.1',database='casepilot_strategy_acceptance_20261021')
space=UUID(json.loads(Path('output/deep-quality-20261022/scale-fixture.json').read_text())['space'])
with create_engine(url).begin() as db:
 actor=db.execute(text('select account_id from space_memberships where space_id=:s limit 1'),{'s':space}).scalar_one()
 result=db.execute(text("""INSERT INTO audit_events(id,space_id,actor_id,action,resource_type,resource_id,payload,created_at)
 SELECT gen_random_uuid(),t.space_id,:a,'test_case.created','test_case',t.id,'{}'::jsonb,t.created_at
 FROM test_cases t WHERE t.space_id=:s AND NOT EXISTS
 (SELECT 1 FROM audit_events e WHERE e.space_id=:s AND e.resource_type='test_case' AND e.action='test_case.created' AND e.resource_id=t.id)"""),{'s':space,'a':actor})
 print('created provenance rows',result.rowcount)
 db.execute(text('ANALYZE audit_events'))
