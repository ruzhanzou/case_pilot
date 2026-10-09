import httpx,json,time,traceback,subprocess
from pathlib import Path
out=Path(__file__).resolve().parents[2]/'output/nl-e2e-fix-20261009/faults-v3';out.mkdir(exist_ok=True)
c=httpx.Client(base_url='http://localhost:8011/api/v1',timeout=240,trust_env=False)
def post(path,data={}):
 r=c.post(path,json=data);assert r.is_success,(r.status_code,r.text);return r.json()
def get(path):
 r=c.get(path);r.raise_for_status();return r.json()
def control(mode,remaining=1):httpx.post('http://localhost:8102/control',json={'mode':mode,'remaining':remaining},trust_env=False).raise_for_status()
account=post('/auth/register',{'email':f'fault-{time.time_ns()}@casepilot.test','display_name':'故障隔离验收','password':'CasePilot123!'})
for code,mode in [('NL-REC-03','429'),('NL-REC-04','invalid'),('NL-REC-06','delay')]:
 j={'id':code,'status':'running','started':time.time(),'turns':[]};path=out/f'{code}.json'
 def save():path.write_text(json.dumps(j,ensure_ascii=False,indent=2))
 try:
  coll=post(f"/spaces/{account['spaces'][0]['id']}/collections",{'name':code});j['collection']=coll
  originals=post(f"/collections/{coll['id']}/test-cases/batch",{'cases':[{'case_key':f'{code}-{i}','title':f'登录{i}','module':'登录','priority':'P1','case_type':'功能','preconditions':['账号已注册'],'steps':[{'action':'提交正确密码','expected':'建立会话'}]} for i in range(3)]})
  j['original']=originals
  conv=post('/conversations',{'collection_id':coll['id'],'space_id':account['spaces'][0]['id']});j['conversation']=conv['id'];save()
  turn=post(f"/conversations/{conv['id']}/messages",{'content':f"给用例 {originals[0]['case_key']} 补充断网点击重试及恢复网络后登录成功的验证，其他用例不变。",'model_id':'ark-code-latest'})
  j['turns'].append(turn);save();assert turn['assistant_message']['metadata'].get('modification_confirmation'),turn['action']
  control(mode,10 if mode=='invalid' else 1)
  operation=turn['assistant_message']['metadata']['operation_id']
  turn=post(f'/conversation-operations/{operation}/resume',{'confirm_modification':True});j['turns'].append(turn);save()
  change_id=turn['action']['change_set_id']
  if mode=='delay':
   # Wait until the proxy has actually held the model response before cancelling.
   start=time.time()
   proxy=out.parent/'fault-proxy.json'
   while time.time()-start<120:
    if any(e['fault']=='delay' and e['time']>j['started'] for e in httpx.get('http://localhost:8102/state',trust_env=False).json()['calls']):break
    time.sleep(1)
   else:raise AssertionError('delay not entered')
   j['cancel']=post(f"/generation-jobs/{turn['action']['job_id']}/cancel")
   time.sleep(50)
   j['late_change']=get(f'/case-change-sets/{change_id}')
   assert j['late_change']['status'] not in ('ready','applied','generating')
  else:
   start=time.time()
   while time.time()-start<360:
    change=get(f'/case-change-sets/{change_id}')
    if change['status']!='generating':break
    time.sleep(2)
   j['first_result']=change;save();assert get(f"/collections/{coll['id']}/test-cases")==originals
   if mode=='invalid':assert change['status'] in ('failed','ready')
   control('normal',0)
   if change['status']=='failed':
    state=get(f"/conversations/{conv['id']}");j['failed_state']=state
    failed=[m for m in state['messages'] if m['status']=='failed' and m['role']=='assistant'][-1]
    turn=post(f"/conversation-messages/{failed['id']}/retry");j['retry']=turn;save()
    if turn.get('assistant_message',{}).get('metadata',{}).get('modification_confirmation'):
     turn=post(f"/conversation-operations/{turn['assistant_message']['metadata']['operation_id']}/resume",{'confirm_modification':True});j['retry_confirmation']=turn;save()
    change_id=turn['action']['change_set_id']
    start=time.time()
    while time.time()-start<360:
     change=get(f'/case-change-sets/{change_id}')
     if change['status']!='generating':break
     time.sleep(2)
   assert change['status']=='ready',change['status']
   assert len(change['items'])==1 and change['items'][0]['ref']==originals[0]['id']
   j['recovered']=change
  j['final']=get(f"/collections/{coll['id']}/test-cases");assert j['final']==originals;j['status']='PASS'
 except Exception as e:j.update(status='FAIL',error=str(e),traceback=traceback.format_exc())
 finally:control('normal',0);j['elapsed']=time.time()-j['started'];save();print(code,j['status'],flush=True)
