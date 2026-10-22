"""Real-model mixed reuse regression with captured synthetic requests only."""
import json
import sys
import time
from copy import deepcopy
from pathlib import Path
from dotenv import load_dotenv
root = Path(__file__).resolve().parents[2]
load_dotenv(root / '.env')
sys.path.insert(0, str(root / 'apps/agent/tests'))
from test_compact_generation import request
from test_reuse import source
from casepilot_agent.config import get_settings
from casepilot_agent.pipeline import GenerationPipeline
from casepilot_agent.providers import create_provider
provider = create_provider(get_settings().provider)
out = root / 'output/object-rewrite-regression-20261022'
runs = []
for repeat in range(3):
    req = request(3)
    req.test_object = '账号系统'
    req.prompt = '测试对象：账号系统。有效账号登录建立会话；更新规则：会话有效期30分钟；新增退出后会话立即失效。按确认测试点生成，不添加规则。'
    points = req.confirmed_plan['test_points']
    for point, title, goal in zip(points, ['有效登录', '会话有效期', '退出会话'], ['有效账号登录建立会话', '登录后的会话有效期30分钟', '退出后当前会话立即失效']):
        point.update(title=title, objective=goal, scenario=goal)
    original = source()
    changed = deepcopy(original)
    changed['key'] = 'asset:two'
    req.confirmed_plan['reuse'] = {'strategy': 'regression', 'decisions': [
        {'point_id': points[0]['id'], 'point_snapshot': deepcopy(points[0]), 'action': 'reuse', 'source_key': original['key'], 'source': original, 'reason': '登录建立会话规则一致'},
        {'point_id': points[1]['id'], 'point_snapshot': deepcopy(points[1]), 'action': 'modify', 'source_key': changed['key'], 'source': changed, 'reason': '新增30分钟有效期规则'},
        {'point_id': points[2]['id'], 'point_snapshot': deepcopy(points[2]), 'action': 'new', 'reason': '没有退出资产'},
    ]}
    before = deepcopy(req.confirmed_plan)
    calls = []
    def execute(stage, instruction, payload, result_type, model_id):
        assert payload['test_object'] == '账号系统'
        assert 1 not in payload['batch_slots']
        assert all(item['slot'] == 2 for item in payload['reuse_modifications'])
        result, usage = provider.complete(stage=stage, instruction=instruction, payload=payload, result_type=result_type, model_id=model_id)
        calls.append({'instruction': instruction, 'payload': payload, 'output': result.model_dump(mode='json'), 'usage': usage.model_dump(mode='json')})
        return result
    start = time.monotonic()
    row = {'repeat': repeat}
    try:
        result = GenerationPipeline(provider).run(req, context={}, answers={}, execute_stage=execute)
        assert result.requirement.test_object == '账号系统'
        assert len(result.test_cases) == 3
        assert result.test_cases[0].steps[0].expected == original['snapshot']['steps'][0]['expected']
        row['result'] = result.model_dump(mode='json')
        assert '30' in json.dumps(result.test_cases[1].model_dump(), ensure_ascii=False)
        assert any(term in ' '.join(s.expected for s in result.test_cases[1].steps) for term in ('30分钟', '失效', '无效', '过期'))
        assert any('asset:two' in ref.excerpt for ref in result.test_cases[1].source_refs)
        assert req.confirmed_plan == before
        row.update(passed=True, result=result.model_dump(mode='json'))
    except Exception as exc:
        row.update(passed=False, error=f'{type(exc).__name__}: {exc}')
    row.update(seconds=time.monotonic()-start, calls=calls)
    runs.append(row)
    (out/'real-mixed.json').write_text(json.dumps(runs,ensure_ascii=False,indent=2))
    print({k:v for k,v in row.items() if k not in ('calls','result')}, flush=True)
