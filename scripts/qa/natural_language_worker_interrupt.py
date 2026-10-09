"""Run only against the isolated acceptance database and worker containers."""
import json,time,subprocess,httpx,traceback
from pathlib import Path
out=Path(__file__).resolve().parents[2]/'output/nl-e2e-fix-20261009/worker-interrupt.json'
j={'id':'NL-REC-05','status':'running','started':time.time()}
def save():out.write_text(json.dumps(j,ensure_ascii=False,indent=2))
c=httpx.Client(base_url='http://localhost:8011/api/v1',timeout=240,trust_env=False)
def post(path,data={}):
 r=c.post(path,json=data);r.raise_for_status();return r.json()
def get(path):
 r=c.get(path);r.raise_for_status();return r.json()
def proxy(data):httpx.post('http://localhost:8102/control',json=data,trust_env=False).raise_for_status()
try:
 a=post('/auth/register',{'email':f'worker-{time.time_ns()}@casepilot.test','display_name':'后台恢复验收','password':'CasePilot123!'})
 coll=post(f"/spaces/{a['spaces'][0]['id']}/collections",{'name':'后台中断25条'})
 j['collection']=coll
 originals=post(f"/collections/{coll['id']}/test-cases/batch",{'cases':[{'case_key':f'WORKER-{i}','title':f'账号{i}登录','module':'登录','priority':'P1','preconditions':[],'steps':[{'action':'提交密码','expected':'建立会话'}]} for i in range(25)]})
 j['original']=originals
 conv=post('/conversations',{'collection_id':coll['id'],'space_id':a['spaces'][0]['id']});j['conversation']=conv['id']
 turn=post(f"/conversations/{conv['id']}/messages",{'content':'给当前集合全部25条用例最后一步预期追加“审计可查”，其他保持原文。','model_id':'ark-code-latest'})
 j['turn']=turn;save()
 assert turn['assistant_message']['metadata'].get('modification_confirmation'),turn['action']
 proxy({'mode':'delay','remaining':1,'skip':1})
 turn=post(f"/conversation-operations/{turn['assistant_message']['metadata']['operation_id']}/resume",{'confirm_modification':True})
 j['confirmation']=turn;save();cid=turn['action']['change_set_id']
 started=time.time()
 while time.time()-started<360:
  change=get(f'/case-change-sets/{cid}')
  calls=httpx.get('http://localhost:8102/state',trust_env=False).json()['calls']
  if len(change['items'])>=20 and any(x['fault']=='delay' and x['time']>j['started'] for x in calls):break
  time.sleep(1)
 else:raise AssertionError('No persisted first batch and delayed second batch')
 j['before_interrupt']=change;save()
 subprocess.run(['docker','kill','casepilot-nl-fault-worker2'],check=True,capture_output=True)
 subprocess.run(['docker','start','casepilot-nl-fault-worker2'],check=True,capture_output=True)
 proxy({'mode':'normal','remaining':0});j['restarted_at']=time.time();save()
 while time.time()-j['restarted_at']<120:
  change=get(f'/case-change-sets/{cid}')
  if change['status']!='generating':break
  time.sleep(3)
 j['after_restart']=change;j['final']=get(f"/collections/{coll['id']}/test-cases")
 assert j['final']==originals
 if change['status']=='generating':
  j['status']='FAIL';j['error']='Worker restart leaves persisted preview permanently generating during 120-second observation; no recovery/error surfaced.'
  j['cleanup_cancel']=post(f"/generation-jobs/{turn['action']['job_id']}/cancel")
 else:j['status']='PASS' if change['status'] in ('ready','failed') else 'FAIL'
except Exception as e:j.update(status='FAIL',error=str(e),traceback=traceback.format_exc())
finally:
 proxy({'mode':'normal','remaining':0});j['elapsed']=time.time()-j['started'];save();print(j['status'],j.get('error',''),flush=True)
