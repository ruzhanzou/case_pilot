# CasePilot 轻量测试执行设计

> 版本：V1.4
> 日期：2026-07-25
> 范围：QA 加载用例集合并逐条记录人工执行结果
> Figma：[测试执行 V1.4](https://www.figma.com/design/fRnEKJHcshgCIa1CmYXbLx?node-id=77-3)

## 1. 产品目标

QA 可以从用例集管理页或主导航进入“测试执行”，选择一个用例集合，逐条查看前置条件、执行步骤和校验点，并记录本次执行结果。

首版形成轻量执行闭环，不扩张为完整测试管理系统：

- 纳入：集合加载、执行队列、步骤确认、执行结果、实际结果、缺陷/阻塞引用、执行进度。
- 暂不纳入：测试计划排期、复杂环境管理、设备矩阵、缺陷生命周期管理、自动化调度。

## 2. 状态边界

用例状态与执行结果是两个独立字段。

| 对象 | 字段 | 可见值 | 含义 |
|---|---|---|---|
| 用例修订 | `case_status` | Pending、通过、不通过、跳过、堵塞 | 用例内容是否完成评审并可使用 |
| 本次执行记录 | `execution_status` | 未执行、通过、不通过、跳过、堵塞 | QA 在某一次运行中的实际执行结果 |

执行结果不得覆盖 `case_status`。同一条已通过评审的用例可以在不同运行中分别得到通过、不通过或堵塞结果。

## 3. 页面信息架构

### 3.1 顶部

- 当前空间。
- 用例集合选择器。
- 本次运行保存入口。
- 进度、通过、不通过和堵塞统计。

### 3.2 左侧执行队列

- 按集合内顺序加载用例。
- 展示编号、优先级、名称、模块和本次执行结果。
- 当前用例高亮。
- 支持上一条、下一条和直接选择。

### 3.3 右侧执行详情

- 用例基本信息与只读 `case_status`。
- 前置条件。
- 可逐项确认的执行步骤与校验点。
- 本次执行结果按钮。
- 实际结果与执行备注。
- 不通过或堵塞时显示缺陷/阻塞项引用。

## 4. 核心交互

1. QA 进入测试执行页面。
2. 选择要执行的用例集合。
3. 系统创建或恢复一个 `Execution Run`，所有用例初始为“未执行”。
4. QA 选择一条用例，依次确认步骤。
5. QA 标记通过、不通过、跳过或堵塞。
6. 页面立即保存执行记录并更新进度。
7. QA 切换到下一条用例。
8. 全部完成后，运行可结束并形成结果汇总。

标记“通过”时，当前原型会自动确认全部步骤；正式版本需要保存每一步的确认时间与操作人。

## 5. 数据对象

```text
ExecutionRun
  id
  space_id
  collection_id
  baseline_id
  name
  status: active | completed | aborted
  executor_id
  environment_snapshot
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
  executed_by
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

## 6. API 草案

```http
POST   /api/v1/execution-runs
GET    /api/v1/execution-runs/{run_id}
GET    /api/v1/execution-runs/{run_id}/records
PATCH  /api/v1/execution-runs/{run_id}/records/{record_id}
POST   /api/v1/execution-runs/{run_id}/complete
```

更新执行结果时，服务端校验：

- 运行仍为 `active`。
- 当前用户具有执行权限。
- `case_revision_id` 属于运行冻结的集合基线。
- 不通过必须填写实际结果；堵塞必须填写阻塞原因。

## 7. 首版验收标准

- 主导航可进入“测试执行”。
- 用例集管理页可对当前集合点击“开始执行”。
- 可在执行页切换用例集合。
- 执行队列与详情展示同一条用例。
- 可逐项勾选执行步骤。
- 可标记通过、不通过、跳过或堵塞。
- 不通过和堵塞显示缺陷/阻塞项输入。
- 标记结果后，队列状态、统计和进度同步变化。
- 切换用例不会丢失当前页面内已记录的结果。
- 用例状态保持只读，不随执行结果改变。

## 8. 当前实现说明

当前前端使用页面内状态模拟 `Execution Run` 和 `Execution Record`，便于本地验收交互。正式持久化、并发控制、权限和审计将在执行 API 与数据库表完成后接入。
