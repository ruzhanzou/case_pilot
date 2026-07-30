# CasePilot 原则重构与真实模型验收记录

验收时间：2026-07-30 15:15（Asia/Shanghai）

当前结论：**验收通过。**

本轮已将产品与对话 Agent 名称统一为 `CasePilot`，接入火山方舟 Coding
Plan 兼容接口，并用真实聊天模型和真实 Embedding 完成生成、知识问答、
用例管理与多人执行验收。真实链路未回退 Mock，验收数据只写入隔离数据库。

## 配置与兼容性

- Provider：OpenAI-compatible。
- Base URL：`https://ark.cn-beijing.volces.com/api/coding/v3`。
- 默认真实模型：`doubao-seed-2.0-lite`。
- Embedding：`doubao-embedding-vision`，2048 维。
- 工作区模型清单：
  `ark-code-latest`、`doubao-seed-2.0-lite`、`glm-5.2`、
  `kimi-k2.7-code`、`deepseek-v4-pro`、`deepseek-v4-flash`、
  `minimax-m3`、`minimax-m2.7`、`kimi-k2.6`、
  `doubao-seed-2.1-turbo`。
- API Key 仅保存在本机忽略的环境文件中，未写入源码、日志或验收证据。

## 本轮端到端结果

1. 登录后默认进入“新对话”，历史侧栏默认隐藏。
2. 历史侧栏为 300px 覆盖式抽屉，不改变三栏宽度；支持 `Esc` 关闭，
   选择历史对话后自动收起。
3. 每条活动对话只绑定一个用例集合，并可恢复消息、工作流与工作区状态。
4. 真实模型先生成结构化测试说明；确认最新版本后才生成候选。
5. 真实 Provider 生成 9 条登录用例，全部写入正式集合并恢复到维护状态。
6. “豆包实时通话”Markdown 文档使用真实 Embedding 建立索引。
7. 知识问题先完成内部知识检索，再由真实模型组织回答，返回 2 条来源。
8. 真实生成集合在用例管理中显示 9 条正式用例及完整详情。
9. 创建 2 人执行任务，9 条用例按稳定顺序平均分配为 5/4。
10. 首条执行结果保存为“通过”，任务进度从 0/9 更新为 1/9。

## 本轮新发现并修复

| 缺陷 | 优先级 | 修复与复测 |
| --- | --- | --- |
| Agent 曾存在 `CasePliot`、`CodePliot`、`CodePilot` 多种旧拼写 | P0 | 运行时、页面、提示词和持久化数据统一为 `CasePilot`；新增 `0014` 数据迁移 |
| 新对话页残留 `CASEPLIOT WORKSPACE` | P1 | 改为 `CASEPILOT WORKSPACE`，重新构建后浏览器复测通过 |
| 旧真实凭据导致 Provider HTTP 401 | P0 | 使用本轮授权凭据重新配置，本地安全存储；聊天和 Embedding 实际请求均返回 200 |
| 全新数据库迁移在扩展权限阶段被阻塞 | P1 | 由数据库管理员预装 `vector` 与 `pg_trgm` 后，从空库迁移至 `0014 head` 通过 |

## 自动化与可视验收

- 原则验收：17/17 通过。
- API：26/26 通过。
- Agent：26/26 通过。
- Web 渲染：2/2 通过。
- Web 构建、Web lint、Python lint、`git diff --check`：通过。
- 全新数据库迁移：`20260730_0014 (head)`。
- 真实结构化说明与用例生成：通过，9 条候选写入 9 条正式用例。
- 真实知识问答：通过，聊天模型与 Embedding 均有任务阶段证据。
- 1280、1440、1920px：无横向溢出；控件不低于 14px，辅助文本
  不低于 12px。
- 历史抽屉：300px 覆盖布局，`Esc` 关闭通过。
- 应用浏览器错误日志：0。

## 发布门槛

本轮原则级 P0/P1 用例全部通过；没有未解释的浏览器错误、接口 5xx、
原始 Provider 异常或演示库污染。真实 Provider 链路已经成功，因此本轮
可以给出最终“验收通过”。

结构化证据：
`docs/evidence/casepilot-restored-acceptance-20260730.json`
