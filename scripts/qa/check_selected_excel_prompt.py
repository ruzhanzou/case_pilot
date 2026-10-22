"""Inspect real persisted rewrite requests, never infer scope from UI labels."""
import json
from pathlib import Path
from dotenv import dotenv_values
from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url
root=Path('output/qa-natural-language-20261022')
evidence=json.loads(next((root/'browser').glob('complex-excel*/evidence.json')).read_text())
url=make_url(dotenv_values('.env')['DATABASE_URL']).set(host='127.0.0.1',database='casepilot_strategy_acceptance_20261021')
with create_engine(url).connect() as c:
 rows=c.execute(text("""select s.stage,s.input_payload from generation_job_stages s join generation_jobs j on j.id=s.generation_job_id
 where j.input_payload->>'conversation_id'=:cid and s.stage like 'rewrite.%' order by s.created_at"""),{'cid':evidence['conversationId']}).mappings().all()
checks=[]
for row in rows:
 value=json.dumps(row['input_payload'],ensure_ascii=False)
 checks.append({'stage':row['stage'],'selected_present':'OLD-001' in value,'unselected_absent':all(token not in value for token in ['OLD-002','OTHER-001','BAD-001','PAY-EXPIRED']),'chars':len(value)})
result={'conversation':evidence['conversationId'],'checks':checks,'passed':bool(checks) and all(x['selected_present'] and x['unselected_absent'] for x in checks)}
(root/'real-prompt-scope.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False))
assert result['passed']
