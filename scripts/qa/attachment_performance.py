"""Real attachment -> analysis -> planning -> confirmed candidates performance run."""
import argparse
import hashlib
import json
import re
import time
from datetime import datetime
from pathlib import Path

import httpx

DOMAINS = [
    ('LOGIN', '账号登录', ['正确密码登录成功', '错误密码拒绝登录', '连续5次错误锁定15分钟',
                         '验证码有效期5分钟', '验证码仅能使用一次', '退出后旧会话失效']),
    ('ORDER', '订单管理', ['库存充足创建订单成功', '库存不足拒绝创建订单', '同一幂等键仅创建一个订单',
                         '待支付订单30分钟自动关闭', '已取消订单不能支付', '订单仅允许所属用户读取']),
    ('REFUND', '退款管理', ['已支付订单可申请退款', '退款金额不得超过实付金额', '未支付订单拒绝退款',
                          '同一退款请求重复提交只处理一次', '退款成功后状态变为已退款', '退款失败保留原订单支付状态']),
]


def fixture(path):
    sections = []
    for prefix, title, rules in DOMAINS:
        section = f'# {title}\n本章有且仅有以下6条规则，后附样例不新增规则。\n'
        section += ''.join(f'{prefix}-{i+1}: {rule}。\n' for i, rule in enumerate(rules))
        rows = []
        for n in range(1, 3000):
            rows.append(f'样例 {prefix}-{n:05}: 用户U{n}，业务B{n*17}；适用规则'
                        f'{prefix}-{n%6+1}：{rules[n%6]}。此记录为测试数据，不新增约束。\n')
        # Distribute three domains throughout the fixed-size document.
        body = ''.join(rows).encode()[:348000].decode(errors='ignore')
        section += body + '\n本章末尾规则复核：\n'
        section += ''.join(f'{prefix}-{i+1}: {rule}。\n' for i, rule in enumerate(rules))
        sections.append(section)
    raw = ('合成性能测试需求 v2；共18条规则。\n' + '\n'.join(sections)).encode()
    assert len(raw) <= 1048576
    raw += b' ' * (1048576-len(raw))
    path.write_bytes(raw)
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'characters': len(raw.decode()), 'nonpadding_bytes': len(raw.rstrip()),
            'expected_rules': 18}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', required=True)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--output', default='output/attachment-1m-20261011')
    parser.add_argument('--api', default='http://localhost:8000/api/v1')
    args = parser.parse_args()
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=True)
    path = root/'requirements-1MiB.txt'
    report = {'label': args.label, 'fixture': fixture(path), 'timings': {}, 'samples': []}
    output = root/f'{args.label}.json'
    if args.resume:
        report = json.loads(output.read_text())
        report.pop('error', None)
        report['status'] = 'running'
    def save():
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    client = httpx.Client(base_url=args.api, timeout=180, trust_env=False)
    def get(url):
        response = client.get(url)
        response.raise_for_status()
        return response.json()
    def post(url, data):
        response = client.post(url, json=data)
        response.raise_for_status()
        return response.json()
    report.setdefault('started_at_unix', datetime.fromisoformat(report['upload']['source']['created_at']).timestamp() if args.resume else time.time())
    start = time.monotonic() - max(0, time.time()-report['started_at_unix'])
    def wait_job(job_id, phase):
        phase_elapsed = report.setdefault('phase_starts', {}).setdefault(phase, next(
            (sample['elapsed'] for sample in report['samples'] if sample['phase'] == phase),
            time.monotonic()-start))
        phase_start, previous = start + phase_elapsed, None
        retries = 0
        while time.monotonic()-phase_start < 3600:
            job = get('/generation-jobs/'+job_id)
            marker = (job['status'], job.get('stage', job.get('current_stage')),
                      json.dumps(job.get('planning_progress')), job.get('generated_count'))
            if marker != previous:
                sample = {'elapsed': round(time.monotonic()-start, 3), 'phase': phase,
                          **{k: job.get(k) for k in ['status', 'stage', 'current_stage',
                              'planning_progress', 'generated_count', 'error_code']}}
                report['samples'].append(sample)
                print(json.dumps(sample, ensure_ascii=False), flush=True)
                previous = marker
                save()
            if phase == 'generation':
                state = get('/conversations/'+report['conversation_id'])
                if state.get('candidates') and 'first_candidates_seconds' not in report['timings']:
                    report['timings']['first_candidates_seconds'] = time.monotonic()-phase_start
            if job['status'] == 'failed' and retries < 2:
                report.setdefault('retries', []).append({'phase': phase, 'job_id': job_id,
                    'elapsed': time.monotonic()-start, 'error_code': job.get('error_code')})
                save()
                post('/generation-jobs/'+job_id+'/retry', {})
                retries += 1
                time.sleep(3)
                continue
            if job['status'] in ('completed', 'failed', 'cancelled', 'awaiting_input'):
                report[phase+'_job'] = job
                report['timings'][phase+'_seconds'] = time.monotonic()-phase_start
                save()
                if job['status'] != 'completed':
                    raise RuntimeError(f'{phase}: {job["status"]}, {job.get("error_code")}')
                return job
            time.sleep(3)
        raise TimeoutError(phase)
    try:
        if not args.resume:
            email = f'perf-1m-{args.label}-{time.time_ns()}@casepilot.test'
            account = post('/auth/register', {'email': email, 'password': 'CasePilot123!',
                                             'display_name': '1MiB附件性能验收'})
            report['account'] = email
            report['models'] = get('/generation-models')
            space = account['spaces'][0]['id']
            collection = post(f'/spaces/{space}/collections', {'name': f'1MiB性能-{args.label}'})
            conversation = post('/conversations', {'space_id': space, 'collection_id': collection['id']})
            report.update(collection_id=collection['id'], conversation_id=conversation['id'])
            cid = conversation['id']
            upload_start = time.monotonic()
            with path.open('rb') as attachment:
                response = client.post(f'/conversations/{cid}/attachments',
                                       files={'files': (path.name, attachment, 'text/plain')})
            response.raise_for_status()
            upload = response.json()
            report['upload'] = upload
            report['timings']['upload_http_seconds'] = time.monotonic()-upload_start
            save()
            source_id = upload['source']['id']
            while time.monotonic()-upload_start < 600:
                source = get('/knowledge-sources/'+source_id)
                if source['status'] == 'ready':
                    break
                if source['status'] == 'failed':
                    raise RuntimeError(f'attachment failed: {source}')
                time.sleep(1)
            else:
                raise TimeoutError('attachment ingestion')
            report['source'] = source
            report['timings']['attachment_ready_seconds'] = time.monotonic()-upload_start
            send_start = time.monotonic()
            turn = post(f'/conversations/{cid}/messages', {
                'content': '根据附件为账号登录、订单管理、退款管理生成18条测试用例，每模块6条，每条对应一条明确业务规则。样例记录只是测试数据，不新增规则。标题保留LOGIN-1等规则编号，保留精确数值，每条包含前置条件、步骤和逐步预期结果。先完成规划，待确认后生成候选用例。',
                'model_id': 'auto', 'document_ids': upload['document_ids'],
                'knowledge_source_ids': [source_id], 'use_space_knowledge': False,
            })
            report['turn'] = turn
            report['timings']['routing_seconds'] = time.monotonic()-send_start
            save()
            jid = turn['action']['job_id']
            report['planning_job_id'] = jid
        else:
            post('/auth/login', {'email': report['account'], 'password': 'CasePilot123!'})
            cid = report['conversation_id']
            jid = report['planning_job_id']
        wait_job(jid, 'planning')
        state = get('/conversations/'+cid)
        report['planned_state'] = state
        brief = state['test_briefs'][-1]
        report['plan_counts'] = {key: len(brief['content']['planning'].get(key, []))
                                 for key in ['feature_points', 'test_points']}
        planning = brief['content']['planning']
        expected = [f'{prefix}-{i+1}' for prefix, _, rules in DOMAINS for i in range(len(rules))]
        by_id = {f['id']: f for f in planning['feature_points']}
        selected, mapping = [], {}
        for rule in expected:
            pattern = re.compile(re.escape(rule) + r'(?![0-9])')
            for point in planning['test_points']:
                linked = [by_id[fid] for fid in point['feature_point_ids']]
                text = json.dumps([{k: f.get(k) for k in ['name', 'description', 'requirement_refs']}
                                   for f in linked], ensure_ascii=False)
                matched = [code for code in expected if re.search(re.escape(code)+r'(?![0-9])', text)]
                if point['id'] not in selected and pattern.search(text) and matched == [rule]:
                    selected.append(point['id'])
                    mapping[rule] = point['id']
                    break
        report['confirmed_rule_selection'] = mapping
        if len(selected) != 18:
            raise AssertionError(f'Cannot map all 18 rules to distinct planning points: {mapping}')
        turn = post(f'/workspaces/{cid}/test-briefs/confirm', {'version': brief['version'],
                    'model_id': 'auto', 'selected_test_point_ids': selected})
        report['generation_turn'] = turn
        jid = turn['action']['job_id']
        report['generation_job_id'] = jid
        save()
        wait_job(jid, 'generation')
        state = get('/conversations/'+cid)
        report['final_state'] = state
        candidates = state['candidates']
        report['candidate_count'] = len(candidates)
        report['persisted_count'] = len(get('/conversations/'+cid)['candidates'])
        report['checks'] = {
            'exact_count': len(candidates) == 18,
            'all_steps_complete': all(c['snapshot'].get('steps') and all(
                s.get('action') and s.get('expected') for s in c['snapshot']['steps']) for c in candidates),
            'persisted': report['persisted_count'] == len(candidates),
            'rules_in_titles': {f'{prefix}-{i+1}': sum(f'{prefix}-{i+1}' in c['snapshot']['title']
                                 for c in candidates) for prefix, _, rules in DOMAINS for i in range(len(rules))},
        }
        report['status'] = 'completed'
    except Exception as error:
        report['status'] = 'failed'
        report['error'] = str(error)
        raise
    finally:
        report['timings']['active_run_seconds'] = time.monotonic()-start
        report['timings']['wall_seconds'] = time.time()-report['started_at_unix']
        save()
        print(json.dumps({k: report.get(k) for k in ['status', 'error', 'timings', 'plan_counts', 'checks']}, ensure_ascii=False), flush=True)
        client.close()


if __name__ == '__main__':
    main()
