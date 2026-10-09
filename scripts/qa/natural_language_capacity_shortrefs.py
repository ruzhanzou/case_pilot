import httpx,json,time,traceback
from pathlib import Path
root=Path(__file__).resolve().parents[2];out=root/'output/nl-e2e-fix-20261009/api-capacity-shortrefs';out.mkdir(exist_ok=True)
c=httpx.Client(base_url='http://localhost:8001/api/v1',timeout=240,trust_env=False)
def post(path,data):
 r=c.post(path,json=data);
 if not r.is_success: raise RuntimeError(f'{r.status_code}: {r.text}')
 return r.json()
def get(path):
 r=c.get(path);r.raise_for_status();return r.json()
account=post('/auth/register',{'email':f'nl-capacity-{time.time_ns()}@casepilot.test','display_name':'容量专项验收','password':'CasePilot123!'})
for size in [1000]:
 journal={'case':'NL-PER-03','size':size,'status':'running','started':time.time(),'timings':{},'snapshots':[]}
 path=out/f'{size}.json'
 def save():path.write_text(json.dumps(journal,ensure_ascii=False,indent=2))
 try:
  coll=post(f"/spaces/{account['spaces'][0]['id']}/collections",{'name':f'批量改写容量-{size}'})
  journal['collection']=coll;save()
  cases=[{'case_key':f'LOAD-{size}-{i}','title':f'账号{i}登录验证','module':f'M{i//20+1:02}','priority':'P1','case_type':'功能','preconditions':['账号已启用'],'steps':[{'action':'提交正确密码','expected':'建立登录会话'}]} for i in range(size)]
  originals=[]
  for offset in range(0,size,100):originals+=post(f"/collections/{coll['id']}/test-cases/batch",{'cases':cases[offset:offset+100]})
  journal['original']=originals
  conv=post('/conversations',{'collection_id':coll['id'],'space_id':account['spaces'][0]['id'],'title':f'{size}条容量验收'})
  journal['conversation']=conv['id'];save()
  start=time.monotonic()
  turn=post(f"/conversations/{conv['id']}/messages",{'content':f'只给当前集合全部{size}条用例最后一步预期追加“审计日志可查”，保留原文及其他字段。','scope':'current','model_id':'ark-code-latest'})
  journal['turn']=turn;journal['timings']['message_response']=time.monotonic()-start;save()
  if turn.get('assistant_message',{}).get('metadata',{}).get('modification_confirmation'):
   operation=turn['assistant_message']['metadata']['operation_id'];start=time.monotonic()
   turn=post(f'/conversation-operations/{operation}/resume',{'confirm_modification':True})
   journal['confirmation']=turn;journal['timings']['confirmation_response']=time.monotonic()-start;save()
  change_id=turn.get('action',{}).get('change_set_id')
  if not change_id:
   journal['status']='NOT_COMPLETED';journal['reason']='No reviewable rewrite started; inspect recorded clarification/rejection.';save();continue
  start=time.monotonic();last=None
  while time.monotonic()-start<5400:
   change=get(f'/case-change-sets/{change_id}')
   marker=(change['status'],len(change['items']))
   if marker!=last:
    journal['snapshots'].append({'elapsed':time.monotonic()-start,'status':marker[0],'items':marker[1]});last=marker;save()
   if change['status']!='generating':break
   time.sleep(5)
  journal['timings']['ready_after_confirmation']=time.monotonic()-start;journal['change']=change;save()
  assert change['status']=='ready',change['status']
  assert len(change['items'])==size
  assert get(f"/collections/{coll['id']}/test-cases")==originals
  start=time.monotonic();journal['applied']=post(f'/case-change-sets/{change_id}/apply',{})
  journal['timings']['apply']=time.monotonic()-start
  after=get(f"/collections/{coll['id']}/test-cases");journal['final']=after
  before={x['id']:x for x in originals}
  assert len(after)==size
  for item in after:
   old=before[item['id']];assert item['revision_number']==old['revision_number']+1
   assert item['steps'][-1]['expected'].startswith(old['steps'][-1]['expected'])
   assert '审计日志可查' in item['steps'][-1]['expected']
   for k,v in old.items():
    if k not in ('steps','revision_number','current_revision_id'):assert item[k]==v,(item['id'],k)
  journal['status']='PASS'
 except Exception as e:
  journal['status']='FAIL';journal['error']=str(e);journal['traceback']=traceback.format_exc()
 finally:
  journal['elapsed']=time.time()-journal['started'];save();print(size,journal['status'],flush=True)
