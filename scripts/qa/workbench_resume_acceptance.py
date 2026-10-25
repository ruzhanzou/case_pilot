"""Live routing of short workbench replies with no historical messages."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from casepilot_api.agent_router import plan_intents
from casepilot_api.config import get_settings
from casepilot_api.rewrite_state import routing_draft_context


def main():
    settings = get_settings()
    if settings.agent_provider == 'mock' or not settings.agent_api_key:
        raise RuntimeError('Live model configuration required')
    operation_id = str(uuid4())
    operation = {'id': operation_id, 'intent': 'CASE_MODIFY', 'status': 'awaiting_target',
                 'target': {'resolved': True, 'case_ids': []}, 'result': {},
                 **routing_draft_context({'instruction': '修改登录模块用例优先级，标题保持不变',
                     'rewrite_draft': {'scope_instruction': '登录模块',
                                      'requirements': '调整优先级，标题保持不变',
                                      'clarification': '希望将优先级改为多少？',
                                      'scope_resolved': True, 'requirements_ready': False}})}
    cases = [('改成P2', 'CASE_MODIFY', True),
             ('只改前两条，优先级P1', 'CASE_MODIFY', True),
             ('先查询支付模块的用例', 'CASE_QUERY', False),
             ('解释一下等价类划分', 'KNOWLEDGE_QA', False)]

    def run(case):
        content, intent, resume = case
        result = plan_intents(content, lambda _: (_ for _ in ()).throw(AssertionError('rule fallback')),
            has_targets=False, phase='maintenance', target_context=[], conversation_memory=[],
            active_operations=[operation], provider=settings.agent_provider,
            model_name=settings.routing_model, base_url=settings.agent_base_url,
            api_key=settings.agent_api_key, timeout_seconds=settings.routing_timeout_seconds,
            tracing_enabled=False)
        actual = result.model_dump(mode='json')['operations']
        passed = (len(actual) == 1 and actual[0]['intent'] == intent
                  and actual[0].get('resume_operation_id') == (operation_id if resume else None))
        return {'content': content, 'expected_intent': intent, 'expected_resume': resume,
                'passed': passed, 'actual': actual}

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, cases))
    output = Path('artifacts/semantic-acceptance/workbench-resume.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps([{'content': r['content'], 'passed': r['passed']} for r in results], ensure_ascii=False))
    return 0 if all(r['passed'] for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
