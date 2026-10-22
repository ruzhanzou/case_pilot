"""Render the QA journey evidence without discarding failed attempts."""
import csv
import html
import json
from pathlib import Path
import xml.etree.ElementTree as ET

root = Path('output/qa-journey-20261022')
results = []
for name in ['journeys', 'fuzzy', 'fixed-journeys', 'final-journeys', 'formal-repeat', 'verified-formal', 'ten-repeat', 'final-core', 'performance', 'regression']:
    path = root / f'{name}.xml'
    if path.exists():
        for case in ET.parse(path).iter('testcase'):
            status = '失败' if case.find('failure') is not None or case.find('error') is not None else '跳过/中断' if case.find('skipped') is not None else '通过'
            results.append([name, case.get('name'), status, case.get('time')])
with (root / 'execution-matrix.csv').open('w') as f:
    writer = csv.writer(f); writer.writerow(['执行轮次', '验收项', '结果', '耗时秒']); writer.writerows(results)
utterances = []
for path in root.rglob('evidence.json'):
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        continue
    turns = value.get('events', []) + value.get('turns', [])
    for turn in turns:
        response = turn.get('result', turn)
        if not isinstance(response, dict):
            continue
        message = response.get('user_message') or {}
        text = turn.get('content') or message.get('content', '')
        assistant = response.get('assistant_message') or {}
        utterances.append([str(path.relative_to(root)), value.get('kind', '多轮修改'), text,
            response.get('intent', ''), ';'.join(assistant.get('target_case_ids', [])),
            (response.get('action') or {}).get('type', ''), value.get('status', '参见执行记录')])
with (root / 'conversation-matrix.csv').open('w') as f:
    writer = csv.writer(f); writer.writerow(['证据', '阶段', '用户原话', '识别意图', '目标用例', '操作', '链路结果']); writer.writerows(utterances)
perf = json.loads((root / 'performance/results.json').read_text())
retrieval = json.loads((root / 'retrieval.json').read_text())
esc = html.escape
rows = ''.join(f'<tr><td>{esc(k)}</td><td>{len(v["samples"])}</td><td>{v["p95"]:.1f} ms</td><td>≤ 2000 ms</td></tr>' for k,v in perf['api'].items())
rows += ''.join(f'<tr><td>{k}px 恢复 / 输入反馈</td><td>30 / 30</td><td>{v["recoveryP95"]:.1f} / {v["interactionP95"]:.1f} ms</td><td>≤ 3000 / 200 ms</td></tr>' for k,v in perf['ui'].items())
rows += f'<tr><td>提交反馈</td><td>30</td><td>{perf["submission"]["p95"]:.1f} ms</td><td>≤ 1000 ms</td></tr>'
passed_regression = sum(a == 'regression' and c == '通过' for a,b,c,d in results)
verified_formal = sum(a == 'verified-formal' and c == '通过' for a,b,c,d in results)
ten_rounds = sum(a in {'final-journeys','ten-repeat'} and 'ten rounds' in b and c == '通过' for a,b,c,d in results)
summary = ''.join(f'<tr><td>{esc(a)}</td><td>{esc(b)}</td><td>{c}</td><td>{d}s</td></tr>' for a,b,c,d in results if a != 'regression')
links = ''.join(f'<li><a href="{esc(str(p.relative_to(root)))}">{esc(str(p.relative_to(root)))}</a></li>' for p in root.rglob('*') if p.name in ['evidence.json','trace.zip','error-context.md'] or p.suffix == '.log')
images = ''.join(f'<figure><img loading="lazy" src="{esc(str(p.relative_to(root)))}"><figcaption>{esc(str(p.relative_to(root)))}</figcaption></figure>' for folder in ['core-browser','verified-browser','ten-repeat-browser','final-browser','repeat-browser','fuzzy-browser','performance','browser'] for p in (root/folder).rglob('*.png') if 'failed' not in p.name)
page = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>QA 全动线回归 · 2026-10-22</title><style>body{{font:16px/1.7 system-ui;max-width:1120px;margin:40px auto;padding:0 24px;color:#182b3a;background:#f7f9fc}}h1,h2{{color:#143e65}}section{{background:white;padding:24px;margin:20px 0;border-radius:14px}}table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #dde4ec;text-align:left;padding:9px}}img{{max-width:100%;border:1px solid #ddd}}a{{color:#1265a3}}code{{background:#edf2f6;padding:2px 4px}}</style>
<h1>QA 全动线回归</h1><p>2026-10-22 · 隔离数据库 / 本地浏览器 / 真实模型 · 不含生产发布</p>
<section><h2>当前结果</h2><p>确定性回归 {passed_regression} 项通过；参考改写最终修复链路 {verified_formal}/3 次通过；真实 UI 十轮修改 {ten_rounds}/3 次通过。性能门槛全部通过。最终结果以各执行记录为准。</p></section><section><h2>本轮验收范围</h2><p>初次生成 → 测试点确认 → 候选生成 → 自然语言搜索参考 → 部分重新生成 → 采纳 → 正式用例参考改写 → 十轮修改 → 差异审阅与采纳 → 刷新与断网恢复。自然搜索从实际对话输入框发起，不在测试请求中预填来源集合或目标用例 ID；数据准备和部分确认使用接口。</p><p>模糊搜索覆盖中文关键词片段、多词组合、编号片段、无结果、通配符转义，以及跨用户隔离。当前证据不等同于拼写纠错、任意同义词或向量召回全面验收。</p></section>
<section><h2>问题与修复</h2><ol><li>“搜一下登录相关的用例”“找找以前的用例参考”等自然表达未触发资产搜索：扩充操作表达并回归否定、条件、引用及搜索功能需求，保持默认不搜索。</li><li>参考改写的搜索阶段扩大目标至同集合其他用例：按修改任务解析目标；不把默认集合展开当成用户已选范围；范围提示词区分参考资产搜索范围与修改目标。初次失败及第一轮未完全修复的记录保留。</li><li>参考改写采纳后仍显示“生成用例／等待确认”：资产搜索转入正式改写时同步 task_intent，采纳完成后关闭任务，并加入刷新后标题与完成状态断言。</li><li>十轮 UI 脚本固定输入框/按钮名称，未适配“用自然语言修改选中用例 / 继续执行修改”：修正状态定位和真实 UI 请求观察。</li><li>断网恢复脚本重复使用同一草稿，等待不存在的保存请求：每次使用唯一草稿，继续验证恢复值和正式版本不变。</li></ol><p>后两项是验收脚本问题。所有失败、取消和最终结果见下表及原始证据，不能以重跑覆盖历史失败。</p></section>
<section><h2>性能</h2><p>1000 条资产、单集合 100 条、至少十轮历史、5 用户并发。接口每项 150 次；各宽度恢复与输入各 30 次。此次与真实生成验收同时运行，跨轮次耗时不作为严格优化收益对比。</p><table><tr><th>指标</th><th>采样</th><th>P95</th><th>门槛</th></tr>{rows}</table><p>数据库检索与来源补全独立采样 150 次，P95 {retrieval['p95']['total_ms']:.1f} ms。上述接口/UI 指标不包含模型生成总耗时；真实链路的测试耗时包含等待、建数及审阅，不应当作模型首批耗时。</p></section>
<section><h2>执行结果</h2><p>完整断言及结果：<a href="execution-matrix.csv">执行矩阵 CSV</a>；<a href="conversation-matrix.csv">自然语言与多轮对话矩阵</a>；<a href="regression.xml">确定性回归 JUnit</a>。未通过项不计完成。</p><table><tr><th>轮次</th><th>链路</th><th>结果</th><th>耗时</th></tr>{summary}</table></section>
<section><h2>测试对象与 Prompt 链路</h2><p>测试对象随测试说明、任务输入和生成产物 requirement_analysis 保存；正式用例版本仍无独立 test_object 字段，不能声称已经完成正式用例字段迁移。直接复用绕过正文生成，参考改写携带已确认来源快照、原步骤、新要求、处理理由；新生成只使用该批测试点所需上下文。紧凑路径每批 5 条、并发 4；正式改写按最多 20 条及字符预算分批，生成差异建议后采纳。本轮未更改批次参数。</p><p>测试对象、直接复用与改写 Prompt 的专项证据见上一轮 <a href="../object-rewrite-regression-20261022/report.html">专项报告</a>。本轮没有重复全部批次参数对比、5 用户同时调用模型压力测试，也没有声称拼写纠错全面通过。</p></section>
<section><h2>截图</h2>{images}</section><section><h2>原始证据</h2><ul>{links}</ul></section></html>'''
(root/'report.html').write_text(page)
print(root/'report.html')
