# Task 模糊搜索与删除端到端验收

日期：2026-09-23
结论：本次修改在独立验收环境中通过，未部署到原 localhost:3000 服务。

## 环境

- 前端：http://localhost:3001（当前工作区代码）
- API：http://localhost:8001（当前工作区代码）
- PostgreSQL：独立数据库 `casepilot_task_acceptance_0923`，迁移至 `20260922_0026`
- 独立创建 owner / member / outsider 三个验收账号，原服务数据未修改。

## 验收结果

| 链路 / 场景 | 结果 | 证据 |
| --- | --- | --- |
| UI 加载 | 通过 | 搜索框、任务卡片、删除按钮正常显示，初始 2 个任务 |
| 中文、局部文字、大小写 | 通过 | `登录 SMOK` 匹配 1 个任务 |
| 全角字符归一化 | 通过 | `ＳＭＯＫＥ` 匹配 1 个任务 |
| 来源搜索 | 通过 | `账号登录` 匹配 2 个任务 |
| 执行人 / 创建人搜索 | 通过 | `李四`、`张三` 分别匹配 2 个任务 |
| 多字段组合搜索 | 通过 | `支付 beta 李四` 匹配 1 个任务 |
| 无匹配 / 空白搜索 | 通过 | `不存在的任务` 为 0；空白恢复 2 个任务 |
| 取消删除 | 通过 | 页面内确认框取消后，Beta 任务和统计保持不变 |
| 确认删除 | 通过 | 点击确认后，Beta 消失、统计归零、显示空列表 |
| 刷新及自动同步 | 通过 | 刷新完成并经过同步周期后依旧 0 个任务 |
| 普通成员越权 | 通过 | 真实 HTTP DELETE 返回 403；摘要 can_manage=false |
| 外部用户越权 | 通过 | 真实 HTTP DELETE 返回 403 |
| 创建者删除 | 通过 | 成员删除自己创建的已终止任务返回 204 |
| 管理员删除 | 通过 | Owner 删除其他成员创建的任务返回 204 |
| 数据级联清理 | 通过 | ExecutionRun、ExecutionRecord、ExecutionRunAssignee 最终均为 0 |
| 原用例保留 | 通过 | 原用例存在且 deleted_at 为 null |
| 删除审计 | 通过 | 本验收空间存在 4 条 execution_run.deleted 审计 |
| Playlist 历史任务删除 | 通过 | 数据库集成测试覆盖删除后 GET 404、列表移除、记录及分配清理 |
| 浏览器错误 | 通过 | 最终页面 error/warn 日志为空 |

## 自动化检查

- API：test_execution_playlists.py + test_execution_run_delete.py：7 passed。
- 搜索单元测试：1 passed（涵盖多个匹配 / 不匹配输入）。
- TypeScript 类型检查、改动组件 ESLint、git diff --check：通过。

## 验收中修正

原生 window.confirm 在浏览器验收控制中发生超时，因此改用页面内原生 HTML dialog。
确认框支持取消、Escape、焦点约束、删除中禁用按钮，并展示删除失败信息。
改动后重新验证取消、确认、刷新和类型 / 静态检查。

## 范围

本次只验收 Task 搜索与删除链路。未发布到原 localhost:3000 服务；未修改原服务的业务数据。
