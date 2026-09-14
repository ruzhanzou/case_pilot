# CasePilot 完整动线验收报告

- 测试日期：2026-09-14（Asia/Shanghai）
- 被测环境：Docker Compose，本地 Web `:3000`、API `:8000`、PostgreSQL 18、Redis 8、Celery Agent
- AI：已配置 OpenAI-compatible 真实模型；Case Service 接口专项使用确定性 Mock
- 修复复验时间：2026-09-14 17:46（Asia/Shanghai）
- 总结论：**通过**
- 原 1 个 P1、2 个 P2 均已修复并复验通过

## 1. 验收范围与结果

| 范围 | 结果 | 证据 |
|---|---|---|
| 登录、会话恢复、历史搜索 | 通过 | 浏览器对话回归 3/3；API 对话验收 12/12 |
| 多意图对话 | 通过 | 同一输入被拆为“知识问答 + 生成用例”；问答、集合绑定、说明确认和候选生成完整完成 |
| 结构化测试说明 | 通过 | 真实模型生成 V1，包含测试对象、范围、规则、风险、覆盖维度、假设；未知阈值未编造 |
| 候选用例生成 | 通过 | 真实模型完成 10 条候选、质量评分 76；超时后自动回退默认模型，候选未写入正式集合 |
| 用例修改与 Revision | 通过 | 对接口生成的正式用例创建 V2，标题、优先级、标签生效 |
| 用例管理/搜索 | 通过 | test_target、创建人、组合、空结果、集合搜索均通过；浏览器 1/1 |
| Playlist | 通过 | 深链预填 2 条用例并保存；去重和集合归属展示正常 |
| 创建执行任务 | 通过 | 创建 2 条冻结用例、2 名执行人的任务；进度为 0/2，状态为执行中 |
| Revision 冻结 | 通过 | 任务仍引用 V1；正式资产更新至 V2 后任务输入未变化 |
| Case Service / TestTool API | 通过 | 14 次逐请求闭环通过；summary GET/POST 响应稳定一致；领取、续租、状态上报、幂等重放、单用例查询成功 |
| 深链 | 通过 | 未登录打开后登录可恢复；自动进入 Playlist 创建页并预填名称与 2 条用例 |
| 回调 outbox | 通过 | `playlist-created` 入队，correlation/context 与 `case_generation_id` 原样保留；测试占位域名投递失败属预期 |

## 2. 自动化结果

| 套件 | 结果 |
|---|---|
| API 全量 pytest | 56 passed |
| API Playlist 专项 | 1 passed |
| API v1.4 调用方回调与深链专项 | 1 passed |
| Agent pytest | 45 passed，5 个第三方 SWIG 弃用告警 |
| 对话 API 实机验收 | 12 passed |
| Web 构建/单元测试 | 7 passed |
| Web TypeScript / ESLint | 通过 |
| Python Ruff | 通过 |
| 浏览器对话回归 | 3 passed |
| 浏览器用例搜索 | 1 passed |
| 浏览器管理/任务取证 | 2 passed |
| 浏览器深链预填 | 1 passed |

容器内 Playwright 首次运行因镜像未包含 `/opt/google/chrome/chrome`，4 条用例在启动浏览器前退出；使用工作区自带 Node 和宿主机既有 Chrome 复跑后相关用例全部通过，因此归类为测试镜像基础设施问题，不计产品失败。

## 3. 端到端实际数据

- 首次多意图会话：`a35a2b89-7c32-4cb9-abe2-66efba53aa15`（修复前失败证据）
- 修复复验会话：`cb5c0300-d686-4d3c-ab94-2d48e9c3fa0b`
- 多意图集合：`验收-多意图邮箱登录-20260914`
- 结构化说明任务：`93ffc285-6a2c-4c82-9867-75f3e9eaf727`，最终完成
- 修复前候选任务：`467dc919-fe47-4881-9c7f-c4be6163e885`，`failed/APITimeoutError`
- 修复后候选任务：`a5542174-878c-4fcd-b31c-c5e8d5f4ccb0`，`completed`，10 条候选，质量评分 76
- 接口项目：`CP-00040`
- 接口生成：`CASE-SESSION-00071`
- TestTool 任务：`TASK-00025`，完整执行闭环完成
- 深链会话：`b33848cf-a02d-4311-bdd3-fdc69ba0eec4`
- Playlist：`e2c92f09-04ec-4624-9cde-56cc61636024`
- 修复复验深链会话：`a28aa506-d052-4eb7-923b-6a95374b47ca`
- 修复复验 Playlist：`59aef4fd-b34b-4ccb-832c-67cf78619010`
- UI 执行任务：`4f916945-5125-4b71-9bc9-49e2a94e492e`

首次修复任务的阶段耗时：需求分析 53.440 秒、功能点 109.465 秒；首选模型在测试点、用例阶段分别等待 120 秒、300 秒后才回退，整条链路墙钟时间约 11 分钟。性能优化后，非默认模型在全部结构化生成阶段最多探测 45 秒；同一任务一旦发生超时或结构错误，后续阶段直接使用默认模型。最终复验任务 `b1e717be-2405-4b91-99c8-9f90653bc8f5` 生成 8 条候选、质量评分 100，候选未提交正式集合。

## 4. 缺陷修复与复验

### BUG-001 · P1 · 真实候选用例生成超时 — 已修复

- 步骤：输入多意图请求 → 明确第二意图为“生成用例” → 新建并绑定集合 → 等待 V1 结构化说明 → 点击“确认并生成用例”。
- 预期：生成候选用例并进入人工评审；候选不自动写入正式集合。
- 根因：Agents SDK 对超时进行隐式多次重试，单阶段可长时间占用；当前 SDK Provider 缺少结构校验纠错与模型兜底。
- 修复：长输出阶段保留独立 300 秒成功窗口，但非默认模型在结构化阶段只探测 45 秒；关闭 SDK 隐式重试；非默认模型结构错误时立即回退，默认模型仍可纠错一次；同一任务后续阶段跳过已降级模型。质量修复改用差量输入，并允许新增功能点修复引用缺口，避免整批重写造成 JSON 截断。
- 复验：任务 `a5542174-878c-4fcd-b31c-c5e8d5f4ccb0` 完成测试点、10 条候选和质量检查；历史对话显示“已生成 10 条候选用例，质量评分 76”；候选评审页可见 10 条且正式集合尚未提交。

### PERF-001 · 用例生成等待时间优化 — 已生效

- 配置：`CASEPILOT_AGENT_MODEL_FALLBACK_TIMEOUT_SECONDS=45`，运行容器已确认读取为 `45.0`。
- 范围：需求、功能点、测试点、批量用例、质量修复五类结构化阶段。
- 同输入对照：需求阶段由 150.851 秒降到 94.967 秒；功能点阶段由 168.611 秒降到 87.602 秒，两阶段合计减少 136.893 秒。
- 质量修复：原整批修复返回被截断并失败；差量修复重试 40.8 秒完成，其中模型阶段 37.475 秒，输入/输出为 5,117/1,302 tokens，质量评分由 75 修复为 100。
- 任务级熔断：首次降级后，后续阶段直接使用默认模型；覆盖五类阶段及跨阶段熔断的回归测试通过。
- 说明：默认模型生成 8 至 10 条结构化用例本身仍需约 1 至 3 分钟/重输出阶段，剩余耗时是有效生成而非重复超时等待。

### BUG-002 · P2 · GET/POST case-summary 返回不同深链令牌 — 已修复

- 失败测试：`test_testweb_mock_generation_and_testtool_execution_loop`。
- 根因：`case_project_access_token()` 每次调用都以“当前时间 + TTL”生成新的到期秒。
- 修复：新增迁移 `20260914_0023`，将项目链接到期时间持久化；过期时再统一轮换。
- 复验：连续 GET/POST 返回完全相同响应与 token；原失败测试恢复通过，API 全量 56/56。

### BUG-003 · P2 · playlist-created 回调丢失 generation ID — 已修复

- 根因：Playlist 详情由 source collection 重建时把 `case_generation_id` 固定为 `null`。
- 修复：详情构造时读取关联的 Playlist 创建会话，并按 collection 恢复 generation ID。
- 复验：会话 `a28aa506-d052-4eb7-923b-6a95374b47ca` 的完成响应与 `playlist-created` 回调均返回 `CASE-SESSION-00071`；新增回归断言通过。

## 5. 关键证据

- 完整接口逐请求/响应（14 次，含 request body）：[`api-request-response.md`](./api-request-response.md)
- 深链、用例修订和冻结校验 request body：[`deeplink-and-revision-api.md`](./deeplink-and-revision-api.md)
- 三项修复的 API request body、response、回调和生成阶段：[`fix-verification-api.md`](./fix-verification-api.md)
- 对话 API 原始结果：[`artifacts/conversation-acceptance-20260914-065241.json`](../../../artifacts/conversation-acceptance-20260914-065241.json)
- 关键 UI 截图：`ui-evidence/01` 至 `13`

截图索引：

1. `01-case-assets-baseline.png`：用例资产基线
2. `02-test-target-fuzzy-search.png`：test_target 模糊搜索
3. `03-creator-fuzzy-search.png`：创建人搜索
4. `04-combined-search.png`：组合搜索
5. `05-empty-result.png`：空结果
6. `06-collection-search.png`：集合搜索
7. `07-collection-search-empty.png`：集合空结果
8. `08-case-management.png`：用例管理
9. `09-execution-task-list.png`：执行任务列表
10. `10-execution-task-detail.png`：冻结 2 条用例的任务详情
11. `11-deeplink-prefill.png`：深链登录后自动预填 Playlist 与 2 条用例
12. `12-multi-intent-generation-fixed.png`：多意图历史对话显示 10 条候选生成完成
13. `13-candidate-review-fixed.png`：10 条候选评审列表、质量工作流完成及“纳入正式集合”人工确认入口

## 6. 发布建议

本轮完整验收通过，可以进入下一发布阶段。性能优化已部署到当前 Agent/cleanup 容器；建议继续保留真实模型阶段耗时、任务级熔断和 fallback 告警，以便区分无效等待与默认模型的有效生成时间。`caller.example` 的回调投递失败仅为测试占位域名，真实联调时仍需使用可达回调地址验证网络层投递。
