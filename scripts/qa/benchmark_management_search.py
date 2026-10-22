"""Measure bounded management search on the isolated 500k fixture."""
import json, os, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID
from dotenv import dotenv_values
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
values = dotenv_values('.env')
os.environ['DATABASE_URL'] = make_url(values['DATABASE_URL']).set(host='127.0.0.1', database='casepilot_strategy_acceptance_20261021').render_as_string(hide_password=False)
from casepilot_api.case_management import search_space_test_cases
from casepilot_api.models import Account, SpaceMembership
engine = create_engine(os.environ['DATABASE_URL'], pool_size=5)
space = UUID(json.loads(Path('output/deep-quality-20261022/scale-fixture.json').read_text())['space'])
results=[]
for query in ['', '账号 登录', '唯一质量锚点05000', '北辰认证验收组05000', '集合规模验收']:
 def run(index):
  start=time.perf_counter()
  try:
   with Session(engine) as db:
    db.execute(text("SET LOCAL statement_timeout='8s'"))
    account=db.scalar(select(Account).join(SpaceMembership, SpaceMembership.account_id==Account.id).where(SpaceMembership.space_id==space))
    items=search_space_test_cases(space,account,db,q=query,limit=100,offset=0)
    return {'ms':(time.perf_counter()-start)*1000,'count':len(items),'ids':[str(x.id) for x in items]}
  except Exception as error:return {'ms':(time.perf_counter()-start)*1000,'error':str(error)[:300]}
 n=int(os.environ.get('QA_SAMPLES','30'))
 with ThreadPoolExecutor(max_workers=min(5,n)) as pool:samples=list(pool.map(run,range(n)))
 row={'query':query,'samples':samples,'p95_ms':sorted(x['ms'] for x in samples)[min(n-1,int(n*.95))]}
 results.append(row)
 Path('output/qa-continuation-20261022/management-search.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
 print(query, row['p95_ms'],[{k:v for k,v in x.items() if k!='ids'} for x in samples[:2]],flush=True)
