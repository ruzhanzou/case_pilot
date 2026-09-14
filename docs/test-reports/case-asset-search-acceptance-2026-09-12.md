# 用例资产模糊搜索端到端验收报告

- 验收日期：2026-09-12；集合搜索扩展复验：2026-09-14
- 验收环境：本地 Docker Compose（Web `localhost:3000`、API `localhost:8000`、PostgreSQL 18）
- 验收结论：通过

## 验收范围

验证用例管理页面能够基于用例基础字段、`test_target` 和创建人进行不区分大小写的模糊搜索，并支持多个关键词组合匹配与零结果反馈。集合搜索扩展覆盖左侧空间集合列表，且与右侧集合内用例搜索相互独立。

## 构造数据

通过 `scripts/seed_case_search_acceptance.py` 调用真实注册、成员管理、Case Project 和正式用例 API 构造隔离数据。

| 数据 | 值 |
| --- | --- |
| Case Project | `CP-00036` |
| 集合 | 统一登录搜索验收 |
| Target type | `fr_test` |
| Target ID | `1789145010` |
| Target key | `FR-SEARCH-145010` |
| 关联 FR | `1789145010`、`FR-LINK-5010` |
| 关联 QPM | `QPM-LINK-5010` |
| 用例 1 | `SEARCH-145010-001` / 统一登录主链路 / 李四·搜索验收 |
| 用例 2 | `SEARCH-145010-002` / 统一登录异常恢复 / 张三·搜索验收 |

## 验收结果

| 编号 | 场景 | 输入 | 期望 | 结果 |
| --- | --- | --- | --- | --- |
| E2E-01 | 资产元数据展示 | 无 | 两条用例展示 Test target 和创建人 | 通过 |
| E2E-02 | Test target 部分匹配 | `SEARCH-145` | 命中两条关联目标用例 | 通过 |
| E2E-03 | 创建人中文模糊匹配 | `张三` | 仅命中张三创建的异常恢复用例 | 通过 |
| E2E-04 | 多字段组合搜索 | `FR-SEARCH-145010 张三` | 两个关键词均匹配，仅返回一条用例 | 通过 |
| E2E-05 | 零结果状态 | `不存在的目标 李四` | 返回 0 条并展示空状态 | 通过 |
| E2E-06 | 用例集合 Test target 搜索 | `SEARCH-145` | 左侧仅保留关联目标的集合 | 通过 |
| E2E-07 | 集合跨字段组合搜索 | `FR-SEARCH-145010 李四` | Target 与创建人均匹配时返回集合 | 通过 |
| E2E-08 | 集合零结果状态 | `不存在的集合` | 左侧返回 0 条并展示集合空状态，右侧用例不受影响 | 通过 |
| API-01 | 后端目标及创建人匹配规则 | target type、部分 ID、target key、QPM ID、姓名、邮箱组合 | 匹配结果符合 AND 语义 | 通过 |
| API-02 | 真实数据库 API 回归 | 创建人姓名及邮箱片段 | 空间级搜索返回对应正式用例 | 通过 |

## 自动化结果

- Playwright：集合搜索扩展最终回归 `1 passed (6.5s)`；覆盖集合及用例搜索页面状态，业务 API 无失败响应。
- Pytest：`3 passed in 2.78s`；覆盖集合/用例搜索规则单元测试及 PostgreSQL 集成回归。
- Web 构建、TypeScript 类型检查、ESLint：通过。

## 截图证据

1. [完整资产列表](../../artifacts/case-search-acceptance/01-case-assets-baseline.png)
2. [Test target 模糊搜索](../../artifacts/case-search-acceptance/02-test-target-fuzzy-search.png)
3. [创建人模糊搜索](../../artifacts/case-search-acceptance/03-creator-fuzzy-search.png)
4. [Test target + 创建人组合搜索](../../artifacts/case-search-acceptance/04-combined-search.png)
5. [零结果状态](../../artifacts/case-search-acceptance/05-empty-result.png)
6. [用例集合组合搜索](../../artifacts/case-search-acceptance/06-collection-search.png)
7. [用例集合零结果状态](../../artifacts/case-search-acceptance/07-collection-search-empty.png)

## 验收备注

首次浏览器运行命中了重启前的旧 Web 页面，重新加载 Web 容器后页面使用最新代码；随后完整用例连续通过。该问题属于验收环境热更新状态，不是产品逻辑缺陷。

正式验收未发现阻塞问题。测试数据保留在本地验收数据库中，便于后续人工复核。
