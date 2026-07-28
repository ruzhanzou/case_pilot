# CasePilot 轻量测试执行设计与实现

> 产品设计版本：V2.1
> 当前实现版本：V0.5
> 日期：2026-07-27
> 范围：QA 填写任务描述，创建独立执行任务并记录结果
> Figma：[V4 任务历史看板](https://www.figma.com/design/fRnEKJHcshgCIa1CmYXbLx?node-id=102-2) · [V4 多人协作执行详情](https://www.figma.com/design/fRnEKJHcshgCIa1CmYXbLx?node-id=77-3) · [V4 新建任务必填校验](https://www.figma.com/design/fRnEKJHcshgCIa1CmYXbLx?node-id=111-25)

## 1. 产品目标

QA 从主导航进入“测试执行”时，首先查看当前空间全部执行任务的历史、实时进度、结果分布和参与成员。进入某个任务后，空间成员可以共同执行；从用例资产页“开始执行”则直接进入新建任务流程。

首版形成轻量执行闭环，不扩张为完整测试管理系统：

- 纳入：空间级任务历史、执行任务、任务描述、集合快照、多人参与者、执行队列、步骤确认、执行结果、实际结果、缺陷/阻塞引用、实时进度。
- 暂不纳入：测试计划排期、复杂环境管理、设备矩阵、缺陷生命周期管理、自动化调度。

## 2. 领域边界

- 用例集合是可复用测试资产容器，本身没有通过、不通过、跳过或堵塞状态。
- 用例定义和 Revision 只描述测试内容，不保存最近一次执行结果。
- `ExecutionRun` 表示某次明确的测试活动，必须填写任务描述。
- `ExecutionRecord.execution_status` 才保存未执行、通过、不通过、跳过、堵塞。
- 同一集合可在多个版本和环境上重复运行；同一用例在不同批次中的结果互不覆盖。
- 评审通过/驳回属于 Review Event，发布状态属于 Revision/Baseline 生命周期，不复用执行结果枚举。

## 3. 页面信息架构

### 3.1 任务历史首页

- 主导航“测试执行”固定进入当前空间的任务历史首页，不默认进入任一集合。
- 首屏展示全部任务、执行中、已完成和参与成员四项汇总。
- 每张任务卡展示任务描述、用例集合、状态、已执行进度、结果分布、参与成员和最后更新时间。
- 页面每 5 秒同步一次，便于负责人查看多人执行进度。
- “新建执行任务”进入独立创建页，选择用例集合并填写任务描述。

### 3.2 单任务执行页顶部

- 返回任务列表。
- 任务描述、用例集合、状态和创建人。
- 进度、结束任务和参与成员。

### 3.3 左侧执行队列

- 按集合内顺序加载用例。
- 展示编号、优先级、名称、模块和本次执行结果。
- 当前用例高亮。
- 支持上一条、下一条和直接选择。

### 3.4 右侧执行详情

- 用例基本信息与冻结的 Revision。
- 前置条件。
- 可逐项确认的执行步骤与校验点。
- 本次执行结果按钮。
- 实际结果与执行备注。
- 不通过或堵塞时显示缺陷/阻塞项引用。

## 4. 核心交互

1. QA 从主导航进入任务历史首页，查看全部任务进度；或从资产页点击“开始执行”。
2. 点击“新建执行任务”，选择用例集合并填写任务描述。
3. 确认后创建新的 `ExecutionRun`，冻结当时的用例 Revision 集合。
4. 每条 `ExecutionRecord` 初始为“未执行”，不得读取资产页的历史结果。
5. QA 选择一条用例，确认前置条件并依次执行步骤。
6. QA 标记通过、不通过、跳过或堵塞；不通过/堵塞补充实际结果和缺陷引用。
7. 页面立即保存该 Run 下的 Record，记录最后更新成员，并仅用当前 Run 记录计算进度。
8. 多位空间成员可以进入同一任务；页面每 5 秒同步最新结果。提交时携带记录更新时间，若其他成员已先修改则返回冲突并加载最新结果，避免静默覆盖。
9. 全部完成后结束任务，生成可追溯的汇总。
10. 回归验证时新建下一任务，不重置或覆盖上一任务结果。

标记“通过”时，当前实现会自动确认全部步骤；步骤 ID 和完成状态写入
`ExecutionRecord.completed_step_ids`。步骤级确认时间与操作人仍属于后续范围。

## 5. 数据对象

```text
ExecutionRun
  id
  space_id
  collection_id
  baseline_id / collection_revision_snapshot
  description
  status: active | completed | aborted
  executor_id
  started_at
  completed_at

ExecutionRecord
  id
  run_id
  case_id
  case_revision_id
  execution_status: not_run | passed | failed | skipped | blocked
  actual_result
  defect_reference
  updated_by_id
  executed_at
  updated_at

ExecutionStepRecord
  id
  execution_record_id
  step_id
  completed
  actual_result
  attachment_ids
```

`case_revision_id` 必须冻结到运行创建时加载的版本，避免执行过程中用例内容变化导致结果失去可追溯性。

## 6. 当前 API

```http
GET    /api/v1/collections/{collection_id}/execution-runs
GET    /api/v1/spaces/{space_id}/execution-runs
POST   /api/v1/collections/{collection_id}/execution-runs
GET    /api/v1/execution-runs/{run_id}
PATCH  /api/v1/execution-runs/{run_id}
PATCH  /api/v1/execution-records/{record_id}
```

创建执行任务请求：

```json
{
  "description": "验证 Audio Feature 录音、转写与中断恢复主流程"
}
```

更新执行结果时，服务端校验：

- 当前用户属于运行对应空间。
- 当前用户是该空间成员。
- 更新结果属于五种允许值。
- 执行记录继续引用创建时冻结的 `revision_id`。
- `base_updated_at` 与服务端记录一致；不一致时返回 `409 execution_record_changed`。

## 7. 首版验收标准

- 主导航可进入“测试执行”。
- 主导航默认展示当前空间所有任务及其进度、状态、结果分布和参与成员。
- 任务列表与活动任务每 5 秒自动同步。
- 用例集管理页可对当前集合点击“开始执行”。
- 创建任务前必须填写任务描述。
- 未填写描述仍可点击创建按钮；系统应在描述字段下提示必填并自动聚焦，不得表现为无响应。
- 每次确认创建都生成独立 Run；相同集合可重复创建。
- 执行队列与详情展示同一条用例。
- 可逐项勾选执行步骤。
- 可标记通过、不通过、跳过或堵塞。
- 不通过和堵塞显示缺陷/阻塞项输入。
- 标记结果后，队列状态、统计和进度同步变化。
- 切换用例不会丢失当前页面内已记录的结果。
- 资产页和脑图不展示执行结果，也不提供结果修改入口。
- 当前任务明确展示任务描述和 Run 标识。
- 空间成员可进入同一任务共同执行，记录展示最后更新成员。
- 多人同时编辑同一条记录时，后提交者收到冲突提示且不会覆盖最新结果。

## 8. 当前实现说明

当前前端已经接入真实 `ExecutionRun` 和 `ExecutionRecord`：

- 进入执行页先展示空间级任务历史，不自动沿用任何历史结果；
- 可从任务历史查看全部任务进度、结果分布和参与成员；
- 新建页选择集合并填写任务描述；
- 点击创建后生成新的独立运行；
- 首次创建运行时为集合内每条用例冻结当前 Revision；
- 后续加入集合的新用例会在恢复活动运行时补充为未执行记录；
- 执行状态、完成步骤、实际结果和缺陷引用写入 PostgreSQL；
- 更新操作校验空间成员，并记录最后更新成员；
- 活动任务和任务历史每 5 秒自动刷新；
- 更新携带记录更新时间，使用乐观并发控制阻止多人覆盖；
- 执行记录更新写入审计事件；
- 刷新后从 API 恢复，不再使用页面 Mock 状态。

当前未完成的是任务筛选与分页、成员分工、任务报告和步骤级审计对象。
