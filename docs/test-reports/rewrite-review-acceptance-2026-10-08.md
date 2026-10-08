# AI 用例工作台修改逻辑修复与验收（2026-10-08）

## 范围

针对本轮 review 的六个问题修复目标解析、改写数据契约、多轮方案继承、明确赋值快捷路径、部分采纳冲突检查和累计结果统计。新增浏览器回归脚本 `apps/web/e2e/rewrite-review-regressions.spec.ts`，保留真实 API、任务队列、模型调用和数据库，不拦截或伪造网络响应。

内容条件超出当前确定性解析能力时，返回澄清，要求先查询/选择具体用例。本次没有把任意自然语言条件自动选例作为已支持能力。

## 当前实现链路

1. 工作台提交自然语言指令及已选用例/候选范围；API 规划操作，再将范围解析为具体引用和版本。复杂内容条件不能确定时要求澄清。
2. 后台按用例逐条改写。完整的明确赋值可走本地快捷路径；包含语义补充时调用模型。生成与修改使用不同的数据限制。
3. 同一任务的多轮结果合并为累计变更集，以正式版本/候选当前版本为基线展示差异；在这一步不覆盖正式用例。
4. 用户采纳后，API 只校验并写入实际接受的条目和字段。正式用例产生新版本；候选修改先保存到候选，最终“纳入”才进入正式集合。
5. 同一句话可能被规划成多个有依赖的操作；前一方案审阅后启动下一项。浏览器验收等待真实后台完成，并逐项审阅后检查最终状态。

## 修复与证据

| 编号 | 修复行为 | 真实端到端检查 | 结果 |
| --- | --- | --- | --- |
| R1 | 内容条件不能只取模块而丢掉其他限制；检查原始消息与模型提取范围 | “登录模块中涉及短信验证码的用例”不创建改写任务或变更集，两条正式用例不变 | 通过 |
| R2 | 改写独立使用现有资产契约：允许空前置条件和最多 100 步；新生成用例保留原限制 | 5 步、空前置条件用例改标题并采纳，步骤和其他用例不变，仅目标版本增加 1 | 通过 |
| R3 | 澄清/失败后沿操作来源回溯有效方案；已应用、已拒绝或冲突方案不能被复活 | 改标题→不存在模块触发澄清→改优先级→采纳，标题与优先级累计保存 | 通过 |
| R4 | 快捷路径仅接受完整的明确赋值；剩余语义指令交给模型 | 改标题并补充断网重试验证，标题与操作步骤均改变并正确保存 | 通过 |
| R5 | 仅对实际接受了有效字段的条目执行版本校验 | A、B 批量建议生成后手动改 B，取消勾选 B，仅应用 A；A 保存，B 的人工版本不变 | 通过 |
| R6 | 先合并累计方案，再计算任务输出、消息、无变更标志和待确认状态 | A 有待审阅改动，B 本轮无需改动；方案与任务均保留两条，任务仍待确认，A 可采纳，B 不新增版本 | 通过 |

最终代码的六项真实模型浏览器验收：**6/6 通过，耗时 5.2 分钟**。此前首轮六项通过后，在候选补验中继续发现并修复了下述两个问题，再完整重跑六项。

R3 的后台失败分支、已审阅边界和生成/查询结果来源保留另外由回归测试验证；浏览器场景使用真实的目标澄清中间轮次。

## 自动化验证

- Python 单元及数据库集成回归：**294/294 通过**，结果见 [执行日志](../../output/rewrite-review-final/python-tests.txt)。
- TypeScript 类型检查通过。
- 新增及本次修改的浏览器脚本 ESLint 通过。
- 本次修改行 Ruff 检查 0 问题；仓库存量文件仍有原有格式问题，未将整仓 Ruff 声称为通过。
- `git diff --check` 通过。

## 补验发现的额外问题

逐条后台改写沿用整段批量指令时，真实模型曾返回两条用例的数组，违反单条 `RewriteCandidate` 契约。补充了单条改写的系统约束，明确数量范围已经由服务端处理、`proposed` 必须为一个对象、差异不能按用例再次分组；改写阶段不再注入新生成用例的规则，以免把现有长用例重新压缩。SDK 与兼容 provider 使用同一约束，并增加测试。失败尝试及页面重试保留在验收记录中。

页面自动保存草稿和选中项可能将旧的会话上下文写回，覆盖最新任务指针，造成还有待审阅建议却报告没有。API 自动保存与 worker 状态更新改为数据库原子合并；旧指针沿已替代方案追踪到最新方案。新增双数据库会话的并发回归，验证草稿、最新任务指针和 worker 阶段互不覆盖；候选第 7 阶段已在原失败数据上恢复通过。

## 候选用例链路补验

状态：**通过，9 个阶段全部完成**。执行现有 `qa-partial-adoption.spec.ts` 中的完整流程：生成三条→先纳入一条→查询正式用例→剩余候选多轮正文修改→逐条采纳→继续改剩余建议→最终纳入→验证新任务边界。修复后通过页面“重试任务”和重发澄清指令，从原有状态续验；原始失败、澄清及重试保留，最终续验运行 1/1 通过（2.0 分钟），不是把首次失败计为通过。结果记录于 [候选链路记录](../../output/rewrite-review-candidates/partial-adoption-results.json)。

最终三条正式用例与正文可见于 [验收截图](../../output/rewrite-review-candidates/06-final-three-formal-cases.png)，浏览器执行记录见 [最终续验 trace](../../output/rewrite-review-candidate-final/qa-partial-adoption-genera-e00a5--editing-and-final-adoption/trace.zip)。

## 验收环境及限制

- 独立 PostgreSQL 验收库 `casepilot_review_20261008`。
- Redis 分别使用 13/14/15 号库，API 为 `127.0.0.1:8110`，Web 为 `127.0.0.1:13100`。
- 使用本地已配置的真实模型；包括模型意图规划与语义改写。明确赋值符合快捷路径时不必调用改写模型。
- 首轮环境检查发现旧验收 worker 共用任务队列，导致新库任务被旧进程取走。已更换独立队列与 worker 名称，再完整执行六项验收；首轮中断不计入通过结果。
- 复合指令复测曾因模型拆为连续任务而触发测试的 20 秒等待上限；核对 trace 后确认前一项已保存、下一项仍运行。测试改为等待后台完成并审阅所有后续方案，最终整组通过；保留该次 trace 于 `output/rewrite-review-final-six/`。
- 本轮验证覆盖上述修复与候选链路，不代表全产品所有功能已经验收。

## 复现入口

启动连接独立验收库和队列的当前代码 API、worker（包含 outbox 定时派发）及 Web 后执行：

```sh
CASEPILOT_REAL_ACCEPTANCE=1 \
CASEPILOT_E2E_API_URL=http://127.0.0.1:8110 \
CASEPILOT_E2E_BASE_URL=http://127.0.0.1:13100 \
pnpm --dir apps/web exec playwright test e2e/rewrite-review-regressions.spec.ts
```

每个场景使用新的隔离集合，断言审阅前正式资产不变、采纳后目标字段及版本正确、非目标用例不变，并保存截图、浏览器 trace 和 API/落库证据。

## 六项回归的原始证据

- [R5 未选条目的版本冲突：数据](../../output/rewrite-review-final-verified/rewrite-review-regressions-06f98--applying-the-selected-case/evidence.json) · [截图](../../output/rewrite-review-final-verified/rewrite-review-regressions-06f98--applying-the-selected-case/result.png)
- [R1 范围条件保护：数据](../../output/rewrite-review-final-verified/rewrite-review-regressions-36612-cation-to-the-entire-module/evidence.json) · [截图](../../output/rewrite-review-final-verified/rewrite-review-regressions-36612-cation-to-the-entire-module/result.png)
- [R3 澄清后累计修改：数据](../../output/rewrite-review-final-verified/rewrite-review-regressions-512bd-erves-the-previous-proposal/evidence.json) · [截图](../../output/rewrite-review-final-verified/rewrite-review-regressions-512bd-erves-the-previous-proposal/result.png)
- [R2 长用例改写：数据](../../output/rewrite-review-final-verified/rewrite-review-regressions-64720-ps-survive-rewrite-and-save/evidence.json) · [截图](../../output/rewrite-review-final-verified/rewrite-review-regressions-64720-ps-survive-rewrite-and-save/result.png)
- [R4 复合修改指令：数据](../../output/rewrite-review-final-verified/rewrite-review-regressions-7bc62-s-the-semantic-step-rewrite/evidence.json) · [截图](../../output/rewrite-review-final-verified/rewrite-review-regressions-7bc62-s-the-semantic-step-rewrite/result.png)
- [R6 累计方案与状态：数据](../../output/rewrite-review-final-verified/rewrite-review-regressions-d7797--pending-results-and-status/evidence.json) · [截图](../../output/rewrite-review-final-verified/rewrite-review-regressions-d7797--pending-results-and-status/result.png)
