"""Real API acceptance, isolated users, evidence for every mutation boundary."""
import json,time,traceback,httpx
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'output/nl-e2e-fix-20261009/compound-final';OUT.mkdir(exist_ok=True)
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
def compound_final(r):
 turn=r.turn('把登录模块优先级改P0，再删除支付模块中的 TC-PAY-01，保留退款用例。');r.unchanged()
 ops=turn['operation_plan']['operations'];assert {x['intent'] for x in ops}>={'CASE_MODIFY','CASE_DELETE'}
 change=r.ready(turn);r.apply(change)
 state=r.get('/conversations/'+r.conv['id']);op=next(x for x in state['operation_history'] if x['intent']=='CASE_DELETE')
 if op['status']=='queued':r.post('/conversation-operations/'+op['id']+'/resume')
 state=r.get('/conversations/'+r.conv['id']);op=next(x for x in state['operation_history'] if x['intent']=='CASE_DELETE');r.j['before_delete']=state
 pending=r.get('/case-change-sets/'+op['related_change_set_id']);pay=r.one('TC-PAY-01')
 assert [x['ref'] for x in pending['items']]==[pay['id']]
 assert next(x for x in r.read() if x['id']==pay['id'])==pay
 r.apply(pending,{'accepted_fields':{pay['id']:['delete']},'review_refs':[pay['id']]})
 after=r.read();assert len(after)==3;assert pay['id'] not in {x['id'] for x in after}
 refund=r.one('TC-REFUND-01');assert next(x for x in after if x['id']==refund['id'])==refund
 for x in after:
  if x['module'].startswith('登录/'):assert x['priority']=='P0'
run('NL-MUL-11',compound_final)
