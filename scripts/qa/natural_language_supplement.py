"""Real API acceptance, isolated users, evidence for every mutation boundary."""
import json,time,traceback,httpx
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'output/nl-e2e-fix-20261009/supplement';OUT.mkdir(exist_ok=True)
SUITE=json.loads((ROOT/'docs/evaluations/casepilot-natural-language-eval-2026-10-09.json').read_text())
class Run:
 def __init__(self,code):
  self.j={'id':code,'started':time.time(),'events':[]};self.path=OUT/f'{code}.json';self.c=httpx.Client(base_url='http://localhost:8000/api/v1',timeout=240,trust_env=False)
  self.a=self.post('/auth/register',{'email':f'{code}-{time.time_ns()}@casepilot.test','display_name':'补充验收','password':'CasePilot123!'})
  self.coll=self.post(f"/spaces/{self.a['spaces'][0]['id']}/collections",{'name':code})
  self.original=[]
  for f in SUITE['fixture_definitions']['F']['cases']:
   f=dict(f);f.pop('alias',None);self.original.append(self.post(f"/collections/{self.coll['id']}/test-cases",f))
  self.conv=self.post('/conversations',{'collection_id':self.coll['id'],'space_id':self.a['spaces'][0]['id']})
  self.j.update(collection=self.coll,original=self.original,conversation=self.conv['id']);self.save()
 def save(self):self.path.write_text(json.dumps(self.j,ensure_ascii=False,indent=2))
 def post(self,path,data={}):
  started=time.monotonic();r=self.c.post(path,json=data);r.raise_for_status();d=r.json();self.j['events'].append({'path':path,'input':data,'response':d,'seconds':time.monotonic()-started});self.save();return d
 def get(self,path):r=self.c.get(path);r.raise_for_status();return r.json()
 def read(self):return self.get(f"/collections/{self.coll['id']}/test-cases")
 def turn(self,text,**kw):return self.post(f"/conversations/{self.conv['id']}/messages",{'content':text,'model_id':'ark-code-latest',**kw})
 def ready(self,turn):
  if turn.get('assistant_message',{}).get('metadata',{}).get('modification_confirmation'):
   turn=self.post(f"/conversation-operations/{turn['assistant_message']['metadata']['operation_id']}/resume",{'confirm_modification':True})
  cid=turn['action'].get('change_set_id');assert cid,turn['action'];start=time.time()
  while time.time()-start<360:
   change=self.get(f'/case-change-sets/{cid}')
   if change['status']!='generating':break
   time.sleep(2)
  assert change['status']=='ready',change['status'];self.j.setdefault('proposals',[]).append(change);self.save();return change
 def apply(self,change,data={}):return self.post(f"/case-change-sets/{change['id']}/apply",data)
 def unchanged(self):assert self.read()==self.original
 def one(self,key):return next(c for c in self.original if c['case_key']==key)
def run(code,fn):
 r=None
 try:r=Run(code);fn(r);r.j['status']='PASS'
 except Exception as e:
  if r:r.j.update(status='FAIL',error=str(e),traceback=traceback.format_exc())
  else: (OUT/f'{code}.json').write_text(json.dumps({'id':code,'status':'FAIL','error':str(e)}))
 finally:
  if r:r.j['final']=r.read();r.j['elapsed']=time.time()-r.j['started'];r.save();print(code,r.j['status'],flush=True)
def selected(r):
 old=r.one('TC-PAY-01');s=r.one('TC-LOGIN-01')
 change=r.ready(r.turn('把 TC-PAY-01 的优先级改为P0，其他不变。',target_case_ids=[s['id']]))
 assert [x['ref'] for x in change['items']]==[old['id']];r.unchanged();r.apply(change)
 assert next(x for x in r.read() if x['id']==s['id'])==s
run('NL-SCP-01',selected)
def ambiguous(r):
 r.post(f"/collections/{r.coll['id']}/test-cases",{'case_key':'OTHER-SMS','title':'营销短信','module':'营销/短信','priority':'P1','steps':[{'action':'发送','expected':'成功'}]});r.original=r.read()
 turn=r.turn('把短信模块全部改为P0。');assert not turn['action'].get('job_id');assert turn['action']['type']=='clarification';r.unchanged()
run('NL-SCP-05',ambiguous)
def remaining(r,reject=False):
 change=r.ready(r.turn('把登录模块全部优先级改P0。'));a=r.one('TC-LOGIN-01');b=r.one('TC-LOGIN-02')
 if reject:r.apply(change,{'accepted_fields':{a['id']:[]},'review_refs':[a['id']]})
 else:r.apply(change,{'accepted_fields':{a['id']:['priority']},'review_refs':[a['id']]})
 before=r.read();follow='把剩余待审阅用例标题加上“复测”。' if reject else '剩下未采纳的建议改成P2。'
 change=r.ready(r.turn(follow,source_operation_id=change.get('operation_id')))
 pending=[i for i in change['items'] if i.get('status') not in ('applied','rejected')];assert [i['ref'] for i in pending]==[b['id']]
 assert r.read()==before;r.apply(change)
 final=r.read();assert next(x for x in final if x['id']==a['id'])==next(x for x in before if x['id']==a['id'])
run('NL-MUL-04',lambda r:remaining(r))
run('NL-MUL-05',lambda r:remaining(r,True))
def stale(r):
 change=r.ready(r.turn('把登录模块全部优先级改P0。'));a=r.one('TC-LOGIN-01');b=r.one('TC-LOGIN-02')
 q=r.c.patch('/test-cases/'+b['id'],json={**b,'base_revision_id':b['current_revision_id'],'title':'人工更改保留'});q.raise_for_status();manual=q.json()
 r.apply(change,{'accepted_fields':{a['id']:['priority']},'review_refs':[a['id']]})
 assert next(x for x in r.read() if x['id']==b['id'])==manual
run('NL-REV-03',stale)
def deletion(r):
 turn=r.turn('删除 TC-PAY-01，其他不要动。');r.unchanged();r.j['delete_preview']=turn
 op=turn['operation_plan']['operations'][0]
 r.post(f"/conversation-operations/{op['id']}/cancel");r.unchanged()
run('NL-REV-08',deletion)
def compound(r):
 turn=r.turn('把登录模块优先级改P0，再删除支付模块中的 TC-PAY-01，保留退款用例。');r.unchanged();r.j['compound']=turn
 ops=turn['operation_plan']['operations'];assert len(ops)>=2
 assert {x['intent'] for x in ops}>={'CASE_MODIFY','CASE_DELETE'}
 # Complete modification; deliberately cancel the deletion preview to verify separate confirmation.
 change=r.ready(turn);r.apply(change)
 state=r.get('/conversations/'+r.conv['id']);r.j['after_modify']=state
 deletes=[x for x in state['operation_history'] if x['intent']=='CASE_DELETE'];assert deletes
 op=deletes[-1];r.post(f"/conversation-operations/{op['id']}/cancel")
 assert next(x for x in r.read() if x['id']==r.one('TC-PAY-01')['id'])==r.one('TC-PAY-01')
 assert next(x for x in r.read() if x['id']==r.one('TC-REFUND-01')['id'])==r.one('TC-REFUND-01')
run('NL-MUL-11',compound)
