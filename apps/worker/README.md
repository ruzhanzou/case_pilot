# CasePilot Worker

异步 Worker 与 API 共享 `casepilot_api` 领域包，通过 Celery 执行文件解析、Mock AI、真实 AI、质量检查和文档导出任务。

当前 M0 只注册 `casepilot.mock.generate`，真实模型 Provider 将在后续里程碑接入。
