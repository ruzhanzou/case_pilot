# CasePilot V1.0

CasePilot 是一个可本地部署的 AI 测试设计、正式用例管理与 QA 执行平台。
V1.0 的产品真相以端到端测试为准：

`新对话 → 知识索引 → 阻塞澄清 → 结构化测试说明 → 候选评审 → 纳入正式集合 → QA 执行`

Figma、交互规格和本文档已在 2026-07-30 按这条实际链路重新生成。

- [Figma V1.0 端到端原型](https://www.figma.com/design/fRnEKJHcshgCIa1CmYXbLx?node-id=165-38)
- [Figma V1.0 组件页](https://www.figma.com/design/fRnEKJHcshgCIa1CmYXbLx?node-id=165-30)
- [完整交互规格](./docs/product-interaction-design.md)
- [产品设计](./docs/product-design-v1.md)
- [V1.0 发布与验收记录](./docs/release-v1.0.0.md)

## V1.0 可用能力

- 本地账号注册、登录、退出与持久会话。
- 登录后的默认入口是“今天想测试什么？”；第一条消息自动创建会话和集合，
  不要求用户先理解集合模型。
- 会话历史支持搜索、新建和恢复；恢复时一并恢复测试说明、候选结果与集合上下文。
- 空间知识库支持 PDF、DOCX、XLSX/CSV、MD/TXT、PNG/JPEG；可检索来源保留
  页码、章节、Sheet、行号或段落定位。
- Embedding 不可用时自动降级到全文、需求编号和错误码检索，并明确提示降级，
  不阻塞核心生成链路。
- AI 先生成可审阅的结构化测试说明。缺少测试对象或成功标准时，确认按钮保持
  不可用；用户通过对话补充后才可继续。
- 测试说明确认后生成候选用例；候选支持列表/脑图查看、结构化详情和人工修改。
- 候选与正式资产严格隔离。只有显式点击“纳入正式集合”才创建正式用例 Revision。
- 正式集合支持搜索、列表/脑图、结构化编辑、软删除和修订历史；刷新不会丢失。
- QA 执行只读取正式用例，并冻结发起执行时的 Revision；结果、实际情况、证据和
  缺陷引用只属于当前 Execution Run。
- `未执行`、`通过`、`不通过`、`跳过`和`堵塞`不会写回用例资产状态。
- Chat 与 Embedding Provider 独立配置；默认 Mock 无需密钥，真实环境支持
  OpenAI-compatible 服务。

## V1.0 产品边界

- 已实现结构化测试说明、候选评审、正式资产交接与人工 QA 执行。
- 已实现文件型知识来源；Jira、ADO、Confluence、Drive 等连接器不在 V1.0。
- AI 改写和批量纳入始终经过人工门禁，不自动发布正式用例。
- V1.0 不生成或运行浏览器/API 自动化脚本，也不自动把执行结果回写为资产状态。
- 自动化脚本生成、CI 编排、缺陷系统双向同步和自动发布属于后续版本。

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
| Agent | Python、Celery | 独立执行需求分析、功能点/测试点提取、用例生成与质量检查 |
| 数据库 | PostgreSQL 18 + pgvector/pg_trgm | 用例修订、知识检索、阶段产物和审计数据 |
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

在另一个终端启动独立 Agent。默认使用 Mock Provider，不需要 API Key：

```bash
PYTHONPATH=apps/agent/src \
CELERY_BROKER_URL=redis://127.0.0.1:6379/1 \
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/2 \
  .venv/bin/celery -A casepilot_agent.tasks:celery_app worker --loglevel=INFO
```

### 配置火山方舟模型

项目同时读取 `.env` 和 `.env.local`，后者优先级更高且已被 Git 忽略。
先复制示例配置：

```bash
cp .env.example .env.local
```

在 `.env.local` 中设置以下内容，并将密钥占位符替换为自己的方舟
Coding Plan API Key：

```dotenv
CASEPILOT_AI_MODE=real
CASEPILOT_AGENT_PROVIDER=openai_compatible
CASEPILOT_AGENT_PROVIDER_LABEL=火山方舟 Coding Plan
CASEPILOT_AGENT_BASE_URL=https://ark.cn-beijing.volces.com/api/coding/v3
CASEPILOT_AGENT_API_KEY=替换为你的服务端密钥

# 默认模型与工作台可选模型；逗号顺序就是下拉框显示顺序。
CASEPILOT_AGENT_MODEL=doubao-seed-2.0-lite
CASEPILOT_AGENT_PRO_MODEL=deepseek-v4-pro
CASEPILOT_AGENT_LOCAL_MODEL=ark-code-latest
CASEPILOT_AGENT_MODELS=ark-code-latest,doubao-seed-2.0-lite,glm-5.2,kimi-k2.7-code,deepseek-v4-pro,deepseek-v4-flash,minimax-m3,minimax-m2.7,kimi-k2.6,doubao-seed-2.1-turbo

# 知识库向量模型；留空 CASEPILOT_EMBEDDING_API_KEY 时复用 Agent 密钥。
CASEPILOT_EMBEDDING_PROVIDER=openai_compatible
CASEPILOT_EMBEDDING_BASE_URL=https://ark.cn-beijing.volces.com/api/coding/v3
CASEPILOT_EMBEDDING_API_KEY=
CASEPILOT_EMBEDDING_MODEL=doubao-embedding-vision
CASEPILOT_EMBEDDING_DIMENSIONS=2048
CASEPILOT_EMBEDDING_TIMEOUT_SECONDS=60
CASEPILOT_EMBEDDING_FALLBACK_ENABLED=true
CASEPILOT_AGENT_TIMEOUT_SECONDS=120
```

模型变量的作用：

| 变量 | 作用 |
| --- | --- |
| `CASEPILOT_AGENT_MODELS` | 工作台模型下拉框的数据源和服务端允许列表，使用逗号分隔 |
| `CASEPILOT_AGENT_MODEL` | 默认模型，也是未指定或旧任务模型无法解析时的回退模型 |
| `CASEPILOT_AGENT_PRO_MODEL` | 兼容旧任务中的 `pro`、`test-design-pro` 模型别名 |
| `CASEPILOT_AGENT_LOCAL_MODEL` | 兼容旧任务中的 `local` 模型别名 |
| `CASEPILOT_AGENT_PROVIDER_LABEL` | 工作台中显示的 Provider 名称 |
| `CASEPILOT_EMBEDDING_MODEL` | 知识库索引和语义检索使用的向量模型 |
| `CASEPILOT_EMBEDDING_DIMENSIONS` | 数据库向量维度；`doubao-embedding-vision` 必须配置为 `2048` |

修改配置后重启 API 与 Agent。工作台会通过
`GET /api/v1/generation-models` 动态加载模型，无需重新构建 Web。
使用 Docker Compose 时，API、Agent 和清理服务会自动读取 `.env.local`，
启动阶段也会自动执行 2048 维数据库迁移。

若向量接口不可用且降级开关为 `true`，资料仍会标记为可检索，但界面会显示
“仅全文检索”。密钥只应配置在 API/Agent 服务端环境中，不要放入 Web 环境
或提交到仓库。

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

AI 生成：

- `POST /api/v1/generation-jobs`
- `GET /api/v1/generation-jobs/{job_id}`
- `GET /api/v1/generation-jobs/{job_id}/events`
- `POST /api/v1/generation-jobs/{job_id}/answers`
- `POST /api/v1/generation-jobs/{job_id}/retry`
- `POST /api/v1/test-cases/{case_id}/candidate-revisions`

空间知识库：

- `POST /api/v1/spaces/{space_id}/knowledge-sources`
- `GET /api/v1/spaces/{space_id}/knowledge-sources`
- `POST /api/v1/spaces/{space_id}/knowledge-documents`
- `POST /api/v1/knowledge-sources/{source_id}/reindex`
- `DELETE /api/v1/knowledge-sources/{source_id}`

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
3. 在“空间知识库”上传需求并等待状态变为“可检索”。
4. 回到“AI 用例工作台”，从新对话发送含阻塞歧义的需求。
5. 在对话中补齐测试对象与成功标准，确认“结构化测试说明”。
6. 评审候选并点击“纳入正式集合”，刷新后确认正式 Revision 可读取。
7. 在“用例管理”编辑用例，确认版本递增。
8. 从正式用例打开“执行用例”，记录步骤、结果、证据和缺陷引用。

V1.0 的产品真相、Figma 节点和自动化结果见
[docs/release-v1.0.0.md](./docs/release-v1.0.0.md)。

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
CASEPILOT_E2E_BASE_URL=http://localhost:3000 pnpm exec playwright test
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
