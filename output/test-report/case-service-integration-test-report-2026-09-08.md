# Case Service 真实 AI、Mock 接口与 UI 回归测试报告

- 测试日期：2026-09-08（Asia/Shanghai）
- 被测版本：工作区当前实现，数据库迁移 `20260908_0021`
- 结论：通过
- 阻断问题：0

## 1. 测试范围

本轮覆盖 TestWeb、CasePilot 与 TestTool 的 Mock 和真实 AI 闭环，并完成浏览器 UI 回归：

1. TestWeb 创建空用例集合。
2. 以固定 Prompt 自动生成 L0、L2、L4 用例并自动批准。
3. 通过 GET 和 POST 两种方式获取完整用例快照。
4. TestWeb 幂等创建待确认执行任务，并返回 Playlist 深链。
5. CasePilot 确认任务，按照 L0/L2/L4 累计规则冻结 ExecutionRun。
6. TestTool 按当前用户及目标、用例等条件查询任务。
7. TestTool 领取任务、续租、上报完整任务和用例状态。
8. `update_id` 幂等重放、时间戳防止旧状态覆盖新状态。
9. generation-status、case-summary、task-status 回调进入持久化投递箱并自动投递。
10. 真实 AI 四阶段异步生成、进度轮询和回调同步。
11. UI 新对话、生成、候选修改、正式入库、Playlist 与执行任务创建。

## 2. 环境

| 项目 | 值 |
|---|---|
| API | FastAPI / Python 3.13 |
| Agent | Celery 5.6 / Python 3.13 |
| Database | PostgreSQL 18 + pgvector |
| Queue | Redis 8 |
| TestWeb/TestTool | HTTP Mock 客户端与 Mock 回调接收器 |
| AI 生成 | Mock 固定数据 + `CASE_SERVICE_MOCK_MODE=false` 真实 AI |

## 3. 自动化结果

| 测试项 | 结果 | 数量/说明 |
|---|---|---|
| API 单元与集成回归 | 通过 | 53 passed |
| Agent 单元回归 | 通过 | 36 passed |
| Python 静态检查 | 通过 | Ruff，无错误 |
| Web 类型检查 | 通过 | `tsc --noEmit` |
| OpenAPI 契约检查 | 通过 | 12 个集成路径、14 个 HTTP 操作，响应均引用具名 Schema |
| 数据库迁移 | 通过 | 空库 upgrade head → downgrade 0018 → upgrade head |
| HTTP 回调投递 | 通过 | Mock 接收器返回 204，outbox 状态变为 delivered，attempts=1 |
| 真实 AI 接口闭环 | 通过 | CP-00009 / CASE-SESSION-00012 / TASK-00008 |
| 逐请求审计 | 通过 | 93 次客户端请求/返回、12 次异步回调，敏感字段脱敏 |
| UI 浏览器回归 | 通过 | 新对话、真实生成 7 条、修改、入库、创建任务；控制台错误 0 |

总计：89 个 Python 自动化用例通过，无失败。

## 4. 集成用例明细

| 编号 | 场景 | 预期 | 结果 |
|---|---|---|---|
| INT-001 | 无效 Case Service Token | 返回 401 | 通过 |
| INT-002 | 创建外部 Case Project | 返回 `CP-[0-9]{5,}` 和平台 URL | 通过 |
| INT-003 | 相同外部目标重复创建 | 返回原 Case Project，不重复建集合 | 通过 |
| INT-004 | 启动 Mock 生成 | 首次响应为 generating，后台转为 approved | 通过 |
| INT-005 | 固定生成分类 | 完整快照含 L0、L2、L4 | 通过 |
| INT-006 | GET/POST case-summary | 两种方式返回同一完整快照 | 通过 |
| INT-007 | 创建执行任务 | 返回 pending_confirmation、TASK ID、Playlist 深链 | 通过 |
| INT-008 | 重放 task_request_id | 返回同一任务，不重复创建 | 通过 |
| INT-009 | L2 确认 | ExecutionRun 仅冻结 L0+L2 | 通过 |
| INT-010 | 当前用户任务隔离 | TestTool 只看到匹配 `X-TestTool-User-ID` 的任务 | 通过 |
| INT-011 | 多条件查询 | `target_type` 与 `case_id` 组合过滤正确 | 通过 |
| INT-012 | 指定任务领取 | 返回一次性 lease token，任务转 running | 通过 |
| INT-013 | 心跳续租 | 合法 lease 延长有效期 | 通过 |
| INT-014 | 完整状态上报 | 任务、用例、日志、证据和 CR 同步成功 | 通过 |
| INT-015 | update_id 重放 | 返回首次响应，不产生第二次状态写入 | 通过 |
| INT-016 | 单用例查询 | 返回冻结修订及最新执行状态 | 通过 |
| INT-017 | 回调 outbox | 生成、批准、确认、领取、完成均产生回调事件 | 通过 |
| INT-018 | 回调真实 HTTP 投递 | Bearer 鉴权请求成功，投递记录标记 delivered | 通过 |
| INT-019 | 同项目再次生成 | 不冲突；新旧 generation 各自保存冻结 Revision 快照 | 通过 |
| INT-020 | 真实 AI 异步生成 | 四阶段任务完成并生成不少于 6 条用例 | 通过 |
| INT-021 | 真实生成分级 | 完整快照同时包含 L0、L2、L4 | 通过 |
| INT-022 | 逐请求与回调留痕 | 请求、响应、耗时和回调载荷全部格式化记录 | 通过 |
| UI-001 | 新对话与集合绑定 | 创建新对话并新建独立集合 | 通过 |
| UI-002 | 结构化说明与生成 | 真实模型生成说明和 7 条候选用例 | 通过 |
| UI-003 | 候选修改 | 修改标题和优先级并保存 | 通过 |
| UI-004 | 正式入库 | 7 条用例纳入正式集合 | 通过 |
| UI-005 | 创建执行任务 | 保存 7 条用例 Playlist 并创建多人执行任务 | 通过 |

## 5. 关键验收结果

- L0 目标执行 L0；L2 目标累计执行 L0+L2；L4 目标累计执行 L0+L2+L4。
- TestWeb 不传 selected case IDs；CasePilot 在确认时根据已批准快照和阶段选择用例。
- ExecutionRun 保存冻结 revision，后续用例修改不会改变该任务的执行输入。
- TestTool 使用 API Token 与外部用户 ID 双重识别；任务查询按当前用户隔离。
- Task 更新要求有效 lease、完整用例快照和递增时间戳。
- 回调使用 durable outbox、事件 ID、Bearer Token 和指数退避重试。

## 6. 可审阅证据

- 逐请求 Markdown：`case-service-real-ai-request-response-report-2026-09-08.md`
- 完整 PDF：`../pdf/case-service-real-ai-ui-regression-test-report-2026-09-08.pdf`
- UI 截图：`ui-evidence/01-new-conversation.png` 至 `ui-evidence/05-task-created.png`
- TestWeb 回调原始 JSONL：`real-ai-callbacks.jsonl`

TestWeb 使用本地 Mock HTTP 接收器，但 Case Service 发出的是真实 HTTP Bearer 请求，已验证接收 204、重试状态和持久化投递结果。TestWeb 自身页面展示不在本仓库范围内。

## 7. 复现命令

```bash
# API（含新增端到端 Mock 用例）
pytest -q apps/api/tests

# Agent
pytest -q apps/agent/tests

# Python 静态检查
ruff check apps/api apps/agent

# Web 类型检查
pnpm --dir apps/web typecheck
```
