"""Evidence ledger for continued QA; never equate fixture design with execution."""
import html,json
from pathlib import Path
from xml.etree import ElementTree
out=Path('output/qa-continuation-20261022');esc=html.escape
parts=['''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>持续验收与修复</title><style>body{font:16px/1.75 system-ui;max-width:1240px;margin:32px auto;padding:0 22px;color:#23364a}h1,h2{color:#173f65}table{width:100%;border-collapse:collapse;margin:16px 0}td,th{border:1px solid #ccd7e2;padding:10px;text-align:left}th{background:#edf3f9}.note{background:#fff3d9;padding:16px}img{max-width:100%;border:1px solid #d8e2ec}details{padding:10px;border:1px solid #ccd7e2;margin:16px 0}a{color:#1263a2}</style><h1>持续验收 · 搜索与多轮工作台</h1><p>2026-10-22 · 隔离测试库 · 无生产发布</p><p>本轮重点：消除管理页全空间加载，验证复杂自然语言和Excel参考改写，补齐真实创建历史下的性能测试，并修复分页与失败重试状态。已覆盖的链路未遗留已知功能阻断；这一结论不等于所有可能的自然语言和业务规则均已证明正确。</p><h2>已修复问题</h2><table><tr><th>问题</th><th>修复与防回归</th></tr><tr><td>选择器打开即加载空间全部用例，搜索由浏览器完成</td><td>服务端搜索，每页最多100条；只为当前页加载正文、来源及创建人。保留多关键词、编号、模块、标签、来源、测试目标、创建人，并新增集合名搜索。按创建时间和ID稳定排序。</td></tr><tr><td>宽泛检索、创建人查询及网络往返在50万条数据下超标</td><td>索引元数据、分页顺序、编号、创建人；预检查只针对当前空间当前版本，合并独立预检查，去掉无用的大规模去重与排序。真实记录超标和失败轮次。</td></tr><tr><td>分页后已选项可能被当作未加载/不可用</td><td>已选用例独立保留；编辑已有清单从其正式快照恢复；按集合完整加入会加载整个明确集合，搜索页不会替代集合完整内容。</td></tr><tr><td>搜索重试成功仍残留旧错误</td><td>局部错误与搜索结果同步清除，失败保留选择；新增503故障注入及重试断言。</td></tr><tr><td>第二页取消后新建，沿用旧页码</td><td>取消/新建时同步清除页码、结果和更多页状态；新增第二页→取消→新建回到100条第一页、零选择断言。</td></tr><tr><td>JSON数组的引号、括号可能被误当标签内容</td><td>特殊字符按实际字段和数组元素匹配；%、_、反斜杠保持字面量。测试目标fr_test中的下划线应真实命中，fr%test不应被当通配符。</td></tr></table><h2>规模性能：服务端检索与展示数据加载</h2><p>5000个有内容集合×100条＝500000条用例，另有1个默认空集合，并补齐500000条创建历史。5并发，每类30次，三轮相同最终检索实现。计时含空间权限检查、SQL搜索和当前页完整视图加载；不含HTTP传输、浏览器及自然语言模型。P95单位毫秒。部分轮次与回归、浏览器检查并行，因此保留各轮波动。</p><table><tr><th>轮次</th><th>查询</th><th>P95 ms</th><th>成功/采样</th><th>结果校验</th></tr>''']
all_ok=True
for repeat in [1,2,3]:
 name=f'management-final-scope-{repeat}.json';path=out/name
 if not path.exists():
  all_ok=False;parts.append(f'<tr><td>{repeat}</td><td colspan="4">未完成</td></tr>');continue
 for row in json.loads(path.read_text()):
  samples=row['samples'];expected=1 if row['query']=='唯一质量锚点05000' else 100
  success=sum('error' not in sample for sample in samples)
  correct=all('error' not in sample and sample['count']==expected and len(set(sample['ids']))==expected and sample['ids']==samples[0].get('ids') for sample in samples)
  all_ok=all_ok and correct and row['p95_ms']<=2000 and len(samples)==30
  parts.append(f'<tr><td><a href="{name}">{repeat}</a></td><td>{esc(row["query"] or "首屏空查询")}</td><td>{row["p95_ms"]:.2f}</td><td>{success}/{len(samples)}</td><td>{"数量、去重、稳定顺序通过" if correct else "未通过"}</td></tr>')
parts.append('</table><p>最终规模性能门槛：'+('通过，450次采样均无错误。' if all_ok else '尚未全部通过，请检查表格及原始数据。')+'</p>')
parts.append('''<p class="note">保留的中间问题：仅移入SQL仍约2秒；不合适的全量子查询曾触发8秒超时；加入创建历史后有2.07秒、2.40秒P95。后续改动有对应索引、查询计划和重复采样依据，没有通过缩小空间范围、减少返回字段或删除失败样本来达标。历史中间日志和JSON均列在下方。</p><h2>功能与浏览器验收</h2><ul><li>真实服务：Excel上传→自然语言搜索参考→只确认OLD-001→候选局部改写→审阅采纳→刷新。保留当前300秒规则、排除旧420秒及未选行，未改动其他候选。</li><li>真实服务：关键词片段、多个词、空结果、字面量百分号、空间隔离及页面搜索。</li><li>真实服务：十轮修改保留范围和有效约束，正式用例只在审阅采纳后变更。</li><li>真实服务：断网刷新后恢复草稿、来源和正式版本。</li><li>真实服务：110条用例两页选择、切换搜索、503重试、保存重开、完整加入、翻页取消后新建。1440／1280／1024宽度截图和无横向溢出断言。</li><li>模拟状态UI（不冒充真实模型）：空资产、局部范围、正式修改、100条资产滚动及键盘操作；select与select_and_generate均先确认后继续。</li></ul><table><tr><th>执行记录</th><th>结果</th></tr>''')
for name in ['regression-release-check.log','browser-final.log','ui-final.log','paging-complete.log','build-reset.log','typescript-reset.log']:
 text=(out/name).read_text() if (out/name).exists() else ''
 summaries=[line.strip() for line in text.splitlines() if (' passed' in line or ' failed' in line or 'Build complete' in line)]
 summary='；'.join(summaries[-2:]) if summaries else ('通过，无诊断' if name=='typescript-reset.log' and (out/name).exists() and not text.strip() else '查看原始记录/执行中')
 parts.append(f'<tr><td><a href="{name}">{name}</a></td><td>{esc(summary)}</td></tr>')
parts.append('''</table><h2>Prompt、质量与性能边界</h2><p>本轮没有更换生成模型、降低依据核对强度或更改分批参数。保留上轮直接复用绕过正文生成、参考改写仅使用已确认来源、有效多轮约束、测试对象持续传递、失败批次保留成功项等回归。实际Excel与十轮动线再次经过真实模型。</p><p>上轮针对附加预期的依据核对由质量模型执行，12条混合用例实测总耗时50—128秒。本轮未宣称这部分耗时已降低；模型阶段独立于普通搜索接口指标，不能以删除审核或弱化断言换取“达标”。<a href="../qa-fixes-20261022/report.html">上轮质量、Prompt及错误回放证据</a>。</p><h2>验收边界与失败记录</h2><ul><li>156条语料中8组×10轮完整组合仍未全部逐句端到端执行；本轮通过的真实链路和模拟状态分别列出，不将语料设计数量算作执行通过数量。</li><li>初次回归时隔离Redis未启动，3项取消流程失败；浏览器初次构建指向默认API，已改为隔离8018并重新构建验证。保留原始失败日志。</li><li>两处测试夹具预期修正：随机用例编号也可能匹配独立数字词；引入fr_test目标后“_”是实际存在的字符。已采用明确唯一标题，并断言百分号不是通配符。</li><li>新增迁移0032—0035只在隔离库验证；测试数据留存以便重复验收。没有生产发布。</li></ul><p><a href="../qa-natural-language-20261022/report.html">复杂自然语言验收集合</a> · <a href="../qa-fixes-20261022/report.html">前轮修复与原始问题</a></p><h2>原始证据</h2><ul>''')
for f in sorted(out.iterdir()):
 if f.suffix in {'.log','.json','.xml','.txt'}:parts.append(f'<li><a href="{esc(f.name)}">{esc(f.name)}</a></li>')
parts.append('</ul><h2>截图</h2>')
for f in sorted((out/'paging-complete').glob('*/selected-*.png'))+sorted((out/'browser-final').glob('*/completed.png'))+sorted((out/'browser-final').glob('*/restored.png')):
 rel=esc(str(f.relative_to(out)));parts.append(f'<details><summary>{rel}</summary><img src="{rel}" alt="验收界面截图"></details>')
parts.append('</html>');(out/'report.html').write_text(''.join(parts));print('report:',out/'report.html','scale_passed:',all_ok)
