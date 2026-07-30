# CasePilot 产品原则重构验收报告 V1

验收时间：2026-07-30（Asia/Shanghai）
实现基线：当前未提交工作树（保留并兼容进入本轮前的已有修改）
结论：**最终验收通过**

## 1. 结论摘要

- 结构化测试说明门禁、唯一持续工作区、自动保存、候选审阅后写入、CasePilot 意图、软删除、停止生成、成员与多人执行等原则级功能已实现。
- 隔离数据库从空 schema 迁移至 `20260730_0012` 成功；历史工作区中的旧 Agent 名称同步迁移为 `CasePilot`。
- 确定性 API/Agent/数据库/Redis 验收 18 项全部通过；空间所有者与普通成员恢复到同一个集合工作区。
- 真实 `doubao-seed-2.0-lite` 链路成功生成并写入 8 条用例，刷新后恢复同一工作区；未回退 Mock。
- Web 构建、服务端渲染基线、ESLint、Python lint、API 24 项单测、Agent 22 项单测全部通过。
- 内置浏览器完成 1280、1440、1920 三档复验：无横向溢出、无小于 12px 的辅助文本、无小于 14px 的工作区控件，且仅保留一个模型选择器。
- 生成中发送按钮稳定替换为“停止生成”；页面点击停止后输入恢复、已确认说明保留、未完成候选为空，刷新仍恢复同一工作区。
- 可视复验发现并修复长对话将三栏工作区撑高到 3695px 的问题；复测后三栏高度锁定视口并独立滚动，浏览器控制台无错误或警告。

## 2. 环境隔离

| 项目 | 实际配置 |
| --- | --- |
| PostgreSQL | 日常实例中的独立 schema `casepilot_e2e_5dc0` |
| Redis | 独立 DB 10 / 11 / 12 |
| 验收账号 | 空间所有者 `demo@casepilot.local`、执行人 `executor@casepilot.local` |
| 确定性 Provider | Mock，仅用于状态、权限和失败分支 |
| 真实 Provider | `doubao-seed-2.0-lite`，Embedding 为 `doubao-embedding-vision` |
| 演示数据污染 | 无；未将本轮验收数据写入日常演示 schema |

## 3. 验收结果

| 用例 | 结果 | 实际证据 |
| --- | --- | --- |
| WS-01 | 通过 | 同集合重复进入及普通成员进入均返回同一活动工作区 ID；源码无“新对话”入口 |
| WS-02 | 通过 | 说明确认前、取消后候选为空，正式集合不回退显示到当前生成画布 |
| WS-03 | 通过 | 消息、说明、候选、草稿和选中状态均持久化；浏览器刷新后恢复相同集合、V5 说明、取消消息和需求历史，无离开保存提示 |
| BR-01 | 通过 | 首次需求只生成 V1 结构化测试说明，正式用例与候选均为空 |
| BR-02 | 通过 | 连续修改产生递增版本，旧版本变为 `superseded` 且不能确认 |
| BR-03 | 通过 | 阻塞项存在时返回 409；解决后指定版本确认才创建生成任务 |
| BR-04 | 通过 | 停止后立即为 `cancelled`，1 秒后仍为终态；说明保留、候选为空，可重新开始 |
| AG-01 | 通过 | 候选编辑、排除、写入正式集合、Revision 创建和恢复均正确 |
| AG-02 | 通过 | 当前用例与当前模块差异生成、部分字段接受及 Revision 正确 |
| AG-03 | 通过 | 查询、审阅式软删除、取消删除、确认删除和审计记录正确 |
| AG-04 | 通过 | 知识问题产生检索阶段和来源；“你好”走 `SMALL_TALK` 且 `retrieval_performed=false` |
| AG-05 | 通过 | 身份回答包含“我是 CasePilot”，职责为测试用例生成与维护 |
| EX-01 | 通过 | 5 条用例、2 名执行人稳定轮询分配为 3/2 |
| EX-02 | 通过 | 非执行人更新返回 403；执行人可保存，另一账号可同步读取 |
| EX-03 | 通过 | 管理者改派后历史结果保留，责任人与审计更新 |
| EX-04 | 通过 | 并发冲突、冻结 Revision、结束只读、任务间结果隔离均通过 |
| UI-01 | 通过 | 三档页面均不存在“新对话”“新建用例”“数据已连接”，仅一个模型选择器；生成中发送按钮替换为“停止生成”并已截图 |
| UI-02 | 通过 | 1280/1440/1920 的 `scrollWidth` 均等于视口宽度；可见辅助文本无低于 12px，控件无低于 14px/34px 高度；长对话固定视口滚动 |
| REG-01 | 通过 | 登录、集合/用例 CRUD、Revision、执行状态、构建和单测回归通过 |
| ERR-01 | 通过 | Provider 无效响应映射为中文公开错误；取消竞争、刷新恢复和中文停止反馈通过；最终浏览器控制台 0 error / 0 warning |

## 4. 真实 Provider 冒烟

真实链路执行了：

`新集合 → 唯一工作区 → 真实模型生成测试说明 → 用户确认版本 → 真实模型生成 → 8 条候选 → 写入 8 条正式用例 → 管理恢复`

阶段证据包含：

- `requirement.analyzed`：`doubao-seed-2.0-lite`
- `feature.generated`：`doubao-seed-2.0-lite`
- `test_point.generated`：`doubao-seed-2.0-lite`
- `test_case.generated`：`doubao-seed-2.0-lite`
- `context.prepared`：`openai_compatible:doubao-embedding-vision`

首次运行发现无质量缺口时仍要求 Provider 回传全部 8 条用例作为“增强结果”，响应在 4096 token 处截断。系统未泄露内部异常，公开错误为 `provider_response_invalid`。修复为：质量校验无错误缺口时不再执行无价值的全量增强回传；重试后任务完成，候选、正式写入和恢复均通过。

## 5. 缺陷与修复

| 缺陷 | 优先级 | 修复内容 | 复测 |
| --- | --- | --- | --- |
| CP-P0-001 | P0 | 增加结构化测试说明版本、阻塞项和确认门禁 | 通过 |
| CP-P0-002 | P0 | 生成未完成/失败/停止时画布不显示旧集合资产 | 通过 |
| CP-P0-003 | P0 | 集合级唯一活动工作区、历史归档、状态自动保存 | 通过 |
| CP-P1-004 | P1 | CasePilot 身份、闲聊无检索、查询/删除/修改意图 | 通过 |
| CP-P0-005 | P0 | 新增取消终态；修复 Worker 将 `cancelled` 覆盖回 `running` 的竞态 | 通过 |
| CP-P1-006 | P1 | 删除变更集、明确确认、软删除 Revision 与审计 | 通过 |
| CP-P0-007 | P0 | 成员管理、必选执行人、稳定平均分配、改派与权限 | 通过 |
| CP-P1-008 | P1 | 移除重复模型/新对话/新建用例/范围控件，工作区字号下限 | 通过 |
| CP-P0-009 | P0 | 建立隔离 schema 与 Redis 分区，避免演示库污染 | 通过 |
| CP-P1-010 | P1 | 真实 Provider 无缺口增强响应被 token 截断 | 通过 |
| CP-P1-011 | P1 | 长对话撑高三栏工作区；增加弹性收缩和聊天列独立滚动约束 | 通过 |
| CP-P1-012 | P1 | Agent 名称由错误拼写统一为 `CasePilot`，并迁移持续工作区历史消息与来源快照 | 通过 |

## 6. 自动化回归

| 检查 | 结果 |
| --- | --- |
| Web build + rendered HTML | 2/2 通过 |
| ESLint | 通过 |
| Python Ruff | 通过 |
| API tests | 24/24 通过 |
| Agent tests | 22/22 通过；仅第三方 SWIG 类型弃用警告 |
| Alembic empty-schema smoke | 从 base 到 `20260730_0012` 通过 |
| 确定性原则验收 | 18/18 通过 |
| 真实 Provider smoke | 通过；8 候选、8 正式用例、同工作区恢复 |
| 浏览器三档可视验收 | 1280 / 1440 / 1920 全部通过 |
| 浏览器停止与刷新恢复 | 通过；停止按钮、取消终态、说明保留、候选清空、刷新恢复 |
| 浏览器控制台 | 0 error / 0 warning |

## 7. 最终签署

当前没有已知未修复的原则级 P0/P1 缺陷，最终签署条件全部满足：

1. 1280、1440、1920 三档桌面截图均已归档。
2. 所有可见工作区文本与控件完成计算样式扫描，字号满足下限。
3. 无关键内容遮挡或横向溢出，生成中停止按钮替换发送按钮。
4. 浏览器控制台无未解释错误或警告。
5. 确定性全套与真实 Provider 冒烟均通过，且验收数据保持隔离。

## 8. 证据文件

- `docs/evidence/casepilot-principles-deterministic.json`
- `docs/evidence/casepilot-real-provider-smoke.json`
- `docs/evidence/casepilot-visual-acceptance.json`
- `docs/evidence/ui-01-stop-generation.jpg`
- `docs/evidence/ui-02-1280.jpg`
- `docs/evidence/ui-02-1440.jpg`
- `docs/evidence/ui-02-1920.jpg`
- `scripts/casepilot_principles_acceptance.py`
- `scripts/casepilot_real_provider_smoke.py`
