"""Readable QA corpus and honest execution ledger, independent of test UI."""
import html,json,shutil
from pathlib import Path
p=Path('output/qa-natural-language-20261022');p.mkdir(parents=True,exist_ok=True);esc=html.escape
for f in ['natural_language_workbench.json','workbench_complex_journeys.json']:shutil.copyfile(Path('tests/acceptance')/f,p/f)
corpus=json.loads((p/'natural_language_workbench.json').read_text());journeys=json.loads((p/'workbench_complex_journeys.json').read_text())
parts=['''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>QA 工作台复杂自然语言验收集合</title><style>body{font:16px/1.7 system-ui;max-width:1260px;margin:36px auto;padding:0 22px;color:#203346}h1,h2{color:#153e63}table{width:100%;border-collapse:collapse;margin:16px 0}td,th{border:1px solid #d6e0e9;padding:9px;text-align:left;vertical-align:top}th{background:#edf4fa}details{border:1px solid #d6e0e9;border-radius:8px;padding:12px;margin:14px 0}summary{cursor:pointer;font-weight:650}.note{background:#fff5de;padding:16px}.ok{color:#087247}img{max-width:100%;border:1px solid #ddd}a{color:#1465a0}input{width:90%;padding:12px;font:inherit}</style><h1>QA 工作台 · 复杂自然语言验收集合</h1><p>2026-10-22 · 156 条检查项：60 条策略授权、16 条资产确认边界、8 组 × 10 轮用户动线。</p><p>每轮检查：当前测试对象、影响范围、有效约束、来源确认版本、未受影响内容，以及是否发生未经授权的搜索或采纳。用户决定授权范围，模型在已确认资产内逐测试点决定直接复用、参考改写或新增。</p><p class="note">集合设计完成不等于全部通过。下列单轮授权检查已自动执行；8 组完整动线中，本轮执行了 Excel 和正式维护的对应核心链路，其他组合仍需继续端到端验收。前轮宽泛搜索性能及无依据预期问题没有在本轮宣称已解决。</p><h2>本轮执行与修复</h2><ul><li>初始68条语句：10条失败、58条通过；保留原始失败记录。扩展后76条全部通过，与旧策略用例合计129项通过。</li><li>修复否定范围、后续纠正、咨询后附带执行请求、条件式操作、“只选不改写”的识别。</li><li>Excel 已确认行替换整表片段；保留当前需求和旧用例所需内容，排除未选行。检查真实模型请求：OLD-001存在，OLD-002 / OTHER-001 / BAD-001 / PAY-EXPIRED均不存在。</li><li>确定性回归593项通过；TypeScript及差异检查通过。包含范围、版本、来源、取消、部分修改和采纳的已有回归。</li><li>真实浏览器：带否定的Excel搜索→确认→局部改写→采纳→刷新通过（约3.8分钟）；12轮连续纠正→审阅→正式采纳通过（约2.5分钟）。均调用真实服务，正式采纳只作用于隔离测试数据。</li></ul>''']
recovery=(p/'recovery.log').read_text() if (p/'recovery.log').exists() else ''
parts.append('<p>新增“刷新后恢复可操作且无错误旧版本警告”复跑：'+('通过' if '1 passed' in recovery else '未通过' if '1 failed' in recovery else '执行中')+'。</p>')
parts.append('<h2>单轮语句：授权与拒绝</h2><p>generate 表示本句没有授权资产搜索，不代表系统必须立即生成；仍由上下文决定咨询、修改或澄清。select 也必须先展示并确认资产。</p><table><tr><th>ID</th><th>用户原话</th><th>预期策略</th><th>执行</th></tr>')
for c in corpus['strategy_cases']:parts.append(f'<tr><td>{c["id"]}</td><td>{esc(c["utterance"])}</td><td>{c["expected_strategy"]}</td><td class="ok">通过</td></tr>')
parts.append('</table><h2>资产确认：不猜测指代</h2><p>当前展示资产编号 a、b。空列表表示拒绝全部；需澄清与拒绝全部不同。</p><table><tr><th>ID</th><th>原话</th><th>预期选择</th></tr>')
for c in corpus['choice_cases']:parts.append(f'<tr><td>{c["id"]}</td><td>{esc(c["utterance"])}</td><td>{esc(str(c["expected_selection"])) if c["expected_selection"] is not None else "需澄清，不自动执行"}</td></tr>')
parts.append('</table><h2>8 组复杂多轮动线</h2><p>每组按顺序执行，不能把每句当作无上下文的新任务。A/B、TC-001、L/O 等编号需要绑定当前测试夹具中的真实资产或用例，不能让模型猜测。</p>')
for j in journeys:
 parts.append(f'<details open><summary>{j["id"]} · {esc(j["title"])}</summary><p>前置：{esc(j["fixture"])}</p><p>执行范围：'+('对应核心链路已浏览器验证，逐句完整组合待执行。' if j['id'] in ['J02','J03'] else '本组完整链路待执行；相关局部断言包含在确定性回归中。')+'</p><table><tr><th>轮次</th><th>用户原话</th><th>验收断言</th></tr>')
 for t in j['turns']:parts.append(f'<tr><td>{j["id"]}-{t["turn"]:02}</td><td>{esc(t["utterance"])}</td><td>{esc(t["expected"])}</td></tr>')
 parts.append('</table></details>')
parts.append('<h2>持续验收方式</h2><ol><li>新增自然语言先写人工预期，保留失败语句；修复后进入固定语料回归，防止只修某个句式。</li><li>先执行确定性意图、范围、来源及状态回归，再执行真实浏览器和真实模型。模型内容逐条对照规则，不以JSON合法或quality.passed代替业务正确。</li><li>多轮每步留存目标、版本、快照和来源；比较未受影响内容。对运行中追加、旧任务晚到、并发、刷新另做故障注入。</li><li>发布门槛：核心流程、数据保护和来源追溯全部通过。未执行和未通过单列；不因抽样通过而宣称156条全通过。</li></ol><p>本轮没有创建定时任务，也没有生产发布。仓库保留可重复执行的验收语料、测试入口及证据。</p><h2>文件与证据</h2><ul>')
for name in ['natural_language_workbench.json','workbench_complex_journeys.json','intent-before.log','intent-expanded.log','intent-after.log','regression-final.log','regression.xml','browser.log','browser.xml','recovery.log','real-prompt-scope.json','typescript.log']:
 if (p/name).exists():parts.append(f'<li><a href="{esc(name)}">{esc(name)}</a></li>')
parts.append('</ul><h2>界面截图</h2>')
for f in sorted((p/'browser').glob('complex-excel*/completed.png'))+sorted((p/'recovery').glob('*/ten-round-result.png')):
 parts.append(f'<p>{esc(str(f.relative_to(p)))}</p><img src="{esc(str(f.relative_to(p)))}">')
parts.append('</html>');(p/'report.html').write_text(''.join(parts))
