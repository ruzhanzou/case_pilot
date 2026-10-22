import html,json,math
from pathlib import Path
p=Path('output/deep-quality-20261022');e=html.escape
parts=['<!doctype html><meta charset="utf-8"><title>深度验收 · 5000 个用例集</title><style>body{font:16px/1.65 system-ui;max-width:1160px;margin:40px auto;padding:0 24px;color:#172435}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccd5df;padding:8px;text-align:left}h1,h2{color:#123d63}.fail{color:#ab2525}pre{white-space:pre-wrap}details{margin:12px 0}</style><h1>深度验收 · 2026-10-22</h1><p class="fail">结论：未全部通过，不计为全链路验收完成。已完成实现修复与针对性回归；未发布生产。</p><p>按用户“3000–5000”理解为用例集数量；隔离库包含 5000 个有数据的集合 × 100 条 = 50 万条用例，另有 1 个空默认集合。数据为合成登录场景，不能代表所有真实数据分布。</p>']
parts += ['<h2>已修复与验证</h2><ul><li>集合名称命中但用例正文不含关键词时，检索原本返回 0；现可返回该集合的 100 条用例。</li><li>检索先排序标识再加载正文；增加持久化搜索文本与索引。匹配数、实际返回数和截断状态传给工作区，不能把前 100 条当作全部资产。</li><li>Excel 参考进入用户确认范围；校验对象、文档版本、校验和、归属及有效期。select 仍只选正式资产。</li><li>Excel 来源保留原编号、文件名、工作表行定位及版本，避免显示为用例管理或 null。</li><li>规划返回空模块时使用已有功能点名称作为分组，修复工作区读取 500。</li><li>生成提示词 v9 强化测试点断言；正文遗漏明确时长时只修复相应条目，允许秒和分钟等价换算。</li></ul><p>确定性回归：516 通过；TypeScript 检查、构建及差异空白检查通过。真实模型与浏览器结果单列如下。</p>']
parts.append('<h2>搜索性能：5 并发，每类 30 次</h2><p>指标只包括数据库检索及来源集合装配，不包括自然语言理解、对象匹配、模型决策、HTTP 或浏览器。成功请求单独计算 P95；失败不能视为快速响应。</p><table><tr><th>版本 / 集合数</th><th>查询</th><th>成功数</th><th>成功 P95 毫秒</th><th>首个成功返回条数</th></tr>')
for name in ['before','after','after-branches','stored','stored-serial','metrics-serial']:
 f=p/f'scale-{name}.json'
 if not f.exists():continue
 for r in json.loads(f.read_text()):
  ok=[x for x in r['samples'] if 'error' not in x];times=sorted(x['ms'] for x in ok);v=round(times[math.ceil(len(times)*.95)-1],1) if times else '—'
  parts.append(f'<tr><td>{name} / {r["collections"]}</td><td>{r["query"]}</td><td>{len(ok)}/30</td><td>{v}</td><td>{ok[0]["returned_cases"] if ok else "—"}</td></tr>')
parts.append('</table><p class="fail">5000 集合宽泛查询未达到 P95 ≤ 2 秒：默认并行查询出现共享内存不足（stored 轮 28/30 失败）；仅在基准事务中禁用查询内部并行后 30/30 成功，但 P95 约 3.49 秒。该实验设置未作为产品全局配置。具体词约 251ms，集合名约 136ms。包含实际搜索统计字段后的复测（metrics-serial）：宽泛查询 P95 4266ms、具体词 222ms、集合名 90ms，三类均 30/30 成功；宽泛查询仍不达标。旧基线部分错误只记录类型，不能断言全部原因相同。</p><p>管理端 search_space_test_cases 仍全量加载空间用例后过滤，50 万条规模尚未验证，也未算通过。需独立做分页及服务端查询，避免把本次对话检索指标套用于管理端。</p>')
runs=json.loads((p/'quality-verified.json').read_text())
parts.append('<h2>真实模型质量：12 个测试点 × 3 轮</h2><p>固定 300 秒过期、第四次错误锁定 1140 秒、边界、计数重置、账号隔离及停用规则；每轮 1 条直接复用、1 条改写、10 条新增。直接复用跳过正文生成，余项按槽位分批，实际每轮 3 次模型请求。记录完整输入、输出与 usage。</p><p class="fail">结构/规则自动断言三轮通过；人工复核发现第 2 轮停用账号新增了“错误次数不增加”的无依据预期，因此内容质量仍未全部通过。时长校验只保护显式数值时长，不能替代语义依据核验。</p>')
for run in runs:
 parts.append(f'<details><summary>第 {run["repeat"]+1} 轮 · {run["seconds"]:.2f}s · {len(run["calls"])} 次请求</summary><table><tr><th>编号</th><th>前置</th><th>操作 / 预期</th></tr>')
 for c in run['result']['test_cases']:
  steps='\n'.join(s['action']+' → '+s['expected'] for s in c['steps'])
  parts.append(f'<tr><td>{e(c["id"])}</td><td>{e("；".join(c["preconditions"]))}</td><td>{e(steps)}</td></tr>')
 parts.append('</table></details>')
log=(p/'excel-provenance.log').read_text() if (p/'excel-provenance.log').exists() else ''
status='通过' if '1 passed' in log else '未通过' if '1 failed' in log else '执行中'
parts.append(f'<h2>浏览器 Excel 多轮链路：{status}</h2><p>默认生成 → 候选生成后上传真实 XLSX → 自然语言查找参考 → 排除不同对象及不完整行 → 用户确认 OLD-001 → 仅改选中候选步骤（420 秒改为当前 300 秒）→ 差异采纳 → 保留另一候选 → 刷新检查文件来源。正式用例数量保持 0，不修改来源。</p><p>先前失败均保留：上传控件未就绪的脚本问题、Excel 来源显示问题、空模块导致工作区 500。最终结果以 excel-provenance.log 和执行证据 为准。旧版弱断言曾误报通过，截图复核后补充参考改写及 OLD-001 断言，并保护服务器来源标识不被模型的引用选择覆盖。新 Excel 链路没有重复三次，不作三次稳定性声明。</p>')
parts.append('<h2>证据与未完成范围</h2><ul>')
for name in ['acceptance-matrix.json','scale-metrics-serial.json','regression-latest.log','provenance-regression.log','excel-provenance.log','regression-final.log','regression.xml','quality-real.json','quality-grounded.json','quality-pre-v9.json','quality-prompt-only.json','quality-verified.json','quality-semantic-review.json','scale-before.json','scale-stored.json','scale-stored-serial.json','excel-fixed.log','excel-verified.log','excel-final.log','build-final.log','typescript.log']:
 if (p/name).exists():parts.append(f'<li><a href="{name}">{name}</a></li>')
parts.append('</ul><p>本轮没有重新覆盖所有响应宽度、百条 UI、十轮正式维护、断网及取消恢复组合；此前报告不能替代这轮完整重跑。额外审查发现：Excel 改写资料仍可能携带整个工作表片段（含未选行），虽有已确认来源清单且本次未生成支付系统规则，模型输入尚未严格裁剪到所选行；此项不算已完成授权范围隔离。未完成：广义搜索达标、管理端大规模检索、无依据预期的语义保护、Excel 三次重复验收。数据库迁移 20261022_0030 仅用于隔离验收库。</p>')
(p/'report.html').write_text(''.join(parts))
