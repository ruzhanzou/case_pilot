# CasePilot 对话区验收集合 V1

本集合验证对话 Persona、真实流式输出、资产意图白名单、集合确认、单集合锁定、
跨集合续接、目标归属、历史恢复和附件安全。验收数据均使用带时间戳的隔离集合，
正式资产写入仍受候选、差异或删除清单的人工门禁约束。

## 自动化入口

```bash
pnpm test:api
pnpm test:agent
pnpm accept:conversation
docker compose run --rm web pnpm test:e2e:conversation
```

- `test:api` 包含 39 条意图语料的 Macro-F1、写意图精确率、最多三项顺序、
  集合确认请求契约和规则回归。
- `accept:conversation` 使用当前配置的豆包/OpenAI-compatible Provider，创建
  `登录回归用例-<token>` 与 `支付回归用例-<token>`，执行 API、SSE 和数据库可观察
  行为，并输出 `artifacts/conversation-acceptance-*.json`。
- `test:e2e:conversation` 验证浏览器中的真实增量渲染、知识问答不跳工作台、
  集合确认、跨集合新对话预填和历史侧栏动画。

## 自动化覆盖映射

| 验收范围 | 自动化证据 |
| --- | --- |
| CHAT-001～009 | Persona、删除方法问答、模型任务及多个 `qa.delta`；Provider 失败安全降级由 Agent/API 单测覆盖 |
| INTENT-001～011 | 固定语料评测、否定删除、多意图顺序、三项上限、action 契约 |
| COLL-001～012 | 首次确认、取消、同集合复用、跨集合阻断/续接、409 锁定、422 目标归属 |
| FLOW-001～010 | 现有 brief/candidate/change-set/Revision 测试与真实 Provider 冒烟；人工应用前不写正式资产 |
| UI-001～011 | Playwright 对话流、历史抽屉、工作台锁定提示；附件 API 验证 TXT、DOCX、伪造 PDF 与超限文件 |
| 数据迁移 | 删除集合后 `collection_id=NULL` 且会话仍可从历史恢复；同一集合可由多段会话绑定 |

## 报告字段

每条真实验收结果记录：

- `actual_reply`、`intent`、`action`、`operation_status`；
- `conversation_id`、`collection_id`、页面去向；
- `related_job_id`、`related_change_set_id`；
- 完整 SSE 事件名称序列和专项证据。

## 通过门槛

- 所有 P0 自动化必须通过，跨集合误写入、未确认写入和 Provider 失败误写入为 0。
- Landing 与工作台均必须产生至少两个 `qa.delta`，浏览器中观察到至少三个不同
  的助手消息长度。
- 意图 Macro-F1 不低于 0.92；生成/修改精确率不低于 0.95；删除精确率不低于 0.99。
- API、Agent、Web lint/build 无回归，浏览器控制台无错误。

`casepilot-test-case-generation` Skill 只用于形成可审阅候选，不允许验收脚本绕过人工
确认直接发布生成候选。
