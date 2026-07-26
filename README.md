# CasePilot

AI 驱动的测试设计、文本用例管理与测试执行平台。

CasePilot turns requirements into reviewable, structured test cases and provides a
lightweight QA execution workspace.

> 当前版本是可本地部署的开发预览版。AI 生成流程使用独立 Agent 中的确定性 Mock Provider；
> 真实大模型、文件解析、执行历史持久化和生产级安全配置仍在开发中。

## 功能概览

- 以空间管理需求、用例集合和测试资产。
- 通过自然语言与 Word、PDF、Excel、Markdown、图片等材料发起测试设计。
- 展示需求分析、风险识别和分阶段生成进度。
- 以脑图、列表、详情和结构化测试说明复用同一份用例数据。
- 支持单条用例 AI 改写候选、人工评审和五种用例状态。
- 支持 Excel 历史用例导入设计。
- 提供轻量测试执行页：加载集合、逐条确认步骤并记录本次执行结果。
- 用例内容状态与执行结果独立，执行失败不会覆盖已评审的用例状态。

## 技术架构

| 层级 | 技术 | 本地职责 |
|---|---|---|
| Web | React 19、TypeScript、vinext/Vite、Tailwind CSS | 对话、脑图、用例管理和测试执行 |
| API | FastAPI、SQLAlchemy、Alembic | 会话、空间、生成任务和 REST API |
| Agent | Python、Celery | 独立的文件分析、模型 Provider 与用例生成管线 |
| 数据库 | PostgreSQL | 账号、空间、集合、任务等权威数据 |
| 队列/缓存 | Redis | Celery Broker、任务结果、进度事件和短期缓存 |

Redis 数据库分工：

- DB 0：生成进度事件与短期缓存。
- DB 1：Celery Broker。
- DB 2：Celery 任务结果。

## 快速部署：Docker Compose

### 前置条件

- Git
- Docker Desktop，或 Docker Engine + Compose 插件
- 建议至少 4 GB 可用内存
- 本机端口 `3000`、`8000`、`5432`、`6379` 未被占用

### 1. 克隆与配置

```bash
git clone https://github.com/ruzhanzou/case_pilot.git
cd case_pilot
cp .env.example .env
```

`.env.example` 的默认值仅用于本机开发。公开网络部署前必须修改数据库密码，
并根据实际域名调整 `CASEPILOT_WEB_ORIGIN` 和
`NEXT_PUBLIC_CASEPILOT_API_URL`。

### 2. 启动

```bash
docker compose up --build -d
docker compose ps
```

首次启动会自动：

1. 拉取 PostgreSQL、Redis、Node.js 和 Python 基础镜像。
2. 创建 PostgreSQL 与 Redis 命名卷。
3. 执行 Alembic 数据库迁移。
4. 启动 API、Agent Worker 和 Web。

访问地址：

| 服务 | 地址 |
|---|---|
| 产品界面 | http://localhost:3000 |
| REST API | http://localhost:8000 |
| OpenAPI 文档 | http://localhost:8000/docs |
| API 存活检查 | http://localhost:8000/health/live |
| API 就绪检查 | http://localhost:8000/health/ready |

### 3. 查看日志

```bash
docker compose logs -f web api agent
```

### 4. 停止、更新与清理

停止服务但保留数据库和 Redis 数据：

```bash
docker compose down
```

更新代码并重新构建：

```bash
git pull
docker compose up --build -d
```

删除服务及全部本地数据：

```bash
docker compose down -v
```

> `down -v` 会永久删除 PostgreSQL 和 Redis 命名卷，请先确认不需要保留数据。

## 不使用 Docker 的本机部署

### 前置条件

- Node.js `>=22.13`
- pnpm `11.9`
- Python `>=3.13,<3.15`
- PostgreSQL（推荐 16+）
- Redis（推荐 7+）

macOS 可以通过 Homebrew 安装 PostgreSQL 和 Redis：

```bash
brew install postgresql@18 redis
brew services start postgresql@18
brew services start redis
```

### 1. 准备数据库

创建用户和数据库，密码请与本机 `.env` 保持一致：

```bash
createuser --login --pwprompt casepilot
createdb --owner=casepilot casepilot
```

### 2. 安装依赖

```bash
corepack enable
pnpm --dir apps/web install --frozen-lockfile

python3.13 -m venv .venv
.venv/bin/pip install -r apps/api/requirements-dev.txt
.venv/bin/pip install -r apps/agent/requirements-dev.txt
```

复制环境变量：

```bash
cp .env.example .env
```

将 `.env` 中的容器主机名改为本机地址：

```dotenv
DATABASE_URL=postgresql+psycopg://casepilot:casepilot-local@127.0.0.1:5432/casepilot
REDIS_URL=redis://127.0.0.1:6379/0
CELERY_BROKER_URL=redis://127.0.0.1:6379/1
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/2
```

### 3. 执行迁移

```bash
DATABASE_URL=postgresql+psycopg://casepilot:casepilot-local@127.0.0.1:5432/casepilot \
  .venv/bin/alembic -c apps/api/alembic.ini upgrade head
```

### 4. 启动三个进程

终端一，启动 API：

```bash
PYTHONPATH=apps/api/src \
DATABASE_URL=postgresql+psycopg://casepilot:casepilot-local@127.0.0.1:5432/casepilot \
REDIS_URL=redis://127.0.0.1:6379/0 \
  .venv/bin/uvicorn casepilot_api.main:app --host 127.0.0.1 --port 8000
```

终端二，启动 Agent：

```bash
PYTHONPATH=apps/agent/src \
DATABASE_URL=postgresql+psycopg://casepilot:casepilot-local@127.0.0.1:5432/casepilot \
REDIS_URL=redis://127.0.0.1:6379/0 \
CELERY_BROKER_URL=redis://127.0.0.1:6379/1 \
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/2 \
  .venv/bin/celery -A casepilot_agent.tasks:celery_app worker --loglevel=INFO
```

终端三，启动 Web：

```bash
pnpm --dir apps/web dev
```

完成后打开 http://localhost:3000。

## 首次验收

首次运行选择“创建本地账号”，可使用：

- 邮箱：`demo@casepilot.local`
- 密码：`CasePilot123!`

登录后输入：

> 请为手机号验证码登录生成测试用例，覆盖验证码错误、过期和重复提交。

预期可以看到风险分析、生成进度、结构化用例、脑图、用例列表、测试说明和
测试执行入口。完整步骤见
[登录与简单生成验收](./docs/acceptance-login-generation-v0.1.md)。

## 常见问题

### PostgreSQL 或 Redis 端口被占用

如果本机已经运行 PostgreSQL 或 Redis，Docker Compose 可能无法绑定端口。
先停止本机服务，或修改 `compose.yaml` 左侧的宿主机端口。

```bash
lsof -nP -iTCP:5432 -sTCP:LISTEN
lsof -nP -iTCP:6379 -sTCP:LISTEN
```

### API 显示 degraded

检查依赖服务和日志：

```bash
curl http://localhost:8000/health/ready
docker compose ps
docker compose logs api postgres redis
```

### 生成任务没有进度

确认 Agent 和 Redis 正常：

```bash
docker compose logs agent
docker compose exec redis redis-cli ping
```

## 开发与验证

```bash
pnpm --dir apps/web lint
pnpm --dir apps/web test

PYTHONPATH=apps/api/src .venv/bin/pytest apps/api/tests
PYTHONPATH=apps/agent/src .venv/bin/pytest apps/agent/tests
.venv/bin/ruff check apps/api apps/agent
```

## 项目结构

```text
apps/web       Web 产品界面
apps/api       FastAPI、数据库迁移与平台 API
apps/agent     可独立开发部署的 Agent、Provider 与任务入口
docs           产品、调研、交互与开发材料
compose.yaml   本地完整部署编排
```

## 当前边界

- AI Provider 当前为 Mock；模型选择会进入任务快照，但不会调用真实模型。
- 文件上传控件与解析流程处于产品原型阶段。
- 脑图编辑、用例状态和测试执行记录尚未全部服务端持久化。
- Compose 当前面向本地开发与验收，Web 使用开发服务器。
- 直接暴露到公网前，需要补充 TLS、密钥管理、生产 Web 镜像、数据库网络隔离、
  备份恢复、限流和安全审计。

## 产品与设计文档

- [材料索引](./docs/README.md)
- [产品设计 V1.4](./docs/product-design-v1.md)
- [产品规格 V1.4](./docs/product-spec-v1.md)
- [完整工作流与交互设计 V1.4](./docs/product-interaction-design.md)
- [产品逻辑 Review V1.4](./docs/product-logic-review-v1.4.md)
- [轻量测试执行设计 V1.4](./docs/test-execution-design.md)
- [开发基线](./docs/development-baseline-v1.md)
- [开源项目调研](./docs/opensource-research.md)
- [Figma AI Workbench V2.1](https://www.figma.com/design/fRnEKJHcshgCIa1CmYXbLx?node-id=38-2)
- [Figma 测试执行 V1.4](https://www.figma.com/design/fRnEKJHcshgCIa1CmYXbLx?node-id=77-3)

## License

CasePilot 使用 [Apache License 2.0](./LICENSE) 开源。
