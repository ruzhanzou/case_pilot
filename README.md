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
- 空间知识库支持 PDF、DOCX、XLSX/XLS/CSV、MD/TXT、PNG/JPEG；可检索来源保留
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

### Windows 10/11（推荐）

Windows 上推荐使用 Docker Desktop，不建议直接在原生 PowerShell/CMD 中分别安装
PostgreSQL、Redis、Python 和 Celery。

要求：

- 已启用 BIOS/UEFI 硬件虚拟化和 WSL 2；建议 WSL 版本不低于 `2.1.5`
- Docker Desktop 使用 WSL 2 后端，并运行 Linux containers
- Docker Compose `2.24.0` 或更高版本
- Docker Desktop 已启动
- 需要从 GitHub 获取代码时，已安装 Git for Windows

在 PowerShell 中确认环境：

```powershell
wsl --version
docker version
docker compose version
```

如果 Docker Desktop 菜单显示“Switch to Linux containers”，需要先点击它；
如果显示“Switch to Windows containers”，说明当前已经在使用 Linux containers。

尚未获取代码时，在 PowerShell 中克隆仓库；如果已经下载或解压代码，可直接
进入现有项目根目录：

```powershell
git clone --branch main https://github.com/ruzhanzou/case_pilot.git
Set-Location .\case_pilot
```

首次部署且 `.env` 不存在时，复制示例配置，校验 Compose 文件并启动。默认使用
本地 Mock Provider，不需要 API Key；需要连接真实模型时再按后文修改
`.env.local`：

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker compose config --quiet
docker compose up --build -d
```

首次构建需要下载 PostgreSQL、Redis、Python 和 Node.js 镜像，耗时取决于网络。
启动后查看所有服务：

```powershell
docker compose ps -a
```

正常状态应满足：

- `postgres`、`redis` 为 `healthy`
- `api`、`agent`、`cleanup`、`web` 为运行状态
- `migrate` 完成迁移后为 `Exited (0)`

验证服务：

```powershell
curl.exe http://localhost:8000/health/ready
```

然后打开：

- Web：<http://localhost:3000>
- API 健康检查：<http://localhost:8000/health/ready>
- OpenAPI：<http://localhost:8000/docs>

> 当前 `compose.yaml` 面向同一台电脑上的本地验收。Web API 地址和登录跨域来源
> 默认都是 `localhost`，不能直接作为局域网或公网部署方案。PostgreSQL 和 Redis
> 端口也会发布到 Windows 主机，不要在防火墙中向局域网或公网开放 `5432` 和
> `6379`。需要让其他电脑访问时，应另外配置公开访问地址、CORS、反向代理、TLS
> 和正式密码。

### macOS / Linux

要求：

- Docker Desktop 或兼容的 Docker Engine
- Docker Compose `2.24.0` 或更高版本

复制环境变量并启动：

```bash
cp .env.example .env
docker compose config --quiet
docker compose up --build -d
```

### macOS + Colima 部署排障记录

下面汇总一次完整本地部署中实际遇到的问题。默认入口仍是
<http://localhost:3000>；只有明确把 Web 改到其他端口时，才需要同步修改端口和
CORS 配置。

#### 1. Docker 无法下载镜像或域名解析失败

现象通常是拉取 `node`、`postgres` 或 `redis` 镜像时出现 DNS、超时或代理连接
错误。先确认 Colima 和 Docker daemon 正常，再检查虚拟机内的 DNS/代理；宿主机
上的 `127.0.0.1:<代理端口>` 不能直接从 Colima 虚拟机访问，需要使用虚拟机可达
的宿主机地址。

可在 `~/.colima/default/colima.yaml` 中按本机网络填写，例如：

```yaml
docker:
  dns:
    - 192.168.0.1
    - 8.8.8.8
  proxies:
    http-proxy: http://<宿主机地址>:<代理端口>
    https-proxy: http://<宿主机地址>:<代理端口>
    no-proxy: localhost,127.0.0.1,::1,host.docker.internal
```

修改后重启 Colima，再单独拉取一个镜像验证网络：

```bash
colima stop
colima start
docker pull node:24-slim
```

不要照抄示例里的网关、宿主机地址或代理端口；它们随当前 Wi-Fi、VPN 和代理软件
变化。未使用代理时不要配置 `proxies`。

#### 2. Web 容器在 Alpine 中启动失败

前端构建依赖包含原生运行时，镜像使用 `node:24-slim` 的 glibc 环境。
Compose 默认先编译前端，再运行固定构建产物；不挂载源码或运行开发服务器。
更新前端后执行：

```bash
docker compose build web
docker compose up -d --no-deps web
```

API 地址通过构建参数 `NEXT_PUBLIC_CASEPILOT_API_URL` 写入浏览器资源，默认
`http://localhost:8000`。更换地址需要重新构建 Web 镜像，单纯重启不会改变它。
旧版本的前端依赖缓存卷不再使用；不要执行 `docker compose down -v`，否则会
删除 PostgreSQL、Redis 和知识库数据。

#### 3. 本地开发与稳定验收

日常验收使用 Compose 的已编译前端。开发模式依赖实时编译和热更新，不应用作
多人持续使用的服务；一个编译或连接错误可能向所有开发页面推送错误遮罩。
需要编辑界面时，可以单独启动宿主机开发服务器：

```bash
docker compose up -d postgres redis migrate api agent cleanup
pnpm install --frozen-lockfile
NEXT_PUBLIC_CASEPILOT_API_URL=http://localhost:8000 \
  pnpm --dir apps/web dev --hostname 127.0.0.1 --port 13000
```

开发页面使用 `13000` 端口，稳定验收页面仍为 `3000`。开发完成后重新构建 Web
镜像，再从 `3000` 验证正式构建的行为。

#### 4. 浏览器显示 `ERR_CONNECTION_REFUSED`

先核对浏览器地址与实际监听端口。Compose 默认发布 `3000:3000`，因此访问
`127.0.0.1:13000` 会被拒绝，除非已经按上一节把宿主机前端启动在 `13000`。

```bash
docker compose ps -a
curl -I http://127.0.0.1:3000
curl -I http://127.0.0.1:13000
```

固定使用 `13000` 时，也可以将 Web 的 Compose 端口映射改为 `13000:3000`；不要
额外启动一个长期端口转发进程来掩盖配置不一致。

#### 5. API 和数据库健康，但登录提示“本地数据服务尚未就绪”

这是端口改变后最容易误判的问题。先使用正确的健康检查地址：

```bash
curl http://localhost:8000/health/ready
```

返回 `status`、`postgres`、`redis` 均为 `ok`，但 API 日志中的
`OPTIONS /api/v1/auth/login` 是 `400` 时，实际原因通常是 CORS，而不是数据库。
`/health` 并不是本项目的健康检查端点，返回 `404` 属于预期行为。

`CASEPILOT_WEB_ORIGIN` 必须包含浏览器实际使用的端口，并支持用逗号配置多个本地
入口：

```dotenv
CASEPILOT_WEB_ORIGIN=http://localhost:3000,http://localhost:13000
```

修改环境变量后，`docker compose restart` 不会重新读取它，必须重新创建 API
容器：

```bash
docker compose up -d --no-deps --force-recreate api
curl http://localhost:8000/health/ready
```

#### 6. 如何判断 Compose 状态是否正常

- `postgres`、`redis`：应为 `healthy`。
- `api`、`agent`、`cleanup`、`web`：应为运行状态。
- `migrate`：成功迁移后显示 `Exited (0)` 是正常完成，不是崩溃。
- `web` 显示 `Exited (137)`：通常是进程被终止或内存不足，需要检查日志和前端
  依赖缓存。

### 是否需要保存 Docker 镜像

普通本地开发和联网部署不需要执行 `docker save`。`compose.yaml`、Dockerfile、
依赖锁文件和环境变量模板才是可重复部署的来源；下次运行 Compose 会复用本机镜像
或重新构建。

还要注意：`docker save` 只保存镜像，不会保存 PostgreSQL、Redis、知识库文件或
命名卷，因此不能当作业务数据备份。需要备份数据时，应分别导出 PostgreSQL，并
备份对应命名卷。

仅在以下场景才建议保存镜像：

- 需要搬到无法联网或网络不稳定的机器；
- 需要归档一套已经验收过的精确镜像用于回滚或审计；
- 镜像构建成本很高，且目标机器无法访问原镜像仓库。

这时可使用 `docker save -o casepilot-images.tar <镜像名...>`，目标机器用
`docker load -i casepilot-images.tar` 导入。镜像归档通常很大，可能包含运行时
配置痕迹，不应提交到 Git，也不应替代数据库备份。

### 查看日志与停止服务

查看状态：

```bash
docker compose ps -a
docker compose logs -f web api agent
```

Windows PowerShell 和 Bash 使用相同的 Docker Compose 命令。需要排查首次迁移或
依赖启动问题时执行：

```powershell
docker compose logs --tail=200 migrate postgres redis api agent web
```

Windows 端口冲突可在 PowerShell 中检查：

```powershell
Get-NetTCPConnection -LocalPort 3000,8000,5432,6379 -ErrorAction SilentlyContinue
```

如果 `migrate` 不是 `Exited (0)`，先检查 `migrate` 和 `postgres` 日志，不要直接
执行带 `-v` 的清理命令。镜像下载失败时，先检查 Docker Desktop 的网络或代理
配置，再重新执行 `docker compose up --build -d`。

停止服务：

```bash
docker compose down
```

保留数据库数据时不要添加 `-v`。只有确定要清空本地 PostgreSQL 和 Redis
数据时，才执行：

```bash
docker compose down -v
```

## 不使用 Docker 启动（Linux、macOS 或 WSL 2）

以下命令使用 Bash 语法，不能直接在原生 Windows PowerShell/CMD 中执行。
Celery 不官方支持原生 Windows，因此 Windows 用户应优先使用上面的 Docker
Desktop 方案，或在 WSL 2 的 Linux 终端中运行本节命令。

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
.venv/bin/pip install -e 'apps/api[dev]' -e 'apps/agent[dev]'

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

应用同时读取 `.env` 和 `.env.local`；对于本节列出的模型与 Embedding 变量，
`.env.local` 优先级更高且已被 Git 忽略。先复制示例配置。

Windows PowerShell：

```powershell
if (-not (Test-Path .env.local)) { Copy-Item .env.example .env.local }
notepad .env.local
```

Linux、macOS 或 WSL 2：

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
# 意图与范围解析；留空使用上面的默认模型。
CASEPILOT_AGENT_ROUTING_MODEL=
CASEPILOT_AGENT_ROUTING_TIMEOUT_SECONDS=45
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
# 用例批量生成/增强输出更长，单独给予更充足的响应时间。
CASEPILOT_AGENT_GENERATION_TIMEOUT_SECONDS=300
# 非默认模型在结构化生成阶段超过此时间后，立即切换默认模型。
CASEPILOT_AGENT_MODEL_FALLBACK_TIMEOUT_SECONDS=45
# 豆包等非 OpenAI Provider 默认关闭 OpenAI tracing。
CASEPILOT_AGENT_TRACING_ENABLED=false
```

模型变量的作用：

| 变量 | 作用 |
| --- | --- |
| `CASEPILOT_AGENT_MODELS` | 工作台模型下拉框的数据源和服务端允许列表，使用逗号分隔 |
| `CASEPILOT_AGENT_MODEL` | 默认模型，也是未指定或旧任务模型无法解析时的回退模型 |
| `CASEPILOT_AGENT_ROUTING_MODEL` | 意图与范围解析专用模型；留空使用默认模型。实际生成、改写和对改写要求的补充解释仍使用任务所选模型 |
| `CASEPILOT_AGENT_ROUTING_TIMEOUT_SECONDS` | 解析等待窗口，默认 45 秒且不超过通用超时；意图解析关闭 SDK 自动重试，范围纠错重试共用一个窗口。超时进入澄清，不执行写操作 |
| `CASEPILOT_AGENT_PRO_MODEL` | 兼容旧任务中的 `pro`、`test-design-pro` 模型别名 |
| `CASEPILOT_AGENT_LOCAL_MODEL` | 兼容旧任务中的 `local` 模型别名 |
| `CASEPILOT_AGENT_MODEL_FALLBACK_TIMEOUT_SECONDS` | 非默认模型在需求、功能点、测试点、用例与质量修复阶段的首选等待窗口；超时后切换默认模型 |
| `CASEPILOT_AGENT_PROVIDER_LABEL` | 工作台中显示的 Provider 名称 |
| `CASEPILOT_AGENT_TRACING_ENABLED` | 是否开启 Agents SDK tracing；非 OpenAI Provider 默认关闭 |
| `CASEPILOT_EMBEDDING_MODEL` | 知识库索引和语义检索使用的向量模型 |
| `CASEPILOT_EMBEDDING_DIMENSIONS` | 数据库向量维度；`doubao-embedding-vision` 必须配置为 `2048` |

修改配置后重启 API 与 Agent。工作台会通过
`GET /api/v1/generation-models` 动态加载模型，无需重新构建 Web。
使用 Docker Compose 时，API、Agent 和清理服务会自动读取 `.env.local`，
启动阶段也会自动执行 2048 维数据库迁移。

`openai_compatible` 仍使用上述 CasePilot 豆包/方舟 Base URL、密钥和模型名，
但 Chat 编排由 OpenAI Agents SDK 的 `OpenAIChatCompletionsModel` 执行；会话历史
继续以 CasePilot 数据库为唯一上下文源，不启用 SDK Session 的重复持久化。

Docker Compose 用户修改环境变量后，应重新创建相关容器；只执行
`docker compose restart` 不会应用新的环境变量：

```powershell
docker compose up -d --force-recreate api agent cleanup
docker compose logs --tail=100 api agent cleanup
```

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
- `POST /api/v1/test-cases/{case_id}/automation-cases/upload`：上传自动化用例绑定清单，字段和示例见 [接口文档](./docs/automation-case-binding-api.md)。

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

- `GET /api/v1/spaces/{space_id}/test-cases?q={query}`
- `GET /api/v1/spaces/{space_id}/playlists`
- `POST /api/v1/spaces/{space_id}/playlists`
- `GET /api/v1/playlists/{playlist_id}`
- `PATCH /api/v1/playlists/{playlist_id}`
- `DELETE /api/v1/playlists/{playlist_id}`
- `POST /api/v1/spaces/{space_id}/execution-runs`
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

以下开发验证命令使用 Bash 语法，适用于 Linux、macOS 或 WSL 2。Windows
Docker Desktop 部署可先执行 `docker compose ps -a`，再按“验收路径”完成业务
验证。

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
pnpm typecheck
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

### Excel 附件与离线转换

对话附件支持 PDF、TXT、XLSX、XLS；知识库也支持两种 Excel 格式。Excel 使用
openpyxl / xlrd 提取原始数据，再通过 MarkItDown 0.1.8 的本地表格转换器生成 Markdown。
每个工作表按最多 40 个非空行分块，保留工作表名、原始行号和列字母；不做自动数字推断，
文本编号的前导零及 NA/NULL 字面量保留。公式优先读取已保存结果，XLSX 没有缓存结果时
保留公式文本，不执行计算。合并单元格仅保留原始锚点值，不复制到其他单元格；图片、
图表及 Excel 显示格式不在本次解析范围。

安装依赖后，Excel 原文转换本身不联网，不启用远程转换或插件。上传 `.xlsx` / `.xls`
后，在索引阶段使用已配置的 Agent 模型整理用例布局：支持自定义列名、纵向卡片、
合并标题及跨行用例。模型只返回单元格引用，程序按引用提取原文，保留工作表、行范围
和原用例编号；不自动补写缺失预期。解析和整理完成后，附件才变为可用。
模型引用不存在或为空的单元格时，最多重新核对一次；仍不合法的结果列为待核对。

发起参考、复用或改写时，资产确认面板展示识别结果、待核对行和来源预览；完整且
测试对象匹配的用例才可选择。模型超时、模拟模式或单批上下文超出预算时，保留标准
表格解析并明确提示降级；未明确识别的行不自动复用。原始文件仍可查看。
整理按每 40 个非空行处理，读取前后相邻批次作为上下文，每批最多 48,000 字符，
最多两批并行；超长跨批次用例和并排多用例可能需要人工核对。此流程针对新上传的
对话附件与知识库文件；旧文件需重新索引或上传。资产管理页的直接 Excel 导入仍使用
其原有模板规则。向量化和用例生成是否联网也取决于模型配置；部署代码后需重启 worker。

### 对话截图

对话附件支持 PNG/JPEG，可选择图片或在输入区粘贴剪贴板图片（Mac Command+V，Windows Ctrl+V）。图片上传后保留原图，不依赖 OCR；发送时与文字一起传给模型。
API 和 worker 使用相同的 `CASEPILOT_AGENT_IMAGE_MODELS`，值为已确认支持图片输入的模型 ID，逗号分隔。示例环境已启用确认支持视觉理解的 `doubao-seed-2.0-lite`；其他部署仍应按实际端点能力配置，不根据模型名称猜测能力。未支持的模型仍可上传图片，发送前须切换模型或移除图片。单次发送的图片总大小默认不超过 25MB，可通过 `CASEPILOT_AGENT_MAX_IMAGE_BYTES` 调整。修改配置后重启 API 和 worker。
