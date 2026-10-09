# CasePilot 自然语言全量验收报告

归档说明：原始截图、视频、请求及执行日志仅保留在本地 `output/`，不随 Git 提交。下文原始证据路径需在验收工作区查看；远端可查看报告及精简矩阵中的结论、断言和执行状态。

本轮围绕生成、修改、重写、审阅、失败恢复、性能及易用性执行真实浏览器、API、模型和数据库链路。验收结论为**不通过**：常用修改与审阅链路已有通过证据，但千条范围识别、工作进程中断恢复和超长正文处理仍存在阻断。80 条是设计集合规模，不能解释成 80 条全部通过。

## 验收范围与证据

以 [80 条自然语言评测设计](../evaluations/casepilot-natural-language-eval-2026-10-09.md) 为范围，每条的断言、历次执行状态及最终判定保存在 [精简验收矩阵](natural-language-acceptance-matrix-2026-10-09.json)。10 条预留同义盲测未执行，不宣称具有盲测泛化结论。

真实服务使用本地生产构建、PostgreSQL、Redis、Celery 和 `ark-code-latest`。新建验收账号及集合隔离正式业务数据。主环境 API 为 8000；独立环境 API 为 8011，使用独立数据库及 Redis 队列。浏览器对独立环境采用真实请求转发，未替换业务响应。脑图的布局回归使用固定模拟数据，真实千条交互另行记录，两种证据不混称端到端。

修复基于提交 `6790ec81`，随本报告一同提交。最终测试过的前端构建已运行于本地 3000 端口，构建摘要一致且页面与 API 就绪检查均为 200，见 交付状态（本地 `output/nl-e2e-fix-20261009/delivery-state.json`）。

部分负载测试与功能回归共享服务及主机。延迟包括此次负载和排队影响，只描述本次运行，不作为空闲环境 SLA。早期在构建期间运行的浏览器用例发生资源加载失败；另有旧按钮定位、遗漏 API 地址和规划任务断言错误。相关原始失败保留，修正脚本后的复测优先，不能将这些失败直接认定为模型语义缺陷。

## 已完成的修复

| 问题 | 修复与边界 | 验证证据 |
| --- | --- | --- |
| 生成用例添加无来源的页面跳转等预期 | 在批次发布前增加独立来源核对；禁止更改用例及测试点身份。新增一次模型调用，会增加生成耗时。 | 生成复测（本地 `output/nl-e2e-fix-20261009/generation-final-results.json`）、来源核对测试（本地 `output/nl-e2e-fix-20261009/agent-tests-grounding.log`） |
| 后续修改把正式 UUID 或 P2 等赋值当作不存在的编号 | 认可真实资产 UUID；错误引用反馈后有界重选，保留未知编号拒绝机制。传输采用请求内短编号及有界区间，仍校验精确成员。 | 多轮复测（本地 `output/nl-e2e-fix-20261009/isolated-full-results.json`）、范围回归（本地 `output/nl-e2e-fix-20261009/router-ranges-tests.log`） |
| 澄清中仍显示旧的改写完成提示 | 根据待处理修改意图抑制过期完成状态，保留上一轮有效建议。 | 多轮及澄清复测（本地 `output/nl-e2e-fix-20261009/isolated-full-results.json`） |
| 集合列表逐项查询导致等待 | 批量读取集合数量、项目、创建者及最新会话上下文。290 个集合仅 7 次查询，结果与旧实现逐项相同。 | 等价性及查询数（本地 `output/nl-e2e-fix-20261009/collections-bulk-comparison.json`）、HTTP 样本（本地 `output/nl-e2e-fix-20261009/collections-http-final.json`） |
| 后台任务更新可能把已保存草稿覆盖为空 | 自动保存仅提交本地实际编辑，迟到响应不清除更新的编辑。 | 见矩阵 REC-07 的最终复测状态 |
| 脑图首次挂载大量不可见节点及展开定位 | 预置节点测量信息避免强制挂载；尺寸变化后重新定位；保留焦点请求直到画布初始化。工作台维护阶段接入行内编辑。 | 见矩阵 PER-04 及脑图回归；不以早期已替换实现的性能样本作为最终结果 |

## 未关闭的问题

| 严重性 | 场景 | 结果及影响 |
| --- | --- | --- |
| P1 | 千条用例范围识别 | 1、25、100 条改写成功；1000 条在短编号及区间优化后仍约 60.85 秒超时，未产生可审阅建议。正式资产未误写。 |
| P1 | 工作进程整体中断 | 25 条任务首批 20 条已保存后强制终止并重启 worker，观察 120 秒仍处于生成中，没有恢复或明确失败。测试随后取消。现有 claim 只接受 queued 状态，不能把重复投递当作运行中任务恢复保证。 |
| P1 | 超长单条正文 | 100 步且每步包含长文本时，只改标题出现 `ModelBehaviorError`。普通长度 100 步标题修改通过，不能代替该长文本验收。 |
| P2 | 重复刷新资源有界性 | 同一任务刷新 20 次后，观测到未结束的 SSE 请求计数由 1 增至 11，堆样本约 13.1MB 至 32.3MB。未重复创建任务，但资源有界断言失败；仍需排除网络事件观测延迟，不能直接断言服务端泄漏。 |
| P2 | 并发可用性 | 五用户各 100 条全部完成且没有结果串入，但建议就绪约 535–1429 秒，采纳约 43–120 秒；功能完成不代表交互性能达标。 |

实际只读角色尚不可建立，SEC-01 记为前提阻塞；越权账号测试不能替代只读角色权限验收。UX-01 需要首次使用者参与并记录误判人数，未用自动化结果替代。其余部分覆盖项的缺口列在逐条矩阵中。

## 性能样本

集合列表优化后的 301 个集合 HTTP 查询为 203、70、58 毫秒。该组为三个样本，数据库等价性测试另覆盖 290 个集合，不能将两个数量视为同一数据集。

最终构建使用同一真实千条集合重复三次：工作台就绪 1254–1392 毫秒，千条列表显示 449–479 毫秒，切换脑图至搜索框可用 412–438 毫秒，输入回显 64–66 毫秒。输入回显不等于目标解析完成；该组没有串接 M01 的 20 条自然语言修改，因此 PER-04 仍为部分覆盖。见 最终千条界面结果（本地 `output/nl-e2e-fix-20261009/capacity-delivery-results.json`）。

五用户各执行一次百条改写，建议就绪总时长的中位数约 964 秒，插值 p95 约 1368 秒。每用户仅一个样本，无法估计有意义的个人 p95；完整各用户时序及采纳时间见 并发结果（本地 `output/nl-e2e-fix-20261009/concurrency/summary.json`）。20、21、100 条生成记录首批、全量完成和稳定批次标识，见 生成容量证据目录（本地 `output/nl-e2e-fix-20261009/generation-capacity`）。

## 验证与重跑

Agent 测试 110 项通过；API 路由与范围测试 87 项通过、1 项需要数据库环境的测试未包含在该命令中；集合批量读取集成测试单独通过。前端生产构建、类型检查及 ESLint 通过。脑图 9 项回归在修复及画布操作定位修正后全部得到通过证据。修改过的 Python 文件静态检查基线有 129 项问题，当前为 102 项，新增行没有诊断；不宣称全仓静态检查通过。

真实用例会调用模型并写入新建的验收集合。执行前启动服务，设置 `CASEPILOT_REAL_ACCEPTANCE=1`、`CASEPILOT_E2E_BASE_URL` 和 `CASEPILOT_E2E_API_URL`，运行 `apps/web/e2e/natural-language-*.spec.ts` 中需要的文件。故障注入脚本只应连接独立环境；不要对主环境启动 worker 中断测试。本轮临时故障服务已停止，独立数据库及证据保留。需要保留本轮完整本地原始证据及 `acceptance-overrides.json`，逐条索引才能通过 `python3 scripts/qa/summarize_natural_language_acceptance.py` 重新生成，不会调用模型或修改应用数据。

<!-- ACCEPTANCE_MATRIX_START -->
## 逐条验收结果

共 80 条：通过 56 条，部分覆盖 18 条，失败 4 条，前提阻塞 2 条。

通过表示本条记录中的自动化断言通过；部分覆盖及前提阻塞均不计为通过。

| 编号 | 场景 | 判定 | 说明与证据 |
| --- | --- | --- | --- |
| NL-GEN-01 | 明确需求生成 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/isolated-evaluation/natural-language-evaluatio-af096-idates-before-incorporation/evidence.json`） |
| NL-GEN-02 | 缺失测试对象 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/generation-final/natural-language-generatio-0ff4b-ation-resumes-original-task/evidence.json`） |
| NL-GEN-03 | 缺少业务阈值 | 部分覆盖 | 两次规划都没有编造具体阈值；一次全部点不可执行，另一次被标为可执行且open_questions为空。具体待确认项的可定位性和最终候选仍需补验。 证据1（本地 `output/nl-e2e-fix-20261009/semantic-final/natural-language-generatio-b861f-fied-thresholds-remain-open/evidence.json`） 证据2（本地 `output/nl-e2e-fix-20261009/isolated-generation/natural-language-generatio-b861f-fied-thresholds-remain-open/evidence.json`） |
| NL-GEN-04 | 矛盾需求 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/isolated-generation/natural-language-generatio-8c390-resholds-require-resolution/evidence.json`） |
| NL-GEN-05 | 生成前修改规划 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/isolated-generation/natural-language-generatio-dc24c-des-obsolete-password-scope/evidence.json`） |
| NL-GEN-06 | 明确数量与测试点 | 通过 | 25个独立测试点生成25条，首批20条与最终25条均保存证据，完整改写与采纳链路通过。 证据1（本地 `output/nl-e2e-fix-20261009/batch-final-results.json`） |
| NL-GEN-07 | 模块增量补写 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/isolated-generation/natural-language-generatio-c01e3-ut-duplicating-normal-login/evidence.json`） |
| NL-GEN-08 | 混合测试维度 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/isolated-generation/natural-language-generatio-75d5e-checks-without-invented-SLA/evidence.json`） |
| NL-GEN-09 | 长需求尾部保真 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/generation-final/natural-language-generatio-cf539-preserves-final-logout-rule/evidence.json`） |
| NL-GEN-10 | 来源冲突与版本 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/generation-final/natural-language-generatio-4b4b9-cludes-historical-threshold/evidence.json`） |
| NL-GEN-11 | 生成同义稳定性 | 通过 | 最终同一环境的3种同义表达均通过，各生成6条并验证相同规则覆盖；不要求逐字相同。 证据1（本地 `output/nl-e2e-fix-20261009/semantic-final/natural-language-generatio-c30ff-araphrase-3-keeps-six-rules/evidence.json`） 证据2（本地 `output/nl-e2e-fix-20261009/semantic-final-results.json`） 证据3（本地 `output/nl-e2e-fix-20261009/paraphrase-semantic-review.json`） |
| NL-GEN-12 | 生成内容注入 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/generation-extra/natural-language-generatio-de3c3--cannot-alter-formal-assets/evidence.json`） |
| NL-SCP-01 | 显式编号覆盖旧选择 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/supplement/NL-SCP-01.json`） |
| NL-SCP-02 | 正文条件查询后续改 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/full-retry/natural-language-full-NL-S-109e1-ody-then-reuse-exact-result/evidence.json`） |
| NL-SCP-03 | 否定优先级条件 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/full/natural-language-full-NL-S-75047-xact-query-and-all-versions/evidence.json`） |
| NL-SCP-04 | 父模块及子模块 | 部分覆盖 | 父子模块目标及正式版本通过；未独立核对脑图和列表的范围展示。 证据1（本地 `output/nl-e2e-fix-20261009/evaluation/natural-language-evaluatio-0214a-e-includes-descendants-only/evidence.json`） 证据2（本地 `output/nl-e2e-fix-20261009/evaluation-results.json`） |
| NL-SCP-05 | 同名模块歧义 | 部分覆盖 | 同名模块会澄清且不修改；澄清后继续指定模块的路径未单独执行。 证据1（本地 `output/nl-e2e-fix-20261009/supplement/NL-SCP-05.json`） |
| NL-SCP-06 | 不存在编号不降级 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/evaluation/natural-language-evaluatio-65a18-uest-cannot-silently-mutate/evidence.json`） |
| NL-SCP-07 | 存在与不存在编号混合 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/evaluation/natural-language-evaluatio-3e837-uest-cannot-silently-mutate/evidence.json`） |
| NL-SCP-08 | 新字段值不是目标 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/full/natural-language-full-NL-S-4437b-vation-and-persisted-reload/evidence.json`） |
| NL-SCP-09 | 排除与保护范围 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/full/natural-language-full-NL-S-f58b4--exclusion-protects-payment/evidence.json`） |
| NL-SCP-10 | 跨集合相同编号隔离 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/isolation/natural-language-isolation-fd615-rized-space-stays-unchanged/evidence.json`） |
| NL-EDT-01 | 只改标题保留长步骤 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/full/natural-language-full-NL-E-994ed-vation-and-persisted-reload/evidence.json`） |
| NL-EDT-02 | 优先级明确赋值 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/full/natural-language-full-NL-E-f3a32-vation-and-persisted-reload/evidence.json`） |
| NL-EDT-03 | 前置条件改写 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/full/natural-language-full-NL-E-83c33-vation-and-persisted-reload/evidence.json`） |
| NL-EDT-04 | 只改指定步骤预期 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/full/natural-language-full-NL-E-15a22--action-expectation-pairing/evidence.json`） |
| NL-EDT-05 | 标题加语义补充 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/full-retry/natural-language-full-NL-E-f682b-tion-and-title-both-persist/evidence.json`） |
| NL-EDT-06 | 步骤重排保持配对 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/full/natural-language-full-NL-E-56dbf--action-expectation-pairing/evidence.json`） |
| NL-EDT-07 | 保留100步历史资产 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/isolated-evaluation/natural-language-evaluatio-be5ab-survives-title-only-rewrite/evidence.json`） |
| NL-EDT-08 | 无实际改动 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/full/natural-language-full-NL-E-97853-t-create-no-formal-revision/evidence.json`） |
| NL-EDT-09 | 非法字段取值 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/evaluation/natural-language-evaluatio-d8631-uest-cannot-silently-mutate/evidence.json`） |
| NL-EDT-10 | 保留文字与特殊字符 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/full/natural-language-full-NL-E-a3b5f-vation-and-persisted-reload/evidence.json`） |
| NL-MUL-01 | 连续两轮累计 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/isolated-full/natural-language-full-NL-M-f3de7-hanges-survive-continuation/evidence.json`） |
| NL-MUL-02 | 澄清轮不丢方案 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/isolated-full/natural-language-full-NL-M-c65ca-des-stale-completion-banner/evidence.json`） |
| NL-MUL-03 | 失败轮恢复方案 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/fault-continuation/NL-MUL-03.json`） |
| NL-MUL-04 | 只重写剩余建议 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/supplement-isolated/NL-MUL-04.json`） |
| NL-MUL-05 | 拒绝内容不复活 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/supplement-isolated/NL-MUL-05.json`） |
| NL-MUL-06 | 候选部分纳入后继续 | 部分覆盖 | 真实12条完整链路验证部分纳入后只修改剩余候选；与设计的3条固定样本数量不同。 证据1（本地 `output/nl-e2e-fix-20261009/full-chain-final-results.json`） 证据2（本地 `output/nl-e2e-fix-20261009/full-chain-final-journal/deep-results.json`） |
| NL-MUL-07 | 候选修改不等于纳入 | 部分覆盖 | 12条链路验证候选修改和纳入分离；未使用指定K1/K2/K3三条基线。 证据1（本地 `output/nl-e2e-fix-20261009/full-chain-final-results.json`） |
| NL-MUL-08 | 多轮覆盖同一字段 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/isolated-correction/natural-language-evaluatio-97812-eplaces-prior-pending-value-repeat2/evidence.json`） |
| NL-MUL-09 | 新会话不继承待审阅方案 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/isolated-isolation/natural-language-isolation-162cb-nherit-old-pending-proposal/evidence.json`） |
| NL-MUL-10 | 本轮无变化保留累计变化 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/full/natural-language-full-NL-M-ba19c-hanges-survive-continuation/evidence.json`） |
| NL-MUL-11 | 不同范围复合操作 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/compound-isolated/NL-MUL-11.json`） |
| NL-MUL-12 | 长对话保留明确约束 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/isolation/natural-language-isolation-3fdb4-teps-and-one-final-revision/evidence.json`） |
| NL-REV-01 | 生成建议前确认 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/full-retry/natural-language-full-NL-R-50fd0-ons-without-formal-mutation/evidence.json`） |
| NL-REV-02 | 逐字段采纳 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/evaluation/natural-language-evaluatio-12c7e-selected-field-is-persisted/evidence.json`） |
| NL-REV-03 | 未选冲突不阻塞 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/supplement/NL-REV-03.json`） |
| NL-REV-04 | 选中条目版本冲突 | 部分覆盖 | 服务端409且人工版本完整保留；冲突页面中的对象说明及重新生成入口尚未完整验收。 证据1（本地 `output/nl-e2e-fix-20261009/full/natural-language-full-NL-R-61a74-nnot-overwrite-manual-edits/evidence.json`） 证据2（本地 `output/nl-e2e-fix-20261009/full-results.json`） |
| NL-REV-05 | 重复采纳幂等 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/full/natural-language-full-NL-R-bec31-not-add-duplicate-revisions/evidence.json`） |
| NL-REV-06 | 拒绝全部修改 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/isolation/natural-language-isolation-f0c35-sets-unchanged-after-reload/evidence.json`） |
| NL-REV-07 | 分批半成品禁止应用 | 通过 | 生成中首批20条无采纳按钮，提前apply为409；最终25条就绪后才可采纳。 证据1（本地 `output/nl-e2e-fix-20261009/batch-final-results.json`） |
| NL-REV-08 | 删除预览与取消 | 部分覆盖 | 取消和再次确认删除已验证；软删除审计记录未单独断言。 证据1（本地 `output/nl-e2e-fix-20261009/supplement/NL-REV-08.json`） |
| NL-REC-01 | 生成中刷新恢复 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/generation-final/natural-language-generatio-5c68a-eneration-restores-same-job/evidence.json`） |
| NL-REC-02 | 改写中切页返回 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/isolated-isolation/natural-language-isolation-6ee01-tores-original-rewrite-task/evidence.json`） |
| NL-REC-03 | 限流后重试 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/faults-v3/NL-REC-03.json`） |
| NL-REC-04 | 模型格式错误 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/faults-v3/NL-REC-04.json`） |
| NL-REC-05 | worker中断续验 | 失败 | 首批20条落盘后杀死并重启worker；120秒内仍生成中，无恢复或明确失败，随后取消验收任务。 证据1（本地 `output/nl-e2e-fix-20261009/worker-interrupt.json`） |
| NL-REC-06 | 取消与迟到响应 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/faults-v3/NL-REC-06.json`） |
| NL-REC-07 | 自动保存与任务更新并发 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/isolated-recovery/natural-language-recovery--a3911-te-survives-task-completion/evidence.json`） |
| NL-REC-08 | 提交响应丢失 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/lost-response-final/natural-language-recovery--d2782-s-discoverable-after-reload/evidence.json`） |
| NL-PER-01 | 首个反馈与排队 | 部分覆盖 | 记录首反馈295.5ms、消息响应22.674s、确认1.199s；后续只读轮询socket hang up中断，后台任务实际完成。未获得完整前端就绪与排队时序及空闲/并发对照。 证据1（本地 `output/nl-e2e-fix-20261009/semantic-final/natural-language-feedback--901e2-mplete-queued-task-timeline/evidence.json`） |
| NL-PER-02 | 首批与全量完成 | 部分覆盖 | 20/21/25/100条的完整生成及尾批均通过；20/21/100保存首批与全量时间和稳定ID，25条浏览器链路未显式记录两项精确时延。 证据1（本地 `output/nl-e2e-fix-20261009/generation-capacity/20.json`） 证据2（本地 `output/nl-e2e-fix-20261009/generation-capacity/21.json`） 证据3（本地 `output/nl-e2e-fix-20261009/generation-capacity/100.json`） 证据4（本地 `output/nl-e2e-fix-20261009/batch-final-results.json`） |
| NL-PER-03 | 批量重写扩展 | 失败 | 1/25/100条通过；1000条范围识别约60.85秒超时，未形成可审阅建议。模型调用数及token未完整采集。 证据1（本地 `output/nl-e2e-fix-20261009/api-capacity-stable/1.json`） 证据2（本地 `output/nl-e2e-fix-20261009/api-capacity-stable/25.json`） 证据3（本地 `output/nl-e2e-fix-20261009/api-capacity-stable/100.json`） 证据4（本地 `output/nl-e2e-fix-20261009/api-capacity-ranges/1000.json`） |
| NL-PER-04 | 千条列表与脑图交互 | 部分覆盖 | 最终构建真实千条集合3次通过：工作台就绪1254-1392ms，列表449-479ms，脑图搜索框可用412-438ms，输入回显64-66ms；尚未串接20条自然语言修改。模拟千条脑图的定位/编辑回归通过。 证据1（本地 `output/nl-e2e-fix-20261009/capacity-delivery-results.json`） 证据2（本地 `output/nl-e2e-fix-20261009/capacity-results.json`） 证据3（本地 `output/nl-e2e-fix-20261009/map-measured-results.json`） 证据4（本地 `output/nl-e2e-fix-20261009/map-recenter-results.json`） 证据5（本地 `output/nl-e2e-fix-20261009/map-pan-final-results.json`） |
| NL-PER-05 | 大方案采纳延迟 | 部分覆盖 | 五用户各100条采纳均恰增一个版本；记录采纳耗时。尚未同场验证百条保存中的按钮防重复和失败提示。 证据1（本地 `output/nl-e2e-fix-20261009/concurrency/summary.json`） 证据2（本地 `output/nl-e2e-fix-20261009/full-results.json`） |
| NL-PER-06 | 并发任务隔离与公平性 | 部分覆盖 | 五用户各100条数据隔离及最终版本通过；每用户仅1次样本，总体分位数仅描述本次运行，不能建立稳定SLA。与其他验收共享服务。 证据1（本地 `output/nl-e2e-fix-20261009/concurrency/summary.json`） |
| NL-PER-07 | 长文本单条成本 | 失败 | 见原始执行结果。 证据1（本地 `output/nl-e2e-fix-20261009/long-text/natural-language-long-text-447a6--steps-preserve-all-content/evidence.json`） |
| NL-PER-08 | 重复进出资源增长 | 失败 | 20次刷新仍只有同一job；未结束的SSE请求计数由1升至11，堆样本约13.1MB到32.3MB，未满足资源有界断言。需区分真实连接泄漏和浏览器网络事件观测延迟，不能据此直接断言服务端泄漏。 证据1（本地 `output/nl-e2e-fix-20261009/isolated-recovery/natural-language-recovery--98877-le-task-and-bounded-streams/evidence.json`） 证据2（本地 `output/nl-e2e-fix-20261009/isolated-recovery-results.json`） 证据3（本地 `output/nl-e2e-fix-20261009/resource-cycle-cleanup.json`） |
| NL-UX-01 | 区分两次确认 | 前提阻塞 | 需要首次使用者参与并记录两次确认的误判人数；自动化不能代替此项用户研究。 证据1（本地 `output/nl-e2e-fix-20261009/full-retry-results.json`） |
| NL-UX-02 | 差异可定位 | 部分覆盖 | 100步保持完整且仅第80步预期改变，审阅内容容器可见并包含该文本；未证明第80行已滚入容器视口，也未测人工定位耗时。 证据1（本地 `output/nl-e2e-fix-20261009/diff-location-final/natural-language-long-text-c8466-ing-text-and-can-be-located/evidence.json`） 证据2（本地 `output/nl-e2e-fix-20261009/diff-location-final-results.json`） |
| NL-UX-03 | 剩余数量可理解 | 部分覆盖 | 12条链路覆盖3条部分纳入及9条剩余候选，未按设计的正式1/候选2/目标2逐视图核对。 证据1（本地 `output/nl-e2e-fix-20261009/full-chain-final-results.json`） |
| NL-UX-04 | 错误提示可行动 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/full-retry/natural-language-full-NL-U-b304a-n-be-corrected-in-same-task/evidence.json`） |
| NL-UX-05 | 键盘完整操作 | 部分覆盖 | 键盘提交、确认、审阅及采纳通过，留有焦点截图；没有独立断言弹窗关闭后的焦点恢复。 证据1（本地 `output/nl-e2e-fix-20261009/recovery-ui/natural-language-recovery--fdec9-onfirms-reviews-and-applies/evidence.json`） 证据2（本地 `output/nl-e2e-fix-20261009/recovery-ui-results.json`） |
| NL-UX-06 | 小窗口与缩放 | 部分覆盖 | 640×360 CSS视口可操作，用作1280×720下200%缩放的布局近似；没有实际浏览器缩放验收。 证据1（本地 `output/nl-e2e-fix-20261009/recovery-ui/natural-language-recovery--366c5-percent-equivalent-viewport/evidence.json`） 证据2（本地 `output/nl-e2e-fix-20261009/recovery-ui-results.json`） |
| NL-UX-07 | 中文口语及纠正 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/isolated-full/natural-language-full-NL-U-c2a82--before-explicit-correction/evidence.json`） |
| NL-UX-08 | 停止状态与下一步 | 部分覆盖 | 首批后取消、刷新后保持取消及正式数据不变已验证；是否容易理解如何保留预览和继续尚需人工体验。 证据1（本地 `output/nl-e2e-fix-20261009/cancel-results.json`） |
| NL-SEC-01 | 只读成员不能改写落库 | 前提阻塞 | 当前角色模型只有owner/member，无法建立只读成员前提；越权账号拒绝写入由SEC-02覆盖，不能替代只读角色验收。  |
| NL-SEC-02 | 越权集合引用 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/isolation/natural-language-isolation-e3dc3-d-target-binding-are-denied/evidence.json`） |
| NL-SEC-03 | 用例正文提示注入 | 通过 | 自动化断言通过。 证据1（本地 `output/nl-e2e-fix-20261009/full/natural-language-full-NL-S-fe932-data-and-only-title-changes/evidence.json`） |
| NL-SEC-04 | 标题脚本作为文本 | 部分覆盖 | 脚本式标题在审阅、列表和脑图中无img节点且不触发dialog；未记录完整外部请求列表。 证据1（本地 `output/nl-e2e-fix-20261009/evaluation/natural-language-evaluatio-b7ad5-ke-title-remains-inert-text/evidence.json`） 证据2（本地 `output/nl-e2e-fix-20261009/evaluation-results.json`） |
<!-- ACCEPTANCE_MATRIX_END -->
