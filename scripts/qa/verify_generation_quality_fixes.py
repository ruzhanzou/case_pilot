"""Real mixed generation: fixed rules, boundary oracles and full prompt capture."""
import json,sys,time,re
from copy import deepcopy
from pathlib import Path
from dotenv import load_dotenv
load_dotenv('.env');sys.path.insert(0,str(Path('apps/agent/tests').resolve()))
from test_compact_generation import request
from test_reuse import source
from casepilot_agent.config import get_settings
from casepilot_agent.providers import create_provider
from casepilot_agent.pipeline import GenerationPipeline
out=Path('output/qa-fixes-20261022');provider=create_provider(get_settings().provider)
rows=[
 ('签发299秒有效','签发后299秒提交正确验证码，账号启用未锁定','TOKEN_OK',['299']),
 ('签发300秒过期','签发后恰好300秒提交正确验证码','E731',['300']),
 ('签发301秒过期','签发后301秒提交正确验证码','E731',['301']),
 ('第三次错误尚未锁定','已有2次连续错误，再提交错误验证码构成第3次','E401',['3']),
 ('第四次错误锁定','已有3次连续错误，再提交错误验证码构成第4次，账号锁定1140秒','E419',['4','1140']),
 ('锁定1139秒仍锁定','从锁定开始后1139秒提交新签发的正确验证码','E419',['1139']),
 ('锁定1140秒解除','从锁定开始恰好1140秒提交新签发的正确验证码','TOKEN_OK',['1140']),
 ('锁定优先于错误判断','锁定期间提交错误验证码仍按锁定处理','E419',[]),
 ('成功清空错误计数','先连续错误2次，再正确登录成功，再提交错误验证码，此时错误次数为1','E401',['1']),
 ('账号间计数隔离','手机号A连续错误4次已锁定；未锁定手机号B提交正确验证码','TOKEN_OK',['4']),
 ('空验证码不计错','已有2次错误，提交空验证码，返回E400且错误次数仍为2','E400',['2']),
 ('停用账号拒绝登录','账号已停用，提交正确未过期验证码','E403',[]),
]
base='测试对象：星桥验证码登录系统。手机号A=13800000001、B=13800000002均已注册。环境允许设置服务端时钟、签发验证码、设置账号状态并查询错误次数和锁定时刻。验证码签发经过时间>=300秒过期E731；否则正确验证码登录返回TOKEN_OK。连续错误1至3次返回E401，第4次立即锁定1140秒并返回E419，锁定期间优先返回E419，锁定经过时间>=1140秒解除。登录成功清零连续错误次数；账号之间隔离。空验证码返回E400且不计错误次数。停用账号返回E403。本轮没有其他规则，不得虚构接口路径或响应耗时阈值。每个用例独立重置环境。'
runs=[]
for repeat in range(3):
 req=request(len(rows));req.test_object='星桥验证码登录系统';req.prompt=base
 points=req.confirmed_plan['test_points']
 for p in points:p['source_refs']=[{'source_id':None,'document_id':None,'chunk_id':None,'label':'验收规则','locator':'当前有效需求','excerpt':base}]
 for f in req.confirmed_plan['feature_points']:f['description']='星桥验证码登录系统的当前有效规则'
 for p,(title,scenario,code,numbers) in zip(points,rows):p.update(title=title,scenario=scenario,objective=scenario+'；预期代码'+code)
 original=source();original['snapshot'].update(title=rows[0][0],module=req.test_object,
  preconditions=['手机号A已启用且未锁定，重置错误次数，签发验证码并记录服务端时刻'],
  steps=[{'action':'推进服务端时钟至签发后299秒，提交手机号A及正确验证码','expected':'返回TOKEN_OK，建立登录会话'}])
 changed=deepcopy(original);changed['key']='asset:old-expiry';changed['snapshot'].update(title='旧版420秒过期',steps=[{'action':'推进时钟至签发后420秒，提交正确验证码','expected':'返回E731，拒绝登录'}])
 req.confirmed_plan['reuse']={'strategy':'regression','decisions':[{'point_id':p['id'],'point_snapshot':deepcopy(p),'action': 'reuse' if i==0 else 'modify' if i==1 else 'new','reason':'规则完全一致' if i==0 else '有效期由420秒改为300秒' if i==1 else '无参考资产',**({'source_key':original['key'],'source':original} if i==0 else {'source_key':changed['key'],'source':changed} if i==1 else {})} for i,p in enumerate(points)]}
 calls=[];previews=[];start=time.perf_counter();record={'repeat':repeat,'rules':base,'oracles':rows}
 def execute(stage,instruction,payload,result_type,model_id):
  result,usage=provider.complete(stage=stage,instruction=instruction,payload=payload,result_type=result_type,model_id=model_id)
  calls.append({'stage':stage,'instruction':instruction,'payload':payload,'output':result.model_dump(mode='json'),'usage':usage.model_dump(mode='json')});return result
 try:
  result=GenerationPipeline(provider).run(req,context={},answers={},execute_stage=execute,on_batch=lambda cases,total:previews.append({'seconds':time.perf_counter()-start,'count':len(cases),'total':total}))
  record['result']=result.model_dump(mode='json');checks=[]
  assert len(result.test_cases)==12
  assert result.test_cases[0].steps[0].action==original['snapshot']['steps'][0]['action']
  assert result.test_cases[0].steps[0].expected==original['snapshot']['steps'][0]['expected']
  for i,(title,scenario,code,numbers) in enumerate(rows):
   matched=[case for case in result.test_cases if points[i]['id'] in case.test_point_ids];assert len(matched)==1
   c=matched[0];body=json.dumps({'preconditions':c.preconditions,'steps':[s.model_dump() for s in c.steps]},ensure_ascii=False)
   expected=' '.join(s.expected for s in c.steps)
   checks.append({'point':points[i]['id'],'case':c.id,'code':code,'correct_code':code in expected,'numbers_present':all(n in body for n in numbers) or (i==3 and '2' in body and '错误验证码' in body and code in expected),'has_setup':bool(c.preconditions),'nonempty_actions':all(s.action.strip() for s in c.steps),'no_old_expiry':'420' not in body,'no_other_system':'PAY-' not in body,'no_unsupported_disabled_count':i!=11 or not re.search('计数|次数|计错',expected)})
  assert all(all(v for k,v in check.items() if isinstance(v,bool)) for check in checks),checks
  assert all(1 not in call['payload'].get('batch_slots',[]) for call in calls)
  record.update(passed=True,checks=checks)
 except Exception as e:record.update(passed=False,error=repr(e))
 record.update(seconds=time.perf_counter()-start,calls=calls,previews=previews);runs.append(record)
 (out/'quality-verified.json').write_text(json.dumps(runs,ensure_ascii=False,indent=2));print({'repeat':repeat,'passed':record['passed'],'seconds':record['seconds'],'error':record.get('error'),'calls':len(calls)},flush=True)
