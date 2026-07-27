# CasePilot

CasePilot 是一个本地部署的结构化测试用例管理与 QA 执行平台。

当前验收版本覆盖“聊天创建候选用例 → 脑图/列表评审 → 写入正式用例资产
→ 创建执行任务 → 多人协作记录结果”的完整产品闭环。AI 工作台已按 Figma
V2.2 接入主导航；当前生成逻辑用于本地交互验收，真实模型、文件解析和异步
生成任务仍由独立 Agent 基础设施承接后续接入。

## 当前可用能力

- 本地账号注册、登录、退出和持久会话。
- AI 用例工作台首次进入采用聊天创建页，可选择目标集合、输入测试目标、
  添加需求文件并使用示例提示快速开始。
- 生成完成后进入“对话 / 脑图或列表 / 用例详情”三栏工作区，展示阶段进度、
  覆盖提醒、结构化候选用例和改写建议入口。
- 候选内容与正式资产隔离；只有点击“写入用例集”才通过现有 API 创建正式
  用例，AI 输出不会直接产生 QA 执行结果。
- 以空间管理数据，每个账号拥有默认质量空间。
- 用例集合新增、查看、编辑、软删除。
- 结构化用例新增、查看、编辑、软删除。
- 用例字段包括编号、名称、模块、类型、优先级、标签、前置条件、执行步骤、
  预期结果和来源。
- 编辑用例时创建新 Revision，不覆盖旧版本。
- 列表与脑图读取同一份用例资产；脑图支持滑动平移、独立缩放、全屏、分支
  折叠、一键隐藏叶子和共同前置条件投影。
- 用例集合和用例资产没有 QA 执行状态；`未执行`、`通过`、`不通过`、`跳过`
  和`堵塞`只属于具体执行任务。
- QA 执行入口展示空间级任务历史、多人进度和结果分布；创建任务只需选择
  集合并填写任务描述。
- QA 可逐步勾选并记录当前任务的执行结果、实际结果和缺陷引用。
- 执行记录锁定执行时的用例 Revision，历史结果不会随用例后续修改而变化。
- 多位空间成员可共同执行；记录采用乐观并发控制，避免静默覆盖他人结果。
- PostgreSQL 持久化业务数据，Redis 作为本地基础设施预留。
- 审计记录覆盖集合、用例 Revision、执行任务和执行记录变更。

## 当前实现边界

- 真实 AI Provider 与服务端异步生成任务。
- 文件内容上传、解析、OCR 与来源定位；当前界面仅管理本地附件上下文。
- 自动应用 AI 改写；当前改写输入作为评审建议，正式变更仍进入结构化编辑。
- 结构化测试说明生成。
- 自动化脚本绑定与执行结果回写。

这些能力仍保留在产品路线图、独立 Agent 和设计文档中，但不会出现在当前
验收页面或 OpenAPI 路由中。

## 验收账号

API 在首次启动时自动创建本地示例账号：

```text
邮箱：demo@casepilot.local
密码：CasePilot123!
```

首次使用该账号进入工作台时，系统会在真实 PostgreSQL 数据库中准备：

- 用例集合：`账号登录验收用例集`
- 登录用例：`AUTH-001 使用正确邮箱与密码登录成功`
- 3 条前置条件
- 3 个执行步骤及对应预期结果

示例数据只在不存在时创建，刷新页面不会重复插入。

## 技术架构

| 组件 | 技术 | 责任 |
| --- | --- | --- |
| Web | React 19、TypeScript、Vinext/Vite | 登录、用例管理和 QA 执行界面 |
| API | FastAPI、SQLAlchemy、Pydantic | 会话、空间、用例和执行 REST API |
| Agent | Python、Celery | 隔离的文件分析、模型 Provider 与生成管线；等待真实 Provider 接入工作台 |
| 数据库 | PostgreSQL 18 | 用例修订、执行任务、执行记录和审计数据 |
| 缓存/队列 | Redis 8 | API 健康依赖、Agent Broker、任务结果和后续事件 |
| 迁移 | Alembic | 数据库结构版本管理 |

## 目录

```text
apps/
  agent/                  独立 Agent、Mock Provider 和测试
  api/                    FastAPI 服务、模型、迁移和测试
  web/                    React Web 应用
docs/
  acceptance-case-management-execution-v0.2.md
  development-progress.md
compose.yaml              本地 Docker Compose
```

## 使用 Docker 启动

要求：

- Docker Desktop 或兼容的 Docker Engine
- Docker Compose V2

复制环境变量并启动：

```bash
cp .env.example .env
docker compose up --build -d
```

打开：

- Web：<http://localhost:3000>
- API 健康检查：<http://localhost:8000/health/ready>
- OpenAPI：<http://localhost:8000/docs>

查看状态：

```bash
docker compose ps
docker compose logs -f web api agent
```

停止服务：

```bash
docker compose down
```

保留数据库数据时不要添加 `-v`。只有确定要清空本地 PostgreSQL 和 Redis
数据时，才执行：

```bash
docker compose down -v
```

## 不使用 Docker 启动

要求：

- PostgreSQL 18（或兼容版本）
- Redis 8（或兼容版本）
- Python 3.13
- Node.js 22+
- pnpm 11

创建本地数据库：

```sql
CREATE USER casepilot WITH PASSWORD 'casepilot-local';
CREATE DATABASE casepilot OWNER casepilot;
```

安装并启动 API：

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r apps/api/requirements-dev.txt
.venv/bin/pip install -r apps/agent/requirements-dev.txt

export DATABASE_URL=postgresql+psycopg://casepilot:casepilot-local@127.0.0.1:5432/casepilot
export REDIS_URL=redis://127.0.0.1:6379/0
export CASEPILOT_WEB_ORIGIN=http://localhost:3000

.venv/bin/alembic -c apps/api/alembic.ini upgrade head
PYTHONPATH=apps/api/src .venv/bin/uvicorn casepilot_api.main:app \
  --host 127.0.0.1 --port 8000
```

可选：在另一个终端启动独立 Agent。当前工作台使用本地候选生成完成前端闭环，
服务端异步生成尚未接入；Agent 可单独验证：

```bash
PYTHONPATH=apps/agent/src \
CELERY_BROKER_URL=redis://127.0.0.1:6379/1 \
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/2 \
  .venv/bin/celery -A casepilot_agent.tasks:celery_app worker --loglevel=INFO
```

再启动 Web：

```bash
cd apps/web
pnpm install
pnpm dev
```

## API 概览

认证：

- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `GET /api/v1/auth/me`
- `POST /api/v1/auth/logout`

用例集合：

- `GET /api/v1/spaces/{space_id}/collections`
- `POST /api/v1/spaces/{space_id}/collections`
- `PATCH /api/v1/collections/{collection_id}`
- `DELETE /api/v1/collections/{collection_id}`

用例：

- `GET /api/v1/collections/{collection_id}/test-cases`
- `POST /api/v1/collections/{collection_id}/test-cases`
- `GET /api/v1/test-cases/{case_id}`
- `PATCH /api/v1/test-cases/{case_id}`
- `DELETE /api/v1/test-cases/{case_id}`

执行：

- `GET /api/v1/collections/{collection_id}/execution-runs`
- `POST /api/v1/collections/{collection_id}/execution-runs`
- `GET /api/v1/execution-runs/{run_id}`
- `PATCH /api/v1/execution-runs/{run_id}`
- `PATCH /api/v1/execution-records/{record_id}`

所有业务接口都要求登录 Cookie，并校验当前账号是否属于目标空间。

## 验收路径

1. 打开 <http://localhost:3000>。
2. 使用示例账号登录。
3. 在“用例管理”查看 `AUTH-001`。
4. 点击编辑，修改任意内容并保存，确认版本从 V1 递增。
5. 打开“执行用例”，确认首先看到当前空间全部任务、进度和参与成员。
6. 新建任务，选择集合并填写任务描述。
7. 逐条勾选步骤，标记本任务执行结果并填写实际结果；其他空间成员可同时参与。
8. 结束任务后确认其只读，并从任务历史重新打开。
9. 刷新页面，确认执行状态、步骤、最后更新成员和实际结果仍然存在。

详细验收标准见
[docs/acceptance-case-management-execution-v0.2.md](./docs/acceptance-case-management-execution-v0.2.md)。

## 本地验证

后端：

```bash
.venv/bin/ruff check apps/api/src apps/api/tests
.venv/bin/pytest apps/api/tests -q
.venv/bin/pytest apps/agent/tests -q
```

前端：

```bash
cd apps/web
pnpm lint
pnpm build
```

## 数据与安全说明

- 密码使用 PBKDF2-SHA256 和随机盐保存，不存储明文密码。
- 会话 Cookie 为 HttpOnly，默认有效期 7 天。
- 删除集合和用例采用软删除，避免直接破坏审计链路。
- 所有更新都会校验空间成员关系。
- 用例更新必须携带 `base_revision_id`，冲突时返回 `409`，防止覆盖他人修订。
- 示例账号只适用于本地验收，生产环境应禁用或替换自动示例账号。

## 许可证

[Apache License 2.0](./LICENSE)
