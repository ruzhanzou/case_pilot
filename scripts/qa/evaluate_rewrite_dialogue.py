"""Real-model API dialogue evaluation with isolated synthetic fixtures.

Setup alone uses the offline provider. Every evaluated reply and scope selection
uses the configured live provider. Queue dispatch is captured, so this validates
API gates/state, not worker output or browser behavior. No model output is mocked.
Run in a separate process; never import into a serving API process.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import logging
import math
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from casepilot_api import conversations
from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import Account, ConversationOperation, GenerationJob, Space, TestCase


def expect_response(response, status):
    if response.status_code != status:
        raise AssertionError(f"HTTP {response.status_code}: {response.text[:800]}")
    return response.json()


def validate_dataset(data):
    aliases = {item['alias'] for item in data['fixture']}
    assert len(aliases) == len(data['fixture'])
    ids = [item['id'] for item in data['scenarios']]
    assert len(ids) == len(set(ids))
    for scenario in data['scenarios']:
        assert set(scenario['initial_scope']) <= aliases
        assert scenario['turns']
        for index, turn in enumerate(scenario['turns']):
            expected = turn['expect']
            assert expected['action'] in {'preview', 'dispatch', 'clarify', 'cancel'}
            assert set(expected['scope']) <= aliases
            for pattern in expected['requirements_include'] + expected['requirements_exclude']:
                re.compile(pattern)
            assert set(re.findall(r'\{\{(.*?)\}\}', turn['input'])) <= aliases
            if expected['action'] in {'dispatch', 'cancel'}:
                assert index == len(scenario['turns']) - 1, 'terminal action must end the dialogue'
    return data


async def prepare(scenario, fixture, owned):
    client = AsyncClient(transport=ASGITransport(app=app), base_url='http://eval', timeout=180)
    suffix = uuid4().hex[:12]
    registration = expect_response(await client.post('/api/v1/auth/register', json={
        'email': f'rewrite-eval-{suffix}@casepilot.test', 'display_name': '改写对话评测',
        'password': uuid4().hex + 'Aa1!',
    }), 201)
    space = registration['spaces'][0]['id']
    owned.append((UUID(space), UUID(registration['id'])))
    collection = (await client.get(f'/api/v1/spaces/{space}/collections')).json()[0]['id']
    cases = {}
    for item in fixture:
        values = {key: value for key, value in item.items() if key != 'alias'}
        values['case_key'] = f"TC-{item['alias']}-{suffix}"
        case = expect_response(await client.post(f'/api/v1/collections/{collection}/test-cases', json=values), 201)
        cases[item['alias']] = case
    workspace = expect_response(await client.put(f'/api/v1/collections/{collection}/workspace'), 200)['id']
    turn = expect_response(await client.post(f'/api/v1/conversations/{workspace}/messages', json={
        'content': scenario['initial_instruction'], 'intent_override': 'CASE_MODIFY',
        'target_case_ids': [cases[alias]['id'] for alias in scenario['initial_scope']],
    }), 202)
    operation = turn['operation_plan']['operations'][0]['id']
    return {'client': client, 'workspace': workspace, 'operation': operation, 'cases': cases}


async def evaluate(scenario, prepared, semaphore):
    async with semaphore:
        client, cases, oid = prepared['client'], prepared['cases'], prepared['operation']
        record = {'id': scenario['id'], 'title': scenario['title'], 'split': scenario.get('split', 'development'),
                  'repeat': scenario.get('_repeat', 1),
                  'conversation_id': prepared['workspace'], 'turns': [], 'status': 'PASS'}
        try:
            for step in scenario['turns']:
                text = step['input']
                for alias, case in cases.items():
                    text = text.replace('{{' + alias + '}}', case['case_key'])
                request = {'content': text}
                with get_session_factory()() as db:
                    prior = db.get(ConversationOperation, UUID(oid))
                    if step.get('echo') == 'current':
                        request['targets'] = [{'kind': 'case', 'case_ids': prior.target.get('case_ids', []),
                                               'candidate_refs': prior.target.get('candidate_refs', [])}]
                if step.get('selection'):
                    request['target_case_ids'] = [cases[alias]['id'] for alias in step['selection']]
                started = time.perf_counter()
                response = await client.post(f'/api/v1/conversation-operations/{oid}/resume', json=request)
                elapsed = round((time.perf_counter() - started) * 1000)
                current = {'input': text, 'request': request, 'latency_ms': elapsed,
                           'expected': step['expect'], 'http_status': response.status_code}
                record['turns'].append(current)
                result = expect_response(response, 202)
                current['reply'] = result['assistant_message']['content']
                current['action'] = result['action']
                with get_session_factory()() as db:
                    op = db.get(ConversationOperation, UUID(oid))
                    current['operation_status'] = op.status
                    current['draft'] = copy.deepcopy(op.payload.get('rewrite_draft', {}))
                    pending = op.payload.get('modification_confirmation')
                    actual = ('dispatch' if result['action'].get('job_id') else 'cancel'
                              if op.status == 'cancelled' else 'preview' if pending else 'clarify')
                    current['actual_action'] = actual
                    scope_ids = op.target.get('case_ids', [])
                    current['actual_scope'] = [a for a, c in cases.items() if c['id'] in scope_ids]
                    expected = step['expect']
                    failures = []
                    if actual != expected['action']:
                        failures.append(f"action: expected {expected['action']}, got {actual}")
                    if actual in {'preview', 'dispatch'} and set(current['actual_scope']) != set(expected['scope']):
                        failures.append(f"scope: expected {expected['scope']}, got {current['actual_scope']}")
                    requirements = str(op.payload.get('instruction', ''))
                    current['requirements'] = requirements
                    for pattern in expected['requirements_include']:
                        if not re.search(pattern, requirements, re.I):
                            failures.append(f'missing requirement: {pattern}')
                    for pattern in expected['requirements_exclude']:
                        if re.search(pattern, requirements, re.I):
                            failures.append(f'stale requirement: {pattern}')
                    if actual in {'preview', 'dispatch'} and scenario['id'] != 'RW-29':
                        for pattern in [r'标题|title', r'预期|expected']:
                            if not re.search(pattern, requirements, re.I):
                                failures.append(f'lost original constraint: {pattern}')
                    if actual == 'dispatch':
                        job = db.get(GenerationJob, UUID(result['action']['job_id']))
                        current['job_prompt'] = job.input_payload['prompt']
                        if job.input_payload['prompt'] != requirements:
                            failures.append('worker prompt differs from persisted requirements')
                        actual_refs = {item['ref'] for item in job.input_payload['case_context']}
                        if actual_refs != {cases[a]['id'] for a in expected['scope']}:
                            failures.append('job scope differs from expected preview')
                    for alias, case in cases.items():
                        if str(db.get(TestCase, UUID(case['id'])).current_revision_id) != case['current_revision_id']:
                            failures.append(f'formal revision changed before adoption: {alias}')
                    current['failures'] = failures
                    # Refresh observes persisted state, not just the response body.
                    restored = expect_response(await client.get(f"/api/v1/conversations/{prepared['workspace']}"), 200)
                    restored_op = next(o for o in restored['operation_plan']['operations'] if o['id'] == oid)
                    if restored_op['payload'].get('rewrite_draft', {}) != current['draft']:
                        failures.append('draft does not survive refresh')
                if failures:
                    record['status'] = 'FAIL'
                    record['not_run_turns'] = len(scenario['turns']) - len(record['turns'])
                    break
        except Exception as error:
            record['status'] = 'ERROR'
            record['error'] = f'{type(error).__name__}: {str(error)[:1000]}'
        finally:
            await client.aclose()
        print(f"{record['id']} repeat={record['repeat']} {record['status']} ({len(record['turns'])} turns)", flush=True)
        return record


async def run(args):
    started_at = datetime.now(UTC).isoformat()
    dataset_text = Path(args.dataset).read_text()
    data = validate_dataset(json.loads(dataset_text))
    if args.validate_only:
        print(f"Valid: {len(data['scenarios'])} scenarios, {sum(len(s['turns']) for s in data['scenarios'])} turns")
        return
    settings = conversations.settings
    if settings.agent_provider == 'mock' or not settings.agent_api_key:
        raise SystemExit('Live provider and configured credentials required; mock results cannot be reported as live evaluation.')
    provider = settings.agent_provider
    scenarios = [s for s in data['scenarios'] if not args.ids or s['id'] in args.ids.split(',')]
    if not scenarios:
        raise SystemExit('No scenarios selected')
    scenarios = [{**scenario, '_repeat': repeat} for repeat in range(1, args.repeat + 1) for scenario in scenarios]
    owned, prepared = [], []
    original_enqueue = conversations.enqueue_task
    # This interception is process-local and does not affect the running API.
    conversations.enqueue_task = lambda *a, **k: None
    try:
        settings.agent_provider = 'mock'
        for scenario in scenarios:
            prepared.append(await prepare(scenario, data['fixture'], owned))
        settings.agent_provider = provider
        semaphore = asyncio.Semaphore(args.concurrency)
        results = await asyncio.gather(*(evaluate(s, p, semaphore) for s, p in zip(scenarios, prepared)))
        durations = sorted(t['latency_ms'] for r in results for t in r['turns'])
        summary = {state: sum(r['status'] == state for r in results) for state in ['PASS', 'FAIL', 'ERROR']}
        report = {'schema_version': 1, 'started_at': started_at, 'finished_at': datetime.now(UTC).isoformat(),
                  'commit': args.commit, 'dataset_sha256': hashlib.sha256(dataset_text.encode()).hexdigest(),
                  'layer': 'live-model-api-state-machine; queue captured; not worker/browser E2E',
                  'model': settings.agent_model, 'provider': provider, 'concurrency': args.concurrency,
                  'repeat_count': args.repeat,
                  'scenario_count': len(results), 'dataset_scenario_count': len(data['scenarios']),
                  'turn_count': len(durations), 'planned_turn_count': sum(len(s['turns']) for s in scenarios),
                  'summary': summary, 'results': results,
                  'latency_ms': {'p50': durations[math.ceil(.5*len(durations))-1],
                                 'p95': durations[math.ceil(.95*len(durations))-1], 'max': max(durations)}}
        destination = Path(args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps({key: report[key] for key in ['summary', 'turn_count', 'latency_ms']}, ensure_ascii=False), flush=True)
    finally:
        settings.agent_provider = provider
        conversations.enqueue_task = original_enqueue
        for item in prepared:
            await item['client'].aclose()
        with get_session_factory()() as db:
            for space, account in owned:
                db.execute(delete(Space).where(Space.id == space))
                db.execute(delete(Account).where(Account.id == account))
            db.commit()
    if summary['FAIL'] or summary['ERROR']:
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', default='docs/evaluations/rewrite-dialogue-v1.json')
    parser.add_argument('--output', default='output/rewrite-dialogue-evaluation/result.json')
    parser.add_argument('--ids', help='Comma-separated scenario IDs for focused reruns')
    parser.add_argument('--commit', default='unknown', help='Code revision, or revision plus dirty marker')
    parser.add_argument('--repeat', type=int, choices=range(1, 6), default=1, help='Fresh fixtures per independent repeat')
    parser.add_argument('--concurrency', type=int, choices=range(1, 5), default=2)
    parser.add_argument('--validate-only', action='store_true')
    logging.getLogger('openai.agents').setLevel(logging.CRITICAL)
    asyncio.run(run(parser.parse_args()))
