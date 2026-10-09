"""Five isolated users, one 100-case task each; descriptive timing only."""
import concurrent.futures,json,time,threading,traceback,httpx
from pathlib import Path
OUT=Path(__file__).resolve().parents[2]/'output/nl-e2e-fix-20261009/concurrency';OUT.mkdir(exist_ok=True)
barrier=threading.Barrier(5,timeout=120)
def run(index):
 j={'id':'NL-PER-06','user':index,'samples_per_user':1,'started':time.time(),'status':'running','timings':{},'states':[]};p=OUT/f'user-{index}.json'
 def save():p.write_text(json.dumps(j,ensure_ascii=False,indent=2))
 c=httpx.Client(base_url='http://localhost:8000/api/v1',timeout=240,trust_env=False)
 def post(path,data={}):r=c.post(path,json=data);r.raise_for_status();return r.json()
 def get(path):r=c.get(path);r.raise_for_status();return r.json()
 try:
  a=post('/auth/register',{'email':f'concurrent-{index}-{time.time_ns()}@casepilot.test','display_name':f'并发用户{index}','password':'CasePilot123!'})
  coll=post(f"/spaces/{a['spaces'][0]['id']}/collections",{'name':f'并发100条-{index}'});j['collection']=coll
  before=post(f"/collections/{coll['id']}/test-cases/batch",{'cases':[{'case_key':f'U{index}-{n}','title':f'用户{index}场景{n}','module':'登录','priority':'P1','steps':[{'action':f'用户{index}提交凭证','expected':f'用户{index}建立会话'}]} for n in range(100)]});j['original']=before
  conv=post('/conversations',{'space_id':a['spaces'][0]['id'],'collection_id':coll['id']});j['conversation']=conv['id'];save();barrier.wait()
  start=time.monotonic();turn=post(f"/conversations/{conv['id']}/messages",{'content':f'只给当前集合全部100条用例最后一步预期追加“用户{index}审计可查”，保留原文和其他字段。','model_id':'ark-code-latest'});j['timings']['message']=time.monotonic()-start;j['turn']=turn;save()
  assert turn['assistant_message']['metadata'].get('modification_confirmation'),turn['action']
  turn=post(f"/conversation-operations/{turn['assistant_message']['metadata']['operation_id']}/resume",{'confirm_modification':True});j['confirmation']=turn;cid=turn['action']['change_set_id'];last=None;save()
  while time.monotonic()-start<1800:
   change=get('/case-change-sets/'+cid);marker=(change['status'],len(change['items']))
   if marker!=last:j['states'].append({'seconds':time.monotonic()-start,'status':marker[0],'items':marker[1]});last=marker;save()
   if change['status']!='generating':break
   time.sleep(3)
  j['timings']['total_ready']=time.monotonic()-start;j['change']=change
  assert change['status']=='ready',change['status'];assert len(change['items'])==100
  assert {x['ref'] for x in change['items']}=={x['id'] for x in before}
  assert get(f"/collections/{coll['id']}/test-cases")==before
  t=time.monotonic();j['apply']=post('/case-change-sets/'+cid+'/apply');j['timings']['apply']=time.monotonic()-t
  after=get(f"/collections/{coll['id']}/test-cases");j['final']=after;old={x['id']:x for x in before}
  for item in after:
   assert item['revision_number']==old[item['id']]['revision_number']+1
   assert f'用户{index}审计可查' in item['steps'][-1]['expected']
   for key in ('title','priority','preconditions','module'):assert item[key]==old[item['id']][key]
  j['status']='PASS'
 except Exception as e:j.update(status='FAIL',error=str(e),traceback=traceback.format_exc())
 finally:j['elapsed']=time.time()-j['started'];save();print(index,j['status'],flush=True)
 return j
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:rows=list(pool.map(run,range(5)))
values=sorted(x['timings']['total_ready'] for x in rows if 'total_ready' in x['timings'])
def quantile(q):
 if not values:return None
 k=(len(values)-1)*q;i=int(k);return values[i]+(values[min(i+1,len(values)-1)]-values[i])*(k-i)
summary={'id':'NL-PER-06','status':'PASS' if all(x['status']=='PASS' for x in rows) else 'FAIL','samples':len(values),'p50':quantile(.5),'p95':quantile(.95),'limitation':'One task per user. Per-user p50/p95 equal the single observation; five pooled samples are descriptive, not a stable SLA estimate.','users':[{'user':x['user'],'status':x['status'],'timings':x['timings']} for x in rows]}
(OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
