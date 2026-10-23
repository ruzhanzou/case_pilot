"""Real-model range selection against a 5001-case synthetic authorized catalog."""
import json
import time
from pathlib import Path

from casepilot_api.config import get_settings
from casepilot_api.scope_filter import select_large_scope

settings = get_settings()
cases = [{'id': str(i), 'case_key': f'BIG-{i}', 'kind': 'formal',
          'module': '支付/退款' if i % 2 else '账号',
          'priority': 'P0' if i % 3 == 0 else 'P1',
          'steps': [{'action': '提交', 'expected': '超时后回滚'}]} for i in range(5001)]
scenarios = [
    ('组合排除', '查询支付模块及其子模块中步骤包含“回滚”的正式用例，排除P0。', {},
     [str(i) for i in range(5001) if i % 2 and i % 3]),
    ('追加范围', '把当前选中的用例加上BIG-5000一起修改，优先级改为P0，其他字段不动。',
     {'selected_ids': ['1', '3']}, ['1', '3', '5000']),
    ('空查询引用', '删除刚才查询到的用例，不扩大范围。', {'latest_query': {'ids': []}}, []),
    ('赋值不筛选', '修改账号模块的P1用例为P0，保留标题步骤和预期。', {},
     [str(i) for i in range(5001) if not i % 2 and i % 3]),
]
results = []
output = Path('output/maturity-acceptance-20261023/large-scope-matrix.json')
for name, instruction, context, expected in scenarios:
    started = time.monotonic()
    decision = select_large_scope(
        instruction, cases, {'phase': 'maintenance', **context},
        intent='CASE_QUERY' if name == '组合排除' else 'CASE_DELETE' if name == '空查询引用' else 'CASE_MODIFY',
        model_name=settings.routing_model, base_url=settings.agent_base_url,
        api_key=settings.agent_api_key, timeout_seconds=settings.routing_timeout_seconds,
        tracing_enabled=False)
    results.append({'name': name, 'exact_match': decision.ids == expected,
                    'ambiguous': decision.ambiguous, 'clarification': decision.clarification,
                    'count': len(decision.ids), 'expected_count': len(expected),
                    'seconds': time.monotonic() - started})
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(results[-1], flush=True)
assert all(item['exact_match'] and not item['ambiguous'] for item in results)
