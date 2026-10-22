"""Publish the repair round's evidence without treating partial QA as full acceptance."""
import html
import json
import shutil
from pathlib import Path

out = Path('output/qa-fixes-20261022')
esc = html.escape
parts = ['''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>工作台修复与回归验收</title><style>body{font:16px/1.7 system-ui;max-width:1200px;margin:36px auto;padding:0 24px;color:#203346}table{border-collapse:collapse;width:100%}td,th{padding:10px;border:1px solid #ccd7e0;text-align:left}th{background:#eef4f9}.note{background:#fff3d6;padding:16px}img{max-width:100%}a{color:#165c9c}details{margin:18px 0}</style><h1>工作台修复与回归验收</h1><p>2026-10-22 · 隔离验收库 · 未发布生产</p><p>本轮修复对话资产检索的排序、统计与内存问题，以及生成结果中部分无依据附加断言。确定性回归595项通过；真实浏览器3条动线通过。以下保留性能中间结果与初始失败记录。</p><p class="note">这是本轮修复验收，不代表156条语料及全部多轮组合已完成端到端验收。管理页搜索入口仍需优化；新增模型依据核对有明显耗时成本。</p><h2>问题与修复</h2><ul><li>50万条用例宽泛检索原先需要全量排序和窗口计数；改为精确计数与候选排序分离，满足最高分条件时先取有限候选，保留排序、空间隔离、来源和实际命中数。排除空集合引起的无效聚合分支。</li><li>并发数据库查询耗尽共享内存：只对当前检索限制内部并行工作进程，并设置每算子16MB工作内存；成功或异常均恢复调用方设置，不改全局数据库参数。新增覆盖索引，并刷新统计信息。迁移0031仅应用隔离验收库。</li><li>生成用例可能把“空验证码不计错”误用到“停用账号”：Prompt版本case-batch-v10-extra-assertions，对额外计数、跳转、数值时延断言按需核对当前需求证据。依据不足则改写；失败只重试受影响项，保留成功结果，直接复用绕过正文生成。</li><li>新增边界回归覆盖候选上限0、最高分与部分匹配排序、精确命中数量、数据库异常后事务可用，以及依据核对失败时保留未受影响用例。</li></ul><h2>资产检索性能</h2><p>5000个有内容集合×100条＝500000条用例，另有1个默认空集合。5并发，每种查询每轮30次。时间包含数据库检索、来源集合附加和实际命中统计，不包含自然语言意图识别、模型匹配及浏览器全程。P95单位毫秒；失败样本不能作为达标依据。</p><table><tr><th>轮次</th><th>查询</th><th>P95 ms</th><th>成功/采样</th></tr>''']
for mode in ['metrics-serial','bounded-top','bounded-serial','bounded-mem16','bounded-verified','covering-index','analyzed-index','analyzed-repeat2','analyzed-repeat3']:
    name = f'scale-{mode}.json'
    src = Path('output/deep-quality-20261022') / name
    shutil.copyfile(src, out / name)
    for row in json.loads(src.read_text()):
        samples = row['samples']
        success = sum('error' not in s for s in samples)
        p95 = row.get('p95_ms')
        parts.append(f'<tr><td><a href="{name}">{mode}</a></td><td>{esc(row["query"])}</td><td>{p95:.2f}</td><td>{success}/{len(samples)}</td></tr>' if p95 is not None else f'<tr><td>{mode}</td><td>{esc(row["query"])}</td><td>无有效值</td><td>{success}/{len(samples)}</td></tr>')
parts.append('''</table><p>最终三轮共270次均成功，宽泛检索P95为1575／1727／1859ms。宽泛命中500000条、返回100条，截断状态和来源正确。未改变搜索范围或依赖缓存。索引单独加入时仍有2035ms结果，更新统计信息后重复验证达标；不将中间失败隐藏。此为合成数据上的检索核心基线，不外推生产容量、冷缓存或整个对话请求SLA。</p><h2>真实模型生成质量与成本</h2><p>固定12个测试点：1条直接复用、1条旧规则改写、10条新增；检查300秒过期、1140秒解锁、错误次数、账号隔离与停用规则。每轮3次正文生成＋1次针对性依据核对。直接复用首条几乎立即可见。</p><table><tr><th>轮次</th><th>结果</th><th>总耗时s</th><th>首个非复用结果s</th><th>记录调用数</th></tr>''')
for row in json.loads((out/'quality-verified.json').read_text()):
    first = next(p['seconds'] for p in row['previews'] if p['count'] > 1)
    parts.append(f'<tr><td>{row["repeat"]+1}</td><td>{"通过" if row["passed"] else "失败"}</td><td>{row["seconds"]:.2f}</td><td>{first:.2f}</td><td>{len(row["calls"])}</td></tr>')
parts.append('''</table><p class="note">质量成本：本轮12条用例总耗时50—128秒，依据核对增加了一次模型请求，尚不能认为生成性能已优化完成。未为速度降低覆盖或移除必要原步骤。检查是有针对性的保护，不能保证识别全部无依据断言；业务预期仍需人工审阅。</p><h2>原始错误回放</h2><p>冻结上轮实际错误正文，仅依据核对阶段调用真实模型，不能算作三次真实正文生成。三次均把停用账号用例中无依据的“不增加错误次数”等附加断言移除，保留E403及拒绝登录。</p><table><tr><th>轮次</th><th>结果</th><th>耗时s</th></tr>''')
for row in json.loads((out/'quality-replay.json').read_text()):
    parts.append(f'<tr><td>{row["repeat"]+1}</td><td>{"通过" if row["passed"] else "失败"}</td><td>{row["seconds"]:.2f}</td></tr>')
parts.append('''</table><h2>接口、状态与浏览器回归</h2><ul><li>确定性回归最终595项通过。首次594通过、1失败：SQL检查仍假定最后一条查询承担检索，修正测试检查全部实际查询后通过，初始记录保留。</li><li>候选生成后自然语言引入资产→确认→局部修改：通过。</li><li>正式用例阶段参考资产→变更建议→审阅采纳：通过，来源资产与未选用例保留。</li><li>12轮连续补充、否定、纠正→审阅→采纳→刷新恢复：通过。</li><li>本轮未修改前端组件，未重新执行前端构建；以上浏览器使用已有构建连接本轮后端。</li></ul><h2>尚未完成</h2><ul><li>管理页search_space_test_cases仍加载空间全部用例后过滤，应另做服务端分页及过滤，并同步检查调用页面。</li><li>8组×10轮语料尚未全部逐句跑完；本轮3条核心动线不能替代完整矩阵。</li><li>完整自然语言搜索时延、模型依据核对成本及其他复杂业务规则质量仍需持续验收。</li></ul><p><a href="../qa-natural-language-20261022/report.html">156条自然语言验收集合及前轮记录</a> · <a href="../deep-quality-20261022/report.html">原始质量与规模基线</a></p><h2>执行证据</h2><ul>''')
for f in sorted(out.iterdir()):
    if f.suffix in {'.json','.xml','.log','.txt'}:
        parts.append(f'<li><a href="{esc(f.name)}">{esc(f.name)}</a></li>')
parts.append('</ul><h2>界面证据</h2>')
for f in sorted((out/'browser').glob('*/result.png')) + sorted((out/'browser').glob('*/ten-round-result.png')):
    rel = esc(str(f.relative_to(out)))
    parts.append(f'<details open><summary>{rel}</summary><img alt="验收工作台结果" src="{rel}"></details>')
parts.append('</html>')
(out/'report.html').write_text(''.join(parts))
print(out/'report.html')
