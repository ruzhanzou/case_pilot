"""Compare identical object-matching requests; retain every real-model outcome."""
import json
import os
import time
from pathlib import Path
from threading import Lock

from dotenv import load_dotenv

root = Path(__file__).resolve().parents[2]
load_dotenv(root / '.env')
from casepilot_agent.config import get_settings
from casepilot_agent.providers import create_provider
from casepilot_agent.reuse import match_asset_objects

out = root / 'output/search-acceptance-round2-20261021' / os.environ.get('ASSET_MATCH_OUTPUT', 'object-matching.json')
out.parent.mkdir(parents=True, exist_ok=True)
provider = create_provider(get_settings().provider)
count = int(os.environ.get('ASSET_MATCH_COUNT', '36'))
sources = []
for i in range(count):
    kind = i % 3
    system = ['星河订单系统', '北斗订单系统', '未记录系统'][kind]
    sources.append({'key': f'asset:{i}', 'kind': 'formal', 'revision': f'revision:{i}',
        'collections': [{'id': f'collection:{kind}', 'name': system}],
        'snapshot': {'title': f'{system}创建订单场景{i}', 'module': '订单创建',
            'preconditions': [f'进入{system}' if kind != 2 else '已登录'],
            'steps': [{'action': '提交订单', 'expected': '订单保存成功'}]}})
expected = [s['key'] for i,s in enumerate(sources) if i % 3 == 0]
results = []
for repeat in range(int(os.environ.get('ASSET_MATCH_REPEATS', '3'))):
    for concurrency in map(int, os.environ.get('ASSET_MATCH_CONCURRENCIES', '1,2,4').split(',')):
        calls, lock = [], Lock()
        def complete(stage, instruction, payload, result_type):
            start = time.monotonic()
            try:
                result, usage = provider.complete(stage=stage, instruction=instruction,
                    payload={**payload, 'prompt': '找星河订单系统已有用例参考一下'},
                    result_type=result_type, model_id='auto')
                with lock:
                    calls.append({'seconds': time.monotonic()-start,
                        'usage': usage.model_dump(mode='json'),
                        'matches': result.model_dump(mode='json')})
                return result
            except Exception as exc:
                with lock:
                    calls.append({'seconds': time.monotonic()-start, 'error': type(exc).__name__})
                raise
        start = time.monotonic()
        row = {'repeat': repeat, 'concurrency': concurrency, 'count': count}
        try:
            found = match_asset_objects(sources, '星河订单系统的订单创建', complete,
                concurrency=concurrency)
            row.update(keys=[s['key'] for s in found], passed=[s['key'] for s in found] == expected)
        except Exception as exc:
            row.update(error=type(exc).__name__, passed=False)
        row.update(seconds=time.monotonic()-start, calls=calls)
        results.append(row)
        out.write_text(json.dumps({'sources': sources, 'expected': expected, 'runs': results}, ensure_ascii=False, indent=2))
        print(json.dumps({k:v for k,v in row.items() if k not in ('calls','keys')}), flush=True)
