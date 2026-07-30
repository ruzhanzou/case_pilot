# CasePilot V1.0.0 发布与验收记录

> 发布日期：2026-07-30
> Git 标签：`v1.0.0`
> 发布门禁：确定性端到端测试、后端/Agent 单元测试、前端构建与静态检查

## 1. 发布结论

V1.0.0 完成从测试设计到 QA 执行的首个正式闭环：

`新对话 → 知识索引 → 阻塞澄清 → 结构化测试说明 → 候选评审 → 正式集合 → QA 执行`

本次发布同时重建了 Figma、产品设计、交互规格和 README。设计不再描述历史的
“直接生成并写入”流程，而是与 Playwright、当前 Web/API/Agent 状态机保持一致。

## 2. Figma V1.0 交付

- [端到端交互总览](https://www.figma.com/design/fRnEKJHcshgCIa1CmYXbLx?node-id=165-38)
- [V1.0 组件页](https://www.figma.com/design/fRnEKJHcshgCIa1CmYXbLx?node-id=165-30)
- [01 新对话](https://www.figma.com/design/fRnEKJHcshgCIa1CmYXbLx?node-id=165-43)
- [02 知识库就绪](https://www.figma.com/design/fRnEKJHcshgCIa1CmYXbLx?node-id=165-44)
- [03 结构化测试说明](https://www.figma.com/design/fRnEKJHcshgCIa1CmYXbLx?node-id=165-45)
- [04 候选评审](https://www.figma.com/design/fRnEKJHcshgCIa1CmYXbLx?node-id=165-46)
- [05 正式用例管理](https://www.figma.com/design/fRnEKJHcshgCIa1CmYXbLx?node-id=165-47)
- [06 历史记录](https://www.figma.com/design/fRnEKJHcshgCIa1CmYXbLx?node-id=165-48)
- [07 QA 执行](https://www.figma.com/design/fRnEKJHcshgCIa1CmYXbLx?node-id=165-49)

设计系统复用既有 3 个变量集合、58 个变量、9 个文字样式和 3 个阴影样式。
新增 4 组组件：

| 组件 | 变体数 | 作用 |
| --- | ---: | --- |
| Nav Item | 2 | 一级导航选中态 |
| Action Button | 4 | 主/次操作与禁用态 |
| Status Pill | 4 | 索引、生成、资产与执行状态 |
| List Row | 2 | 集合、候选和正式用例选择 |

原型从“01 新对话”启动，包含 33 个点击导航或关键业务连接。

## 3. 端到端验收

### 3.1 知识与澄清链路

测试：`apps/web/e2e/agent-knowledge-flow.spec.ts`

覆盖：

1. 登录后进入新对话；
2. 上传需求文件并等待“可检索”；
3. 发送缺少测试对象的生成请求；
4. 验证阻塞问题；
5. 通过对话补齐测试对象和成功标准；
6. 确认结构化测试说明；
7. 生成候选并纳入正式集合；
8. 在正式资产中打开用例；
9. 刷新并重新选择集合，Revision 仍可读取；
10. 浏览器控制台无未处理错误。

### 3.2 实时语音链路

测试：`apps/web/e2e/doubao-voice-flow.spec.ts`

覆盖：

1. 提交包含权限、性能、弱网、设备切换和隐私约束的实时语音需求；
2. 确认测试说明；
3. 生成 8 条结构化候选；
4. 验证弱网重连与资源释放场景；
5. 显式纳入正式集合；
6. 验证正式资产使用 `CP-*` 编号与 Revision；
7. 按业务标题搜索和打开正式用例；
8. 刷新后重新选择最新同名集合，数据仍存在。

### 3.3 真实模型 smoke

`apps/web/e2e/doubao-voice-real-model.spec.ts` 默认跳过，避免外部模型可用性阻塞
发布门禁。显式运行：

```bash
CASEPILOT_E2E_REAL_MODEL=1 \
CASEPILOT_E2E_MODEL_LABEL=doubao-seed-2.0-lite \
pnpm --dir apps/web exec playwright test e2e/doubao-voice-real-model.spec.ts
```

## 4. 发布验证

| 检查 | 结果 |
| --- | --- |
| API 单元测试 | 33 passed |
| Agent 单元测试 | 29 passed |
| Python Ruff | passed |
| Web rendered HTML | 2 passed |
| Web ESLint | passed |
| Web production build | passed |
| Playwright 确定性 E2E | 2 passed |
| Playwright 真实模型 smoke | opt-in |
| Figma 组件结构与截图 | passed |
| Figma 七状态原型审计 | passed |

发布回归使用 Mock Agent 和 Mock Embedding，但仍经过真实浏览器、FastAPI、
Celery、Redis 和 PostgreSQL。这样可以验证系统集成，同时不把外部模型波动当成
产品回归。

## 5. 版本边界

V1.0.0 不包含：

- 自动生成或执行浏览器/API 自动化脚本；
- Jira、ADO、Confluence、Drive 等连接器；
- AI 自动发布正式用例；
- 缺陷系统双向同步；
- 多人实时共同编辑；
- 将某次 QA 结果写成正式用例资产状态。

## 6. 升级说明

- 根工作区、Web、API 和 Agent 版本统一为 `1.0.0`。
- 部署前执行全部 Alembic 迁移。
- 生产环境必须替换或禁用示例账号。
- API Key 只配置在 API/Agent 服务端环境，不进入 Web 构建或 Git。
- 真实 Chat 与 Embedding Provider 可独立配置；Embedding 失败时按配置降级。
