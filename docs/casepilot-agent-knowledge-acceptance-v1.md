# CasePilot 用例生成 Agent 与空间知识库验收记录

验收日期：2026-07-28
实现版本：Alembic `20260728_0008`

## 验收范围

本轮将原来一次模型调用升级为可暂停、可恢复、可追溯的编排式 Agent，并交付
空间知识库 MVP：

```text
上传资料
→ 解析/OCR/结构切片
→ pgvector + pg_trgm + 精确匹配 + RRF
→ 需求分析
→ 阻塞问题暂停/回答
→ 功能点
→ 测试点与覆盖矩阵
→ 分批用例
→ 定向增强
→ 确定性与语义质量检查
→ 人工选择
→ 正式 TestCase Revision
```

## 实际验收结果

### 数据库无损升级

使用已有 PostgreSQL 18 数据库从 `20260728_0007` 升级到
`20260728_0008`。升级前后计数一致：

| 资产 | 升级前 | 升级后 |
| --- | ---: | ---: |
| 账号 | 2 | 2 |
| 用例集合 | 5 | 5 |
| 正式用例 | 65 | 65 |
| Revision | 68 | 68 |
| 执行任务 | 2 | 2 |
| 执行记录 | 24 | 24 |
| 历史生成任务 | 24 | 24 |

扩展检查：`vector 0.8.5`、`pg_trgm 1.6`。
新增表检查：5/5（知识来源、文档、切片、任务阶段、阶段证据）。

### 自动化测试

| 检查 | 结果 |
| --- | --- |
| Python Ruff（API + Agent） | 通过 |
| Agent pytest | 18 passed |
| API pytest | 18 passed |
| Web ESLint | 通过 |
| Web build | 通过 |
| Web rendered HTML tests | 2 passed |
| Playwright 端到端 | 1 passed，5.5 秒 |

Agent 自动化覆盖结构化切片、Parent/Child、中文预分词、确定性 2048 维
Embedding、分阶段顺序、阻塞暂停/回答恢复、两轮增强上限、质量错误阻断、
模型映射、结构重试和 Embedding 维度。

### API + Worker 端到端

使用 FastAPI、Redis、Celery 和确定性 Mock Provider 实际执行：

1. 登录示例账号。
2. 上传 Markdown 支付需求并等待索引完成。
3. 检索知识切片并保存阶段证据。
4. 触发阻塞问题，任务进入 `awaiting_input`。
5. 提交回答，任务从需求分析恢复。
6. 生成 1 个功能点、2 个测试点和 2 条候选用例。
7. 所有候选均包含可解析的文档、定位和摘录引用。
8. 质量规则通过；与正式集合疑似重复时只产生 warning。
9. 人工选择候选并通过批量接口写入。
10. 刷新集合，正式用例与 Revision 1 可读取。

阶段顺序：

```text
context.prepared
requirement.analyzed
requirement.analyzed（回答后重新执行）
feature.generated
test_point.generated
test_case.generated
enhancement.completed
quality.completed
```

SSE 另行验证了完整 8 个事件和 `Last-Event-ID` 续传；回答时会清理上一段
已终止事件流，避免新连接再次停在旧的 `generation.awaiting_input`。

### Playwright 浏览器验收

浏览器自动完成：

```text
登录
→ 打开知识库
→ 上传需求
→ 等待“可检索”
→ 回到 AI 工作台
→ 提交阻塞需求
→ 回答问题
→ 查看质量提醒
→ 写入候选
→ 刷新
→ 在用例管理确认正式资产
```

登录后的浏览器控制台错误：0。

Embedding 降级专项动线使用生产 Web 构建重新验收，Playwright `1 passed`，
业务场景耗时 9.3 秒。录屏文件：
`artifacts/casepilot-embedding-fallback-acceptance-20260728.webm`。

## 千问真实路径

已使用用户指定的 OpenAI-compatible 网关完成真实连通验收：

- Base URL：`https://api.0x7e.vip/v1`
- Chat 模型：`Qwen3.7-MAX`
- `/v1/models`：HTTP 200，模型精确匹配
- `/v1/chat/completions`：HTTP 200，结构化 JSON 合法
- 实际返回模型：`Qwen3.7-MAX`
- 本次延迟：7,657 ms
- Usage：返回 prompt、completion 和 total token

密钥仅保存在被 Git 忽略且权限为 `0600` 的本地 `.env`，没有写入受版本控制
文件。

Chat 与 Embedding Provider 已拆分为独立配置。知识库 Embedding 尚未通过
该网关验收：密钥的 `/v1/models` 只返回 `Qwen3.7-MAX`，调用
`text-embedding-v4` 返回 HTTP 403（未授权该模型）。

降级路径已使用真实接口验证：

1. `Qwen3.7-MAX` 完成结构化 `requirement.analyzed`，Schema 合法并返回 Usage。
2. Embedding 真实请求返回 403。
3. `context.prepared` 没有失败，以 `lexical` 模式完成。
4. 阶段产物包含 `embedding_retrieval_degraded` warning。
5. 确定性整链路回归继续完成功能点、测试点、用例、增强与质量检查。
6. 已有用例仍执行标题精确去重；语义去重跳过并产生 warning。

真实千问多阶段烟测完成了阻塞问题暂停、回答恢复、功能点、测试点和用例生成；
最后一次 `enhancement.completed` 请求在网关侧超过 120 秒读取超时。该超时与
Embedding 降级无关，未将其记录为真实全流程通过。

若后续提供独立的 OpenAI-compatible Embedding 地址、模型与密钥，只需设置
`CASEPILOT_EMBEDDING_PROVIDER`、`CASEPILOT_EMBEDDING_BASE_URL`、
`CASEPILOT_EMBEDDING_API_KEY` 和 `CASEPILOT_EMBEDDING_MODEL`，无需修改
千问 Chat 配置。

## 环境说明

`docker compose config` 已通过。Docker 客户端存在，但本机 Docker daemon 未
启动，因此本次无法执行 Compose 全量重建和容器健康检查；改用本机
PostgreSQL 18、Redis、隔离 Python 环境、真实 API/Worker 进程和浏览器完成
功能验收。启动 Docker Desktop 后应补跑：

```bash
docker compose up --build -d
docker compose ps
curl http://localhost:8000/health/ready
```
