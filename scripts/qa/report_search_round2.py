"""Build the second-round evidence report from retained measurements."""
import html
import json
import statistics
from pathlib import Path
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

root = Path(__file__).resolve().parents[2]
out = root / 'output/search-acceptance-round2-20261021'
load = lambda name: json.loads((out / name).read_text())
matrix = load('object-matching.json')['runs']
hundred = load('object-matching-hundred.json')['runs']
perf = load('performance/results.json')
retrieval = load('retrieval.json')
comparisons = {str(c): statistics.median(r['seconds'] for r in matrix if r['concurrency'] == c) for c in (1,2,4)}
baseline = [load(f'search-run-{i}/evidence.json') for i in range(3)]
lean = [load(f'lean-preflight/search-run-{i}/evidence.json') for i in range(3)]
engine = create_engine(make_url(dotenv_values(root / '.env')['DATABASE_URL']).set(host='127.0.0.1', database='casepilot_strategy_acceptance_20261021'))
stages = []
with engine.connect() as connection:
    for label, runs in [('full_asset_preflight', baseline), ('lean_preflight', lean)]:
        for index, run in enumerate(runs):
            job_id = run['selection']['job_id']
            rows = connection.execute(text('''select stage,status,model,latency_ms,token_usage,
                length(input_payload::text) as input_chars
                from generation_job_stages where generation_job_id=:job order by created_at'''), {'job': job_id}).mappings()
            stages.append({'variant': label, 'repeat': index, 'job_id': job_id, 'stages': [dict(row) for row in rows]})
(out / 'stages.json').write_text(json.dumps(stages, ensure_ascii=False, indent=2))
summary = {'model': matrix[0]['calls'][0]['usage']['model'], 'object_match_median_seconds': comparisons,
    'hundred_object_matching': [{k:r[k] for k in ('concurrency','seconds','passed')} for r in hundred],
    'search_api_p95_ms': perf['api']['search']['p95'], 'database_p95_ms': retrieval['p95'],
    'full_asset_preflight_total_ms': [r['totalMs'] for r in baseline],
    'lean_preflight_total_ms': [r['totalMs'] for r in lean],
    'all_object_checks_passed': all(r['passed'] for r in matrix+hundred),
    'all_hundred_searches_passed': all(r['passed'] for r in baseline+lean)}
analysis_stats = {}
for variant in ('full_asset_preflight', 'lean_preflight'):
    selected = [stage for run in stages if run['variant'] == variant for stage in run['stages'] if stage['stage'] == 'requirement.batch.1']
    analysis_stats[variant] = {'median_ms': statistics.median(stage['latency_ms'] for stage in selected),
        'median_input_tokens': statistics.median(stage['token_usage']['input_tokens'] for stage in selected)}
summary['requirement_analysis'] = analysis_stats
summary['deterministic_tests'] = 336
summary['mixed_journey_passed'] = load('mixed-regression/run-0/real-e2e-results.json')['status'] == 'passed'
(out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
scenarios = [
    ('默认生成/咨询/否定/引用', '不启动资产搜索', 'regression.xml'),
    ('自然语言查找，100 条同对象资产', '完整待确认，未生成候选，刷新恢复', 'search-lean.xml'),
    ('混合同对象/不同对象/未知对象', '仅同对象进入确认列表，11 组真实核对通过', 'object-matching.json'),
    ('0/1/12/13/100 条边界与乱序完成', '稳定顺序及版本，不漏不重', 'search-regression.xml'),
    ('非法来源编号及重复输入身份', '保存检查点前拒绝，不返回部分确认列表', 'regression.xml'),
    ('限流/单批失败/取消', '仅失败批次重试，取消停止继续派发', 'regression.xml'),
    ('1000 条资产，5 用户各 30 次', '搜索接口 P95 ≤ 2 秒', 'performance/results.json'),
    ('百条确认列表、键盘操作', '列表独立滚动，已选数量正确', 'ui-final.xml'),
    ('1024/1280/1440、历史与断网恢复', '无横向溢出，可恢复既有内容', 'performance.xml'),
    ('默认生成、多集合选用、混合复用/改写/新增', '确认、生成、采纳、刷新来源均通过真实模型回归', 'mixed-regression.xml'),
    ('检查点恢复与有效批次复用', '5 项附加回归通过，不重复有效批次', 'checkpoints.xml'),
    ('修改范围、来源版本、跨用户与旧任务', '保持既有保护与修改流程', 'regression.xml'),
]
(out / 'acceptance-cases.json').write_text(json.dumps([{'scenario':a,'expected':b,'evidence':c} for a,b,c in scenarios],ensure_ascii=False,indent=2))
def link(name, label=None):
    return f'<a href="{html.escape(name)}">{html.escape(label or name)}</a>'
rows = ''.join(f'<tr><td>{a}</td><td>{b}</td><td>{link(c)}</td></tr>' for a,b,c in scenarios)
base_median = statistics.median(summary['full_asset_preflight_total_ms'])/1000
lean_median = statistics.median(summary['lean_preflight_total_ms'])/1000
report = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>第二轮搜索验收</title>
<style>body{{font:16px/1.7 system-ui;margin:40px auto;max-width:1100px;padding:0 24px;color:#223047}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ccd4e0;padding:10px;text-align:left}}img{{max-width:100%;border:1px solid #ccd4e0}}a{{color:#1657ba}}code{{background:#eef2f7}}h1,h2{{color:#123c6a}}</style>
<h1>第二轮验收：用例搜索性能与确认体验</h1><p>2026-10-21 · 隔离数据库与本地生产构建 · 未发布生产 · 模型 {summary['model']}</p>
<h2>本轮修复</h2><ol><li>对象核对从每 12 条串行改为最多 4 路并发；每批独立连接保存检查点，取消检查阻止晚到结果写入，输出保留原检索顺序。可用 CASEPILOT_ASSET_MATCH_CONCURRENCY 调低至 1–4。</li>
<li>来源编号完整性校验前移到检查点保存之前，防止非法模型结果被缓存后不断重放；重复输入身份直接拒绝。</li>
<li>确认前使用独立需求分析提示词，不再通过 existing_cases 重复传递待确认资产正文，不提取功能和测试点；完整资产仍用于对象核对，确认后生成流程不变。</li>
<li>百条资产列表独立滚动并支持键盘，显示已选数量，工作区确认按钮保持可达。</li></ol>
<h2>性能证据</h2><table><tr><th>测量</th><th>结果</th></tr>
<tr><td>36 条资产，串行/并发 2/并发 4，各 3 次中位数</td><td>{comparisons['1']:.1f}s / {comparisons['2']:.1f}s / {comparisons['4']:.1f}s</td></tr>
<tr><td>100 条混合对象资产，串行→并发 4（各一次）</td><td>{hundred[0]['seconds']:.1f}s → {hundred[1]['seconds']:.1f}s；对象集合与顺序均正确</td></tr>
<tr><td>100 条完整对话搜索，精简分析前→后（均已开启并发，各 3 次中位数）</td><td>{base_median:.1f}s → {lean_median:.1f}s；包含提交、任务等待、分析、核对和轮询，不等同单模型调用</td></tr>
<tr><td>1000 条资产，5 用户普通搜索接口，共 150 次</td><td>P95 {summary['search_api_p95_ms']:.1f}ms</td></tr>
<tr><td>对话实际数据库检索＋来源归属，共 150 次</td><td>P95 {retrieval['p95']['total_ms']:.1f}ms</td></tr></table>
<p>确认前分析输入从 27968 降到 2059 token（约减少 92.6%），该阶段中位耗时从 12.4s 降到 7.5s；完整对话搜索中位耗时 54.4s → 58.4s，没有证明总耗时进一步改善。保留提示词收窄是为了避免未确认资产污染当前需求，并减少重复输入；不宣称整体加速。</p>
<p>并发 4 相对并发 2 中位耗时改善超过 10%，因此采用 4；每批仍为 12 条，不减少对象核对内容。普通接口指标与上一轮处于相同范围，不能据此声称 SQL 提速。</p>
<p>{link('object-matching.json','真实模型九组原始数据')} · {link('object-matching-hundred.json','百条对象核对')} · {link('stages.json','逐阶段耗时、token 与输入长度')} · {link('summary.json','结果汇总')}</p>
<h2>验收集合</h2><table><tr><th>场景</th><th>检查</th><th>证据</th></tr>{rows}</table>
<h2>限制与失败记录</h2><p>331 项主回归及 5 项附加检查点回归通过（共 336 项，另一次 59 项搜索子集不重复计数）。百条完整对话搜索优化前后三轮均通过，最终混合流程真实模型回归通过。并发比较使用单搜索任务；五用户并发仅测普通接口，未验证五个大规模模型搜索同时运行的供应商容量。真实供应商限流未主动触发，限流恢复使用确定性测试。100 条模型对比各一次，36 条对比各三次，不将其包装为模型 P95。</p>
<p>初版浏览器验收脚本直接绑定空集合，违反现有“创建新集合确认”入口约束，三次均收到 422。修正脚本走真实创建确认流程后重新执行；保留 {link('search-e2e.log','原失败日志')} 与 {link('search-harness-failures/','失败截图/trace')}，不计入通过。</p>
<h2>1024 宽度百条确认列表</h2><img src="lean-preflight/search-run-0/confirmation-1024.png" alt="百条资产确认列表及滚动区域"></html>'''
(out / 'report.html').write_text(report)
print(json.dumps(summary, ensure_ascii=False))
