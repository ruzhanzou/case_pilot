# CasePilot Agent

Agent 是 CasePilot Monorepo 中可独立开发和部署的用例生成服务。它不依赖
`casepilot_api` Python 包，通过任务契约、PostgreSQL 任务记录和 Redis 事件与
平台 API 协作。

## 目录职责

```text
src/casepilot_agent/
├── contracts.py       # 渠道无关的输入、输出和 Provider 协议
├── pipeline.py        # 用例生成工作流
├── providers/         # Mock、真实模型及后续本地模型适配器
├── store.py           # 任务状态和进度事件适配器
└── tasks.py           # Celery 运行入口
```

Agent 当前提供两类任务：

- `casepilot.agent.generate`：需求分析、功能点、测试点、用例、质量检查和落库。
- `casepilot.agent.rewrite`：为单条用例生成可接受或拒绝的候选 Revision。

开发新的模型能力时，实现 `AgentProvider`，然后在
`providers.create_provider()` 中注册。Provider 不应依赖 FastAPI、Teams SDK、
Celery 或平台页面逻辑，因此同一套生成能力可以被 Web、API 和 Teams App 复用。

## 独立开发

在仓库根目录创建虚拟环境并安装 Agent 依赖：

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r apps/agent/requirements-dev.txt
```

运行不依赖数据库和 Redis 的 Agent 单元测试：

```bash
pnpm test:agent
```

连接本地 PostgreSQL 和 Redis 后启动任务进程：

```bash
pnpm dev:agent
```

默认使用 `mock` Provider。使用 OpenAI 兼容服务时设置
`CASEPILOT_AGENT_PROVIDER=openai_compatible`，并配置 Base URL、API Key 和模型名。
该模式通过 OpenAI Agents SDK 的 Chat Completions 适配器调用现有豆包/方舟服务；
默认设置 `CASEPILOT_AGENT_TRACING_ENABLED=false`。
模型密钥仅配置在 Agent 服务。
