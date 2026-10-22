"""Isolated multi-collection retrieval benchmark with known relevant assets."""
import json,os,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID,uuid4
import httpx
from dotenv import dotenv_values
from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url
from casepilot_agent.store import JobStore
root=Path('output/deep-quality-20261022');root.mkdir(exist_ok=True)
url=make_url(dotenv_values('.env')['DATABASE_URL']).set(host='127.0.0.1',database='casepilot_strategy_acceptance_20261021')
engine=create_engine(url,pool_size=5)
fixture=root/'scale-fixture.json'
if fixture.exists(): data=json.loads(fixture.read_text())
else:
 with httpx.Client(base_url='http://localhost:8018/api/v1',timeout=60) as client:
  r=client.post('/auth/register',json={'email':f'scale-{uuid4().hex}@casepilot.test','password':'CasePilot123!','display_name':'集合规模验收'});r.raise_for_status();u=r.json()
 data={'space':u['spaces'][0]['id'],'seeded':0,'collections':[]};fixture.write_text(json.dumps(data))
store=JobStore.__new__(JobStore)
results=[]
mode=os.environ.get('CASEPILOT_SCALE_MODE','before')
scales=[int(n) for n in os.environ.get('CASEPILOT_SCALE_LEVELS','10,100,1000,3000,5000').split(',')]
for count in scales:
 if data['seeded']<count:
  start=time.perf_counter()
  with engine.begin() as c:
   for index in range(data['seeded'],count):
    cid=uuid4();name=f'资产集合{index+1:05d}'
    if index+1 in [10,100,1000,3000,5000]:name=f'北辰认证验收组{index+1:05d}'
    c.execute(text('INSERT INTO case_collections(id,space_id,name,description,mind_map_notes,created_at) VALUES(:id,:space,:name,\'\',\'[]\',now())'),{'id':cid,'space':UUID(data['space']),'name':name})
    c.execute(text('CREATE TEMP TABLE IF NOT EXISTS qa_seed_rows (id uuid,rev uuid,n int) ON COMMIT DROP'))
    c.execute(text('TRUNCATE qa_seed_rows'))
    c.execute(text('INSERT INTO qa_seed_rows SELECT gen_random_uuid(),gen_random_uuid(),n FROM generate_series(1,100) n'))
    c.execute(text("INSERT INTO test_cases(id,space_id,case_key,created_at) SELECT id,:space,'QA-'||:prefix||'-'||n,now() FROM qa_seed_rows"),{'space':UUID(data['space']),'prefix':str(index+1)})
    c.execute(text("""INSERT INTO test_case_revisions(id,test_case_id,revision_number,title,description,module,priority,case_type,tags,preconditions,steps,source_refs,execution_level,test_domains,automation_type,automation_cases,created_at)
    SELECT rev,id,1,'账号登录场景'||n||CASE WHEN n=100 THEN ' 唯一质量锚点'||:prefix ELSE '' END,'','身份认证','P1','functional','[]','["已有有效账号"]','[{"action":"提交登录请求","expected":"返回会话标识"}]','[]','L0','[]','manual','[]',now() FROM qa_seed_rows"""),{'prefix':str(index+1).zfill(5)})
    c.execute(text('UPDATE test_cases t SET current_revision_id=s.rev FROM qa_seed_rows s WHERE t.id=s.id'))
    c.execute(text('INSERT INTO collection_case_memberships(id,collection_id,test_case_id,position,created_at) SELECT gen_random_uuid(),:cid,id,n,now() FROM qa_seed_rows'),{'cid':cid})
    data['collections'].append({'id':str(cid),'name':name})
  data['seeded']=count;fixture.write_text(json.dumps(data));print('seeded',count,count*100,'seconds',round(time.perf_counter()-start,2),flush=True)
  with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as c:
   for table in ['case_collections','test_cases','test_case_revisions','collection_case_memberships']:c.execute(text('ANALYZE '+table))
 # For after runs, measure the current full space; no misleading smaller-scale labels.
 with engine.connect() as c:
  counts=c.execute(text('SELECT (SELECT count(*) FROM case_collections WHERE space_id=:s) collections,(SELECT count(*) FROM test_cases WHERE space_id=:s) cases'),{'s':UUID(data['space'])}).mappings().one()
 for kind,terms in [('broad',['账号','登录']),('specific',[f'唯一质量锚点{count:05d}']),('collection',[f'北辰认证验收组{count:05d}'])]:
  def run(i):
   start=time.perf_counter()
   try:
    with engine.begin() as c:
     c.execute(text("SET LOCAL statement_timeout='8s'"))
     if os.environ.get('CASEPILOT_SCALE_SERIAL') == '1': c.execute(text("SET LOCAL max_parallel_workers_per_gather=0"))
     if os.environ.get('CASEPILOT_SCALE_WORK_MEM') in {'4MB','8MB','16MB'}:
      c.execute(text("select set_config('work_mem', :memory, true)"), {'memory':os.environ['CASEPILOT_SCALE_WORK_MEM']})
     metrics={}
     found=store.search_reuse_cases(c,space_id=UUID(data['space']),terms=terms,metrics=metrics)
     items=store.attach_reuse_collections(c,found,space_id=UUID(data['space']))
     return {'metrics':metrics,'ms':(time.perf_counter()-start)*1000,'returned_cases':len(items),'returned_collections':len({x['id'] for item in items for x in item['collections']})}
   except Exception as e:return {'ms':(time.perf_counter()-start)*1000,'error':type(e).__name__,'detail':str(getattr(e,'orig',e))[:500]}
  with ThreadPoolExecutor(max_workers=5) as pool:samples=list(pool.map(run,range(30)))
  row={'mode':mode,'collections':counts['collections'],'cases':counts['cases'],'query':kind,'terms':terms,'samples':samples,'p95_ms':sorted(x['ms'] for x in samples)[28],'expected_cases':1 if kind=='specific' else 100}
  results.append(row);(root/f'scale-{mode}.json').write_text(json.dumps(results,ensure_ascii=False,indent=2));print({k:v for k,v in row.items() if k!='samples'},'first',samples[0],flush=True)
