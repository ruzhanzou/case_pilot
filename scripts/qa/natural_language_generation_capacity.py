"""Real generation at batch boundaries; no generated outputs are mocked."""
import httpx,json,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'output/nl-e2e-fix-20261009/generation-capacity';OUT.mkdir(exist_ok=True)
fixture=json.loads((ROOT/'apps/web/e2e/fixtures/batch-planning.json').read_text())
c=httpx.Client(base_url='http://localhost:8011/api/v1',timeout=240,trust_env=False)
def post(path,data={}):r=c.post(path,json=data);r.raise_for_status();return r.json()
def get(path):r=c.get(path);r.raise_for_status();return r.json()
a=post('/auth/register',{'email':f'gen-boundaries-{time.time_ns()}@casepilot.test','display_name':'生成批次边界验收','password':'CasePilot123!'})
for size in [20,21,100]:
 j={'id':'NL-PER-02','size':size,'status':'running','started':time.time(),'states':[]};p=OUT/f'{size}.json'
 def save():p.write_text(json.dumps(j,ensure_ascii=False,indent=2))
 try:
  coll=post(f"/spaces/{a['spaces'][0]['id']}/collections",{'name':f'生成批次-{size}'});j['collection']=coll
  conv=post('/conversations',{'collection_id':coll['id'],'space_id':a['spaces'][0]['id']});j['conversation']=conv['id']
  feature={**fixture['planning']['feature_points'][0],'id':'FP-BOUNDARY','name':'账号登录','module':'账号登录'}
  points=[{**fixture['planning']['test_points'][0],'id':f'TP-{i+1}','title':f'B{i+1:03} 账号qa_{i+1}正确密码登录','scenario':f'账号qa_{i+1}已启用，正确密码登录成功并建立会话','feature_point_ids':[feature['id']]} for i in range(size)]
  brief=post(f"/workspaces/{conv['id']}/test-briefs",{'content':{'test_object':'账号登录','test_objective':f'每个测试点生成1条，共{size}条，标题保留B编号，不合并；每条最多2步。','planning':{'feature_points':[feature],'test_points':points}}});j['brief']=brief;save()
  start=time.monotonic();turn=post(f"/workspaces/{conv['id']}/test-briefs/confirm",{'version':brief['version'],'model_id':'ark-code-latest'});j['turn']=turn;last=None;preview_refs=set();save()
  while time.monotonic()-start<1800:
   state=get('/conversations/'+conv['id']);history=state['candidate_history'];run=next((x for x in state['workflow_runs'] if x['job_id']==turn['action']['job_id']),{})
   marker=(run.get('status'),len(history),len(state['candidates']))
   if marker!=last:
    j['states'].append({'elapsed':time.monotonic()-start,'status':marker[0],'history':marker[1],'ready':marker[2],'refs':[x['ref'] for x in history]});last=marker;save()
   if history and not preview_refs:preview_refs={x['ref'] for x in history};j['first_batch']=time.monotonic()-start
   if run.get('status') in ('completed','failed','cancelled'):break
   time.sleep(2)
  j['total_ready']=time.monotonic()-start;j['final_state']=state;save()
  assert run['status']=='completed',run
  assert len(state['candidates'])==size
  assert preview_refs<={x['ref'] for x in state['candidates']}
  for i in range(size):assert sum(f'B{i+1:03}' in x['snapshot']['title'] for x in state['candidates'])==1
  assert get(f"/collections/{coll['id']}/test-cases")==[]
  j['status']='PASS'
 except Exception as e:j.update(status='FAIL',error=str(e),traceback=traceback.format_exc())
 finally:j['elapsed']=time.time()-j['started'];save();print(size,j['status'],flush=True)
