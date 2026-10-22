"""Recheck frozen outputs without model resampling or requiring a synonym."""
import json
from pathlib import Path
out = Path(__file__).resolve().parents[2] / 'output/object-rewrite-regression-20261022'
runs = json.loads((out/'real-mixed.json').read_text())
checks=[]
for run in runs:
    result=run['result']; cases=result['test_cases']
    assert result['requirement']['test_object']=='账号系统'
    assert len(cases)==3
    assert cases[0]['steps']==[{'action':'输入正确凭据登录','expected':'建立用户会话'}]
    assert all(1 not in call['payload']['batch_slots'] for call in run['calls'])
    assert all(call['payload']['test_object']=='账号系统' for call in run['calls'])
    expected=' '.join(step['expected'] for step in cases[1]['steps'])
    assert '30' in json.dumps(cases[1],ensure_ascii=False)
    assert any(term in expected for term in ('30分钟','失效','无效','过期'))
    assert any('asset:two' in ref['excerpt'] for ref in cases[1]['source_refs'])
    assert '失效' in ' '.join(step['expected'] for step in cases[2]['steps'])
    checks.append({'repeat':run['repeat'],'passed':True,'seconds':run['seconds'],'calls':len(run['calls'])})
(out/'revalidated-mixed.json').write_text(json.dumps({'note':'原始结果不改写。数值可以在操作中，预期也可直接表述30分钟有效期；不强制出现失效一词。', 'checks':checks},ensure_ascii=False,indent=2))
print(checks)
