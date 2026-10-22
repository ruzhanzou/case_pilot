"""Build a local evidence index. Pending checks never count as passed."""
import html
import json
from pathlib import Path
from statistics import median
import xml.etree.ElementTree as ET
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'output/journey-acceptance-20261021'

def read(name):
    path = OUT / name
    return json.loads(path.read_text()) if path.exists() else {}

def suite(name):
    path = OUT / name
    if not path.exists(): return {'status': 'pending', 'tests': 0}
    cases = list(ET.parse(path).iter('testcase'))
    failed = [c.attrib.get('name') for c in cases if c.find('failure') is not None or c.find('error') is not None]
    skipped = sum(c.find('skipped') is not None for c in cases)
    return {'status': 'failed' if failed else 'passed', 'tests': len(cases), 'skipped': skipped, 'failures': failed}

suites = {n:suite(n) for n in ['regression-v7.xml','data-protection-passed.xml','core-verified.xml','tenround-verified.xml','stage-transitions-final.xml','ui-confirmation-final.xml','performance-final.xml','network-recovery.xml','rate-limit.xml']}
rows=[]
def add(feature, stage, utterance, scope, decision, expected, evidence):
    status=suites.get(evidence,{}).get('status','pending')
    rows.append(dict(id=f'J-{len(rows)+1:03}',requirement_id=f'R-{feature}',feature=feature,stage=stage,user_utterance=utterance,scope=scope,model_decision=decision,expected=expected,status=status,evidence=evidence))
unit='regression-v7.xml';core='core-verified.xml';guard='data-protection-passed.xml';stage='stage-transitions-final.xml'
for phrase,result in [('生成登录用例','默认生成，不搜索'),('不复用历史，生成两条','否定复用，不搜索'),('select和select_and_generate有什么区别？','咨询，不搜索'),('如果以后复用历史用例会怎样','条件表达，不搜索'),('需求示例：“参考已有资产”','引用，不搜索'),('复用已有会话继续访问','业务要求，不搜索'),('找已有的用例参考一下','明确请求，搜索并确认'),('参照已有资产改写步骤','明确参考改写请求'),('选择现有用例组成新集合','select：只选资产'),('找已有的，缺少的补齐','select_and_generate')]:
 add('意图识别','需求输入',phrase,'当前任务','由授权范围约束',result,unit)
for phrase,outcome in [('确认复用','确认所有当前展示资产'),('只用第一条','仅首条'),('这两条直接用','仅当展示恰好两条时确认'),('不复用继续生成','拒绝资产'),('用第99条','无效范围，不猜测')]:
 add('确认','待确认',phrase,'当前展示资产','尚未决策',outcome,unit)
for phrase,decision,outcome in [('已有用例规则全部适用','reuse','保留正文、来源身份，不调用正文模型'),('错误密码提示从密码错误改为凭据无效','modify','基于来源与新规则改写，保留出处'),('补齐退出后会话失效','new','无合适资产，依据需求新增')]:
 add('混合决策','确认后规划',phrase,'已确认同对象资产',decision,outcome,core)
for label,outcome in [('不同测试对象','排除'),('未知测试对象','排除'),('模型虚构来源标识','拒绝非法决策'),('来源正文过长','不因裁剪将不确定来源直接复用'),('用户未确认来源','不能越过确认进行生成')]:
 add('模型边界','对象匹配/决策',label,'候选资产','same/different/unknown',outcome,unit)
for label in ['多集合选择后新集合展示来源','确认combined不提前加入原用例','直接复用采纳后仍为原用例身份','改写用例不会修改来源','刷新重进保持来源']:
 add('来源追溯','生成/采纳',label,'当前集合','reuse/modify/new',label,core)
add('来源追溯','共享工作区','成员重新进入集合','共享集合','reuse','可查看来源，不能读取其他成员私有对话',unit)
add('阶段衔接','候选生成后','找已有用例参考，仅重新生成确认的测试点','勾选测试点','模型逐点选择','保留未选点候选和原测试点身份',stage)
add('阶段衔接','正式维护','参考原资产改写这条步骤，其他保持不变','指定正式用例','modify','来源确认→目标确认→建议→审阅采纳；来源和兄弟用例不变',stage)
add('局部生成','部分采纳','只重新生成这一点，其他保持','单测试点','new','生成、局部重生成、部分采纳、正式修改完整链路三次',core)
add('多轮修改','正式维护','补充→否定→纠正→改目标→再次确认','十轮上下文','局部修改','十轮约束和未选用例保留，三次真实模型执行','tenround-verified.xml')
for label in ['来源版本已更新','来源已删除','确认版本过期','重复/并发确认','直接复用不误报重复','同一来源不能重复采纳']:
 add('数据保护','确认/采纳',label,'来源/候选','拒绝非法状态',label+'应有确定性断言',unit)
for label in ['跨用户读取或取消任务','取消后任务组解锁','旧UI自动保存晚到','旧worker上下文晚到','并发采纳重查状态']:
 add('并发保护','运行中',label,'当前任务','保留新状态','不能覆盖新任务或越权',guard)
for label in ['不足一批/恰好一批/跨批/百条','批次乱序完成','局部格式错误只修复失败槽位','断连重试不重复','持续错误有重试上限','取消后禁止晚到保存','跨批重复保留覆盖归属','完整输入保留有效多轮纠正','旧提示词契约与compact一致']:
 add('分批生成','正文生成',label,'当前批次','new/modify','稳定编号、覆盖、约束和完成结果',unit)
for label in ['确认前无规划执行','多选资产在对话区确认','撤销旧复用选择继续生成','多集合来源在确认卡片显示']:
 add('交互','对话/工作区',label,'当前选择','待确认','确认状态与请求范围一致','ui-confirmation-final.xml')
for label in ['1440宽度','1280宽度','1024宽度','1000资产/100用例/十轮历史/五用户','提交反馈30次']:
 add('性能与布局','工作区',label,'固定数据','不适用','接口P95≤2秒；恢复≤3秒；交互≤200ms；提交≤1秒','performance-final.xml')
add('网络恢复','工作区','断网刷新后恢复','已保存输入与百条用例','不适用','恢复草稿、来源和正式版本，无重复写入','network-recovery.xml')
add('批间参数','分批生成','slot=91对应业务端点/report/90','当前测试点','new','不能顺延为/report/91，状态码缺失也只重试对应槽位',unit)
add('限流恢复','分批生成','已完成首批后第二批返回429','失败批次','new','只重试失败批次，成功项保持且无重复','rate-limit.xml')
(OUT/'acceptance-cases.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
bench=read('batch-validation-final.json');perf=read('performance-final/results.json')
fixes=[
 ('意图误触发','“不复用历史”原先被误判成资产搜索','收紧否定、咨询、引用和业务对象边界，补充原话回归'),
 ('提前混入原资产','combined确认后原用例即加入目标集合，规则改写会保留错误旧条目','确认仅授权范围，待逐点决策和采纳再加入'),
 ('后期复用重启流程','搜索清空候选并重新规划','保存基础规划，明确影响点，只替换所选点候选'),
 ('正式维护错误入口','参考改写可能进入新集合生成','资产确认后衔接既有修改预览、差异审阅和采纳'),
 ('来源不持久/误标','共享工作区看不到来源，人工创建误标全新生成','持久化来源快照、共享集合投影、正确显示人工与未知来源'),
 ('直接复用误报重复','确认过的直接复用被资产去重检查警告','仅对同对象、确认过且内容完全一致的直接复用豁免'),
 ('批间参数错配','slot位置被误当业务编号，/report/90生成/report/91','移除无关全局场景列表；明确slot身份；校验点对应端点与状态码，仅修复失败槽位'),
 ('Prompt契约冲突','旧运行时技能要求四段字段和逐步配对，compact要求slot/preconditions/steps','统一当前阶段schema优先；版本case-batch-v7-scoped-reuse；保留独立动作与断言'),
 ('长列表交互','来源列表反复渲染全部100条','来源memo与25条分页，保留键盘按钮和滚动区域'),
 ('运行中调整','尚未生成测试说明时转资产搜索被错误要求新建集合','允许同任务继续，记录前序任务，取消旧任务后再启动'),
 ('批次性能','默认5条/并发2','九组合筛选及三次复测后选择5条/并发4；不削减覆盖及来源')]
limits=[
 '验收使用隔离的本地数据库、真实已配置模型和生产前端构建；未做生产发布。',
 '五用户并发覆盖普通列表、历史、资产检索；模型矩阵为同一模型的固定数据测试，不等同于五路同时生成的容量测试。',
 'compact执行本地结构与覆盖校验，并明确要求人工审阅业务预期；实测结果另外检查固定端点、状态码与测试点完整性，没有宣称自动证明全部业务语义正确。',
 '已新增预览/最终写入和资产质量检查计时；写入计时不包含事务提交。浏览器渲染仍以恢复和交互端到端时间衡量。',
 '已完成浏览器断网刷新恢复；真实供应商限流及任意阶段复杂指代组合未穷举，限流/断连/取消/晚到/重试另有确定性故障注入覆盖。',
]
summary=dict(suites=suites,case_count=len(rows),fixes=fixes,limitations=limits)
(OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
e=html.escape
def table(headers,data):return '<table><thead><tr>'+''.join('<th>'+e(str(x))+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+e(str(x))+'</td>' for x in row)+'</tr>' for row in data)+'</tbody></table>'
content='<h1>用例生成全动线验收</h1><p>2026-10-21 · 隔离本地环境 · 模型 doubao-seed-2.0-lite · 不含生产发布</p>'
content+='<h2>执行结果</h2>'+table(['证据','状态','用例数','失败'],[(k,v['status'],v['tests'],v.get('failures',[])) for k,v in suites.items()])
content+='<p>原始失败记录保留：multiround.xml（否定意图缺陷）、real-mixed.xml（连接中断/环境竞争）、performance/results.json（开发构建与录制下的慢响应）、regression-final/verified.xml（测试收集及async配置）、data-protection.xml（Redis环境配置）。stage-transitions.xml保留一次生成基础校验失败；redirection-and-metrics.xml保留运行中调整缺陷；ui-confirmation.xml保留旧断言未包含新增范围字段的失败。最终通过结果使用单独文件，不覆盖失败证据。</p>'
content+='<h2>动线与修复</h2>'+table(['问题','原行为','修复'],fixes)
content+='<h2>Prompt review</h2><p>主工作区确认入口显式使用 case_batch_v2；legacy 规划生成路径仍存在，最多20条且独立来源核对，作为独立基线，不把其参数误当工作区参数。<a href="prompt-capture.json">完整SDK系统与用户请求</a>由替换传输层捕获；性能基线使用真实传输。每批保留当前需求、去重后的用户约束、相关证据、当前测试点、改写来源原文与变化理由。直接复用绕过正文生成，系统回填身份与来源。exact重复可去除，语义不同的纠正不截断。</p>'
content+='<h2>分批真实模型对比</h2>'+table(['记录','批大小','并发','数量','总秒','首批秒','请求数','输入token','输出token','重试','校验问题'],[(r['file'],r['size'],r['concurrency'],r['count'],round(r['seconds'],2),round(r['first_visible_seconds'] or 0,2),r['requests'],r['input_tokens'],r['output_tokens'],r['retries'],r['content_issues']) for r in bench])
v5=[r for r in bench if r['file']=='batch-v7-finalists.json'];a=[r['seconds'] for r in v5 if r['concurrency']==2];b=[r['seconds'] for r in v5 if r['concurrency']==4]
if a and b:content+=f'<p>V7同模型三次复测：并发2中位数 {median(a):.2f}s，并发4中位数 {median(b):.2f}s，下降 {(1-median(b)/median(a))*100:.1f}%。严格检查正文中的端点和状态码，早期四轮存在缺失或批间错配（含中文路径提取修复前的一轮V7），已单独标记不合格；不以source_refs中的需求原文充当正文覆盖。发生过模型格式错误的轮次及重试保留在原始JSON；最终版本的错误、覆盖与重试以逐轮表格为准。</p>'
legacy=read('batch-legacy-baseline.json')
if legacy.get('runs'):
 lr=legacy['runs'][0];content+=f'<p>旧路径独立基线：20条/串行，{lr["seconds"]:.2f}秒，{len(lr["calls"])}次模型调用。包含独立来源核对，不能将时间差全部归因于分批参数。</p>'
metrics=read('stage-metrics.json')
content+='<h2>分阶段指标</h2><p>旧记录的0耗时表示未测量，不按零成本计算。需求总阶段与需求批次是汇总/明细关系，不能重复相加。</p>'+table(['阶段','状态','记录数','有效计时数','平均ms','P95ms','输入token','输出token'],[(r['stage'],r['status'],r['requests'],r['timed_samples'],r['average_ms'],r['p95_ms'],r['input_tokens'],r['output_tokens']) for r in metrics.get('stages',[])])+table(['任务','持久化与质量检查ms'],[(r['job_id'],r['metrics']) for r in metrics.get('persistence',[])])
hundred=next((r for r in bench if r['file']=='batch-v7-hundred-verified.json'),None)
if hundred:content+=f'<p>最终百条：{hundred["count"]}条，{hundred["seconds"]:.2f}秒，首批{hundred["first_visible_seconds"]:.2f}秒，{hundred["retries"]}次局部重试；正文端点、状态码与覆盖检查：{hundred["content_issues"] or "全部通过"}。</p>'
retry=read('failed-job-retry.json')
if retry:content+=f'<p>保留的实际失败任务重试：{retry.get("status")}；未受影响候选逐字段校验：{retry.get("unaffected_verified")}。<a href="failed-job-retry.json">完整重试证据</a></p>'
content+='<h2>普通操作性能</h2><p>每用户每接口30次，五用户并发，共150次；各宽度恢复和输入30次。生产与开发基线的构建、录制及竞争负载不同，不能把全部差值归因于代码优化。</p>'+table(['接口','P95 ms'],[(k,round(v['p95'],1)) for k,v in perf.get('api',{}).items()])+table(['宽度','恢复P95 ms','输入P95 ms'],[(k,round(v['recoveryP95'],1),round(v['interactionP95'],1)) for k,v in perf.get('ui',{}).items()])
if perf.get('submission'):content+=f'<p>提交反馈P95 {perf["submission"]["p95"]:.1f}ms（点击后输入清空与乐观回显开始，非模型完成）。</p>'
content+='<h2>截图</h2>'+''.join(f'<figure><img src="performance-final/workspace-{w}.png"/><figcaption>{w}px · 百条工作区</figcaption></figure>' for w in [1440,1280,1024])
content+='<h2>验收集合</h2><p><a href="acceptance-cases.json">下载结构化验收集合</a> · <a href="batch-validation-final.json">批次校验</a> · <a href="stage-metrics.json">真实分阶段调用指标</a></p>'+table(['ID','功能','阶段','原话/场景','范围','决策','预期','状态','证据'],[(r['id'],r['feature'],r['stage'],r['user_utterance'],r['scope'],r['model_decision'],r['expected'],r['status'],r['evidence']) for r in rows])
content+='<h2>未完成/适用边界</h2><ul>'+''.join('<li>'+e(x)+'</li>' for x in limits)+'</ul>'
(OUT/'report.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="UTF-8"><title>用例生成验收</title><style>body{font:15px/1.65 system-ui;margin:40px auto;max-width:1400px;color:#183044;padding:0 24px}table{border-collapse:collapse;width:100%;margin:16px 0;font-size:13px}th,td{border:1px solid #ccd5dd;text-align:left;padding:8px;overflow-wrap:anywhere}th{background:#eaf2f5}h2{margin-top:36px}img{max-width:100%;border:1px solid #ccc}figure{margin:24px 0}a{color:#17629a}</style>'+content+'</html>')
print(json.dumps(suites,ensure_ascii=False));print('Acceptance cases:',len(rows))
