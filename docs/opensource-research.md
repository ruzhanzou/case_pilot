# AI 驱动的测试设计与文本用例管理平台：开源项目调研

> 调研日期：2026-07-19
> 调研目标：提取可复用的产品与工程设计，不复制或整合开源代码。
> 证据口径：以项目官方仓库、仓库内文档和 Kiwi TCMS 官方文档为主；“未发现”表示在本次公开资料与主分支文档中未找到明确支持，不等于项目永远不具备该能力。

## 1. 结论摘要

这八个项目不是八种彼此替代的方案，而是覆盖了四个互补层次：

1. **产品工作台与 AI 需求链路**：`presidio-oss/specif-ai` 最接近“需求 → 用户故事 → 测试用例”的产品形态。
2. **测试资产与执行域模型**：`kiwitcms/Kiwi`、`tcms-api`、`pytest-plugin` 提供成熟的 Plan / Case / Run / Execution 分层、人工评审门禁和执行回写经验。
3. **结构化 AI 流程**：`ai-testcase-generation-engine` 展示了最小可行的“抽取 → 生成 → 覆盖分析 → 导出”流水线；`qa-skills` 则给出更完整的“风险、覆盖矩阵、Oracle、代码、人工审核”方法论。
4. **MCP 与本地 Agent**：`specifai-mcp-server` 展示本地文件型知识库的只读 MCP；`browserstack/mcp-server` 展示远端平台的细粒度 MCP 写工具、本地/远端能力差异和“建议修复但不自动改代码”的安全边界。

推荐方案不是 fork 某一个仓库，而是**重新实现一个平台内核**，分别参考：

- 产品设计：Specifai；
- 数据模型：Kiwi TCMS；
- AI 设计流程：qa-skills 为主，AI Test Case Generation Engine 为最小流水线参考；
- MCP / Agent：Specifai MCP 的轻量只读模式 + BrowserStack MCP 的工具粒度与安全门禁；
- 自动化回写：Kiwi `tcms-api` / `pytest-plugin` 的适配器模式。

## 2. 评估口径

### 2.1 能力标记

- **●**：原生、明确支持；
- **◐**：部分支持、间接支持，或只在配套商业平台/外部系统中成立；
- **○**：未发现原生支持；
- **—**：该能力不属于项目定位，不应据此判断项目质量。

### 2.2 “版本管理”定义

本报告区分三种容易混淆的能力：

- **审计历史**：知道谁在何时改了什么，可能支持回滚；
- **生成批次历史**：AI 重生成时保留旧批次；
- **语义版本**：一个用例具有可寻址的 revision，执行结果固定绑定某一 revision，并支持差异、基线和分支/合并。

八个项目中没有一个完整覆盖第三种能力；这是当前产品需要自行设计的核心差异点。

## 3. 能力对比表

| 项目 | 需求管理 | AI 需求分析 | 测试点生成 | 文本用例管理 | AI 用例生成 | 人工评审 | 版本管理 | 需求追踪 | REST API | MCP | 本地 Coding Agent | 自动化绑定 | 执行结果回写 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| presidio-oss/specif-ai | ● | ● | ◐ | ● | ● | ◐ | ◐ | ● | ○ | ◐（作为 MCP Client） | ◐（经配套 MCP） | ◐（任务/Jira/ADO，非测试代码强绑定） | ○ |
| presidio-oss/specifai-mcp-server | ◐（只读暴露） | ○ | ○ | ◐（读取 TC 文档） | ○ | ○ | ◐（继承本地文件历史） | ● | ○ | ● | ● | ◐（Task/文档供 Agent 使用） | ○ |
| kiwitcms/Kiwi | ○ | ○ | ○ | ● | ○ | ● | ◐（审计/回滚，不是用例 revision 模型） | ◐（requirement 字段、Plan/Case 关联） | ◐（JSON/XML-RPC，**非 REST**） | ○ | ○ | ● | ● |
| kiwitcms/tcms-api | ○ | ○ | ○ | ◐（客户端操作） | ○ | ○ | ○ | ◐ | ◐（RPC 客户端，**非 REST**） | ○ | ◐（可被本地工具调用） | ● | ● |
| kiwitcms/pytest-plugin | ○ | ○ | ○ | ◐（从测试项创建/复用 Case） | ○ | ○ | ○ | ○ | ○ | ○ | ◐（pytest 本地进程） | ● | ● |
| rohitpkumar/ai-testcase-generation-engine | ◐（读取 PRD） | ● | ● | ○（仅 CSV） | ● | ○ | ○ | ●（requirement_id） | ○ | ○ | ●（CLI/本地脚本） | ○ | ○ |
| browserstack/mcp-server | ○ | ◐（PRD 文件交给商业 AI Agent） | ◐ | ●（BrowserStack TM） | ●（依赖 BrowserStack 服务） | ◐（平台状态/审批；代码修复需确认） | ◐（依赖商业平台） | ◐ | ◐（底层调用 BrowserStack API，不对外提供通用 REST） | ● | ● | ● | ● |
| petrkindlmann/qa-skills | ◐（读取 PRD/Story/Spec） | ● | ● | ◐（提供管理方法，不是平台） | ● | ● | ◐（建议记录模型、输入 hash、技能版本） | ● | ○ | ◐（可指导使用 MCP） | ● | ●（生成标准测试代码及追踪注释） | ◐（指导 CI/报告，不是中心服务） |

### 3.1 对表格的关键解释

- Kiwi 的“API”是 XML-RPC / JSON-RPC，官方 Python 包 `tcms-api` 是 RPC 客户端，不能在架构文档中误称为 REST。
- Specifai 自身支持接入外部 MCP Server；`specifai-mcp-server` 是反方向的配套组件，把 Specifai 的本地文档提供给 Cursor、VS Code、Claude Desktop 等客户端。
- BrowserStack MCP 的 AI 生成、执行和回写依赖 BrowserStack 商业服务；开源仓库不是独立的测试管理后端。
- qa-skills 是 Agent Skills 内容库，不是多用户、持久化、带权限的测试管理平台。

## 4. 分项目分析

## 4.1 presidio-oss/specif-ai

官方资料：[仓库与 README](https://github.com/presidio-oss/specif-ai)、[核心功能](https://github.com/presidio-oss/specif-ai/blob/main/docs/docs/current/core-features.md)、[AI 生成内容流程](https://github.com/presidio-oss/specif-ai/blob/main/docs/docs/current/ai-generated-content.md)、[需求类型](https://github.com/presidio-oss/specif-ai/blob/main/docs/docs/current/requirement-types.md)。

### 项目定位

AI 驱动的 SDLC 需求工作台。它从 Solution 元数据和上下文生成 BRD、PRD、NFR、UIR，继续派生 User Story、Task 和 Test Case，并支持聊天、行内 AI 编辑、Jira / Azure DevOps 集成。其主要价值是把“生成”嵌入结构化产品流程，而不是提供一个独立聊天框。

### 技术栈

- TypeScript 为主；Angular UI + Electron 桌面容器；
- 本地文件系统保存/组织生成文档；
- LangGraph 编排 agentic workflow；
- 多模型供应商：OpenAI/Azure OpenAI、Anthropic、Bedrock、Gemini、OpenRouter、Ollama；
- 可选 Langfuse、PostHog；
- 自身作为 MCP Client，可接 AWS Bedrock Knowledge Base 或自定义 MCP Server。

### 核心数据对象

- `Solution`：项目名称、描述、技术栈、工作目录和上下文根；
- 文档：`BRD`、`PRD`、`NFR`、`UIR`、Business Process Document；
- 执行分解：`UserStory`、`Task`；
- 质量资产：`TestCase`，关联 User Story，并间接追溯 PRD；
- Strategic Initiative、外部研究 URL、MCP 配置；
- 生成批次/归档对象：重生成前的 Story、Task、Test Case 被归档。

公开文档更强调 JSON/文件文档而非关系数据库约束；因此它适合参考信息架构，但不宜直接视作成熟的测试域数据库模型。

### 页面和用户流程

典型路径：

1. Welcome / 工作目录设置；
2. 创建 Solution，录入描述和技术栈；
3. 生成并编辑 BRD / PRD / NFR / UIR；
4. 连接 BRD 与 PRD，使用 Chat 或 Inline Edit 细化内容；
5. 在 PRD 上点击 Generate Stories，弹窗补充上下文；
6. 查看 Story 及其自动生成的 Tasks；
7. 从 Story 进入 Test Cases 列表，点击 Generate Test Cases；
8. 补充涉及页面和额外上下文；
9. 查看、编辑、导出或同步到外部系统。

这个流程非常适合当前产品借鉴：**AI 动作出现在对象列表/详情页的明确位置，并在执行前要求用户补上下文**。

### AI 生成流程

- 需求生成：先汇总 Solution 元数据与对话，再通过知识库/MCP 获取上下文，整理为结构化 `ReferenceInfo`，最后生成多类需求文档；
- Story/Task：选择 PRD → 补充上下文 → agentic flow 生成 Story → 对每个 Story 继续生成 Task；
- Test Case：选择 Story → 补充 UI Screens 和 Extra Context → 三阶段 Agentic Flow → 生成 prerequisites、steps、expected results、alternative flows；
- 重生成：旧对象归档，新对象作为新批次生成，保持历史追踪；
- 质量目标：覆盖 functional、integration、edge、negative，并由 AI 做完整性/最佳实践检查。

公开文档没有把三阶段的每个内部节点、评分器和失败恢复协议完全展开，不能把“3-Phase”理解成已验证的通用算法。

### API 或 MCP 设计

- 主应用公开资料以桌面/本地文件交互为主，未发现稳定的公共 REST API 合约；
- 应用是 MCP Client：Integrations 页面统一配置内置和自定义 MCP Server；
- 对 Jira/ADO 做双向同步，但这是业务集成，不等同于平台公共 API；
- 由独立 `specifai-mcp-server` 对外提供文档读取 MCP。

### 平台与本地 Agent 的边界

- Specifai 桌面端负责文档生成、编辑、关联和本地持久化；
- Coding Agent 通过 MCP 读取已形成的需求、Story、Task、Test Case，并在代码仓库内执行实现；
- 当前边界偏“本地文件即交换层”，缺少中心平台的租户权限、审批令牌、幂等写入和执行回写协议。

### 人工审核机制

有 Chat、Inline Edit、列表/详情编辑以及生成前的上下文补充，体现 human-in-the-loop；但公开资料未发现强制的 Reviewer、审批状态机、逐条接受/拒绝、评审意见闭环或发布门禁。它更像“人工可编辑”，还不是“受治理的人工评审”。

### 用例版本管理能力

- 重生成时归档上一批 Test Case，具备生成批次历史；
- 文档位于本地工作目录，可由 Git、OneDrive、Dropbox 等外部机制管理；
- 未发现一等公民的 `TestCaseRevision`、差异视图、基线、分支/合并，以及 Test Execution 固定绑定 revision 的设计。

### 自动化绑定方式

主要链路是 Story → Task → Coding Agent/外部工作项；测试用例与自动化脚本的稳定 ID、仓库路径、框架 node id、commit SHA 等绑定未形成成熟模型。

### 可以复用的设计

- Solution → PRD → Story → Test Case 的渐进式信息架构；
- 在生成前用弹窗收集页面、额外约束和知识库范围；
- Chat、Inline Edit 和结构化表单三种 AI 入口并存；
- 重生成先归档、后新建，避免覆盖旧结果；
- MCP 集成统一在 Integrations 页面管理；
- 多模型 Provider 抽象和可观测性开关；
- 生成对象直接保留上游关系，实现追溯导航。

### 不适合当前产品的部分

- Electron + 本地文件是单机优先架构，不适合作为多用户 SaaS 的唯一真相源；
- BRD/NFR/UIR 的宽 SDLC 范围可能稀释“测试设计与文本用例管理”的核心；
- 文件级版本控制无法替代对象级 revision 与执行快照；
- 当前人工审核较软，缺乏发布门禁；
- 测试执行、自动化绑定和结果回写不是核心能力。

### 开源许可证风险

MIT，代码复用风险低，但仍需保留版权与许可文本；项目名称、Logo、服务商商标不随 MIT 自动授权。即使许可证宽松，也不建议 fork：产品范围、桌面架构和目标平台的中心化需求差异较大。

## 4.2 presidio-oss/specifai-mcp-server

官方资料：[仓库与工具清单](https://github.com/presidio-oss/specifai-mcp-server)、[架构指南](https://github.com/presidio-oss/specifai-mcp-server/blob/main/docs/dev/03-architecture-guide.md)。

### 项目定位与技术栈

面向 Cursor、VS Code、Windsurf、Claude Desktop 等 MCP Client 的本地 stdio Server。TypeScript/Node.js（也支持 Bun），使用 MCP SDK，服务按 Server Service、Document Service、File Service 分层。

### 核心数据对象

自身不建立新的业务数据库，读取 Specifai 工作目录中的 Solution 文档：BRD、PRD、NFR、UIR、BPD、Test Case、User Story、Task。`.specifai-path` 保存目标工作目录的绝对路径。

### 页面和用户流程

无独立业务页面。用户通过 npx 安装，在 IDE/MCP Client 配置 stdio server；可选择用 `.specifai-path` 固定项目目录，然后在 Agent 对话中检索需求或任务。

### AI 生成流程

不负责 AI 生成。它把结构化上下文交给宿主 Agent，生成和代码修改由 MCP Client/Agent 完成。

### API 或 MCP 设计

主要工具：`get-brds`、`get-prds`、`get-nfrs`、`get-uirs`、`get-bpds`、`get-tcs`、`get-user-stories`、`get-tasks`、`get-task`、`get-task-by-id`、`list-all-tasks`、`search`、`set-project-path`。

设计特点：

- stdio、本地运行、无需中心服务；
- 按文档类型提供小工具，而不是一个万能 query；
- 读路径为主，降低 Agent 误写需求真相源的风险；
- Server → Document → File 三层隔离协议、业务解析和文件访问；
- `set-project-path` 是有状态配置，便于多项目切换，但绝对路径文件的可移植性和隐私需谨慎。

### 平台与本地 Agent 的边界

本地 MCP 只负责发现、解析、搜索需求文档；Agent 负责理解上下文和修改代码。它没有平台认证、审批和写回，因此适合作为“本地只读桥”，不适合作为完整平台 MCP。

### 人工审核、版本、自动化绑定

- 不提供人工评审；
- 版本能力继承文件系统/Git；
- Task/Test Case 可成为 Agent 上下文，但没有脚本绑定实体；
- 没有执行结果回写。

### 可以复用的设计

- 本地 stdio sidecar；
- 只读默认、按对象类型拆工具；
- 统一全文搜索；
- 服务分层；
- 项目目录显式选择，而不是扫描整台机器；
- MCP Server 与主产品独立发布。

### 不适合当前产品的部分

- 依赖绝对路径和特定文件布局；
- 没有远端身份、租户和权限；
- 工具返回可能是大文档，不利于分页、字段选择和 token 成本；
- 没有写入、审核、幂等和冲突检测协议。

### 开源许可证风险

MIT，风险低；保留版权和许可声明。项目 README 明确标记 experimental，工具契约可能变化，不应直接把它作为平台稳定协议。

## 4.3 kiwitcms/Kiwi

官方资料：[仓库](https://github.com/kiwitcms/Kiwi)、[数据组织与工作流](https://kiwitcms.readthedocs.io/en/stable/guide/introduction.html)、[测试用例与评审](https://kiwitcms.readthedocs.io/en/latest/guide/testcase.html)、[测试运行](https://kiwitcms.readthedocs.io/en/stable/guide/testrun.html)、[RPC API](https://kiwitcms.readthedocs.io/en/latest/modules/tcms.rpc.api.html)。

### 项目定位

成熟的开源测试用例管理系统，覆盖手工与自动化测试、计划、执行、缺陷、报表、权限和插件。它不是 AI 产品，但在“测试资产如何成为组织真相源”方面最有参考价值。

### 技术栈

- Python / Django 单体应用；
- PostgreSQL 等关系数据库；
- Web UI 使用 JavaScript 与 PatternFly 体系；
- 容器、Helm、邮件、外部缺陷系统集成；
- XML-RPC 和 JSON-RPC；
- Django 权限、历史审计和插件生态。

### 核心数据对象

- 分类域：`Classification` → `Product` → `Version` → `Build`；
- 组织域：`Component`、`Category`、`Priority`、`Tag`、`Property`、User/Group/Permission；
- 设计域：`TestPlan`、`TestCase`、Plan-Case 关联和排序；
- 执行域：`TestRun`、`TestExecution`、`TestExecutionStatus`；
- 缺陷域：Bug System、Bug/LinkReference、Comment、Attachment；
- TestCase 字段包括 summary、text、requirement、notes、priority、status、author、reviewer、default tester、is_automated、script、arguments、extra_link、setup/testing duration。

最重要的模型原则是：**TestCase 描述可复用场景；TestRun 表示针对某一 Build 的一轮工作；TestExecution 是 Case 在该 Run 中的执行实例和状态容器。**

### 页面和用户流程

1. 管理 Product / Version / Build 和分类数据；
2. 创建 Test Plan；
3. 新建、搜索、复用或克隆 Test Case，并加入 Plan；
4. 在 Review 页面评论和修改，状态确认后才可执行；
5. 从 Plan 选 Case 创建 Test Run，指定 Build、Manager、Tester；
6. 执行者逐条展开 Execution，录入状态、评论和缺陷；
7. 从 Dashboard/Search/Reports 查看结果；
8. 自动化插件可创建/复用资产并回写 Execution。

### AI 生成流程

无原生 AI。若接入当前产品，Kiwi 风格的 Case 应作为 AI 输出的目标 schema 和审核/发布对象，而非让 AI 直接写 Execution。

### API 或 MCP 设计

- `/xml-rpc/` 与 `/json-rpc/`，不是 REST；
- 方法按模型分组，如 `TestCase.create/filter/update/add_comment`、`TestPlan.add_case`、`TestRun.add_case`；
- 查询参数大量沿用 Django QuerySet lookup，例如 `summary__startswith`；
- 每个方法以 Django permission 做授权；
- 官方建议 Python 客户端使用 `tcms-api`，不要直接拼 RPC。

优点是模型覆盖完整、过滤能力强；缺点是 RPC/Django 字段耦合、接口发现性和跨语言体验弱，不宜原样作为新平台 API。

### 平台与本地 Agent 的边界

Kiwi 是中心平台，保存测试资产、权限与执行结果；本地 runner/plugin 通过 API 创建或复用 Plan/Case/Run 并回写。它提供了很好的“平台真相源 + 本地执行适配器”边界，但没有 Coding Agent 或 MCP 层。

### 人工审核机制

- Case 可以处于多种状态；只有被标记为 Confirmed 的状态才能加入 Test Run；
- Review 页面展示评论，Reviewer 可提供反馈；
- 权限控制状态、内容和评论修改；
- 这是本次样本中最接近正式发布门禁的设计。

不足：状态名称可配置，但核心语义主要是 confirmed/non-confirmed；未体现多人 quorum、字段级建议、AI 风险等级或逐条接受/拒绝。

### 用例版本管理能力

- 对可编辑实体提供历史审计，具有相应权限可查看并恢复旧版本；
- Product Version / Build 是被测产品版本，不等于 Test Case revision；
- Test Run 绑定 Build，但公开模型没有把 Execution 固定到不可变的 Case revision；Case 后续修改可能影响历史阅读语义。

因此应借鉴其审计能力，但新平台应额外引入不可变 `TestCaseRevision` 和 `Execution.case_revision_id`。

### 自动化绑定方式

- Case 具有 `is_automated`、`script`、`arguments`、`extra_link`；
- Runner plugin 根据测试描述和 Product 查找或创建 Case；
- 环境变量提供 Product、Version、Build、Plan、Run、commit 等上下文；
- 执行状态和评论写回 `TestExecution`。

### 可以复用的设计

- Plan / Case / Run / Execution 四层模型；
- Case 与 Plan 多对多复用，而不是复制文本；
- Confirmed 作为执行门禁；
- Product / Version / Build 与测试执行分离；
- Tag、Component、Property 的扩展元数据；
- 权限落到具体动作；
- 插件只通过 API 回写，不让平台理解每种 runner；
- 缺陷绑定在 Execution，而非抽象 Case。

### 不适合当前产品的部分

- Django 单体和大量管理字典会给新产品带来较重历史负担；
- UI/交互以传统 TCMS 为中心，AI 生成和差异审核难以自然嵌入；
- RPC 与 Django lookup 泄露内部模型；
- `requirement` 更像自由文本，不是完整 Requirement 实体和有向追踪图；
- Case 的 script 字段不足以表达多框架、多仓库、多实现绑定；
- 审计历史不等于可发布 revision。

### 开源许可证风险

GPL-2.0 强 copyleft。若复制、修改并分发 Kiwi 派生作品，通常需要按 GPL 提供对应源码；与闭源产品直接合并风险高。可运行独立实例并通过协议集成，也可只研究不复制其数据模型思想。建议不 fork、不嵌入代码；任何实质代码复用需法务评估。

## 4.4 kiwitcms/tcms-api

官方资料：[仓库](https://github.com/kiwitcms/tcms-api)、[Python API 文档](https://tcms-api.readthedocs.io/en/latest/modules/tcms_api.html)、[Plugin Backend](https://tcms-api.readthedocs.io/en/latest/modules/tcms_api.plugin_helpers.html)。

### 项目定位与技术栈

Kiwi TCMS 的官方 Python RPC 客户端和 runner-plugin 公共后端。Python 实现，处理登录、Cookie/XML-RPC transport、长任务连接刷新，以及测试框架插件所需的资产创建/结果回写流程。

### 核心数据对象

不拥有独立业务数据，代理 Kiwi 对象；`Backend` 在本地维护 `product_id`、`plan_id`、`run_id`、category、priority、confirmed status 等上下文，并将 runner 结果映射为 TestExecution。

### 页面和用户流程

无页面。用户配置 TCMS URL/凭据和环境变量；插件调用 `Backend.configure()`，解析本地测试结果，查找/创建 Case，加入 Plan/Run，更新 Execution，最后结束 Run。

### AI 生成流程

无。适合作为 AI 平台输出到自动化生态的适配层参考。

### API 设计

- `TCMS(...).exec` 提供动态 RPC proxy；
- `plugin_helpers.Backend` 封装标准 runner 生命周期；
- `test_case_get_or_create(summary)` 以 Product + 截断后的 summary 做复用；
- 环境变量选择/创建 Product、Version、Build、Plan、Run；
- `update_test_execution` 写状态、评论和起止时间。

### 平台与本地 Agent 的边界

本地进程只做 runner 适配和上下文采集，平台负责 ID、权限、状态和历史。这个边界值得保留，但新平台应使用稳定 REST/Webhook/事件协议，而不是动态 RPC proxy。

### 人工审核、版本、自动化绑定

- 不提供人工审核；
- Version/Build 代表被测版本；
- 自动化绑定依赖 summary + Product，容易因重命名造成重复或误绑定；
- 结果、评论、时间可回写。

### 可以复用的设计

- 把多 runner 的公共行为放到 SDK Backend；
- 配置优先级：显式平台 ID > CI 环境变量 > 自动创建；
- get-or-create 降低首次接入成本；
- 状态映射与兜底；
- 连接刷新和长任务稳定性处理。

### 不适合当前产品的部分

- summary 作为身份键不稳定，应换为显式 `automation_binding.external_id`；
- 自动创建的 Case 直接 Confirmed 会绕过 AI/人工评审门禁；
- 动态 RPC 对类型、演进和跨语言 SDK 不友好；
- 凭据文件/环境变量方案需升级为短期 token 或 OIDC。

### 开源许可证风险

LGPL-2.1。独立使用库通常比 GPL 主应用宽松，但修改库本身、分发以及 Python 动态导入场景仍需满足 LGPL 条款。若只是重写协议思想风险低；若直接依赖，应保留许可、允许替换库并经法务确认。

## 4.5 kiwitcms/pytest-plugin

官方资料：[仓库与 README](https://github.com/kiwitcms/pytest-plugin)。

### 项目定位与技术栈

pytest 到 Kiwi TCMS 的薄插件。Python/pytest，依赖 `tcms-api`。启用 `--kiwitcms` 后，把测试收集与执行结果同步到 Kiwi；2026 年版本会把测试函数 docstring 发布为 TestCase.text。

### 核心数据对象与流程

- 输入：pytest item、测试名称/docstring、执行 outcome、时间和日志；
- 平台对象：Product/Version/Build、TestPlan、TestRun、TestCase、TestExecution；
- 流程：pytest 收集 → 配置 Backend → 创建/复用 Case → 加入 Plan/Run → 将 passed/failed/error 等映射并回写。

### AI、页面、API/MCP

无 UI、无 AI、无 MCP；通过 `tcms-api` 间接调用 Kiwi RPC。

### 平台与本地 Agent 的边界

插件运行于用户代码和 CI 环境，平台不执行测试，只接收标准化资产与结果。这是正确边界；插件不应获得修改需求或批准 AI 用例的权限。

### 人工审核与版本管理

无独立审核或 Case revision。尤其要注意：由自动化发现的新 Case 直接进入 TCMS 的策略不能照搬到需要人工审核的 AI 平台。

### 自动化绑定方式

以 pytest 测试项的可读描述/名称作为 Case 查找线索，并同步 docstring；平台绑定不够稳定。新平台应额外采集：

- framework + node id；
- repository + relative path + symbol；
- branch + commit SHA；
- 参数化用例 identity；
- 可选显式 marker（如 `@case_id`）。

### 可以复用的设计

- runner hook 薄插件；
- 公共 SDK 与 pytest 适配逻辑分离；
- opt-in 开关；
- 将代码文档同步到文本用例；
- CI 上下文自动填充 Build/Run；
- 状态和评论回写。

### 不适合当前产品的部分

- 仅支持 pytest；
- 名称匹配弱；
- 缺少离线队列、幂等键、重试去重和批量上传协议；
- 没有 revision 冲突检测；
- 自动创建与 Confirmed 策略会绕过审核。

### 开源许可证风险

GPL-3.0。直接复制或派生闭源插件风险高；建议依据 pytest 官方 hook 重新实现自有轻插件，不复制实现。与平台通过公开网络 API 通信可降低耦合，但仍需法务判断具体分发组合。

## 4.6 rohitpkumar/ai-testcase-generation-engine

官方资料：[仓库与 README](https://github.com/rohitpkumar/ai-testcase-generation-engine)。

### 项目定位

一个小型、教学/原型性质的本地 AI 测试设计流水线：读取纯文本 PRD，抽取结构化需求，为每项需求生成 functional/negative/edge 用例，分析覆盖缺口并输出 CSV。

### 技术栈

Python 3、OpenAI API、Pydantic、pandas、python-dotenv；模块按 parser、requirement extractor、test generator、coverage analyzer、report generator 拆分。

### 核心数据对象

- PRD 文本；
- Requirement：稳定的 `REQ-*`、描述等结构化字段；
- TestCase：requirement_id、type、title、steps；
- Coverage：每项需求的类别覆盖状态、缺失类别、总覆盖率；
- CSV 报告。

### 页面和用户流程

无 Web 页面。放入 PRD 文本、配置 API key、执行 `python main.py`，查看终端和 `/output` CSV。

### AI 生成流程

1. PRD Parser；
2. LLM Requirement Extractor，输出 JSON；
3. 按 requirement 生成 functional、negative、edge Test Case；
4. Coverage Analyzer 检查每个 requirement 是否覆盖以及是否缺类别；
5. 导出 testcase/coverage CSV。

它用 `temperature=0` 和 Pydantic 结构化解析提升可重复性，但 temperature=0 不等于真正确定性；还需记录模型版本、prompt、输入 hash 和原始响应。

### API/MCP 与平台/Agent 边界

没有服务 API 或 MCP；所有数据、模型调用和输出都在单机脚本中。它可作为 AI worker 内部 pipeline 的最小参考，不应直接承担多租户平台职责。

### 人工审核与版本管理

没有审核页面、状态机、重生成差异或 revision；CSV 是最终产物。覆盖分析只检查类别存在，不判断需求语义是否真的被断言。

### 自动化绑定和结果回写

不生成可运行代码，不绑定仓库测试，也不回写执行结果。

### 可以复用的设计

- 先抽取 Requirement，再按 Requirement 生成；
- 每个阶段独立、输入输出结构化；
- requirement_id 贯穿追踪；
- 把 coverage/gap 作为正式产物，而不是生成后的说明文字；
- 原始输入与报告分离。

### 不适合当前产品的部分

- 项目规模小、提交和发布成熟度低；
- 只处理纯文本 PRD；
- 覆盖类别仅三种，缺少风险、业务不变量、安全、可访问性、并发、NFR；
- 无队列、重试、限流、观测、模型路由、评测集；
- 无人工确认“隐含需求”；
- CSV 不适合作为平台真相源。

### 开源许可证风险

MIT，许可风险低；但工程成熟度不足，不值得 fork。可参考阶段拆分和 schema 思想后重写。

## 4.7 browserstack/mcp-server

官方资料：[仓库、用例与工具清单](https://github.com/browserstack/mcp-server)、[根 LICENSE](https://github.com/browserstack/mcp-server/blob/main/LICENSE)、[package.json](https://github.com/browserstack/mcp-server/blob/main/package.json)。

### 项目定位

BrowserStack 官方 MCP Server，把 Test Management、真实浏览器/设备、自动化执行、Observability、Accessibility、Percy 和 BrowserStack AI Agents 暴露给 IDE/Agent。核心价值是让 Agent 用自然语言完成“管理 → 执行 → 诊断 → 提议修复”。

### 技术栈

TypeScript/Node.js，MCP SDK、Zod、Axios、WebdriverIO、BrowserStack Local、Sharp、Pino、Vitest；支持本地 npx stdio，并区分 Remote MCP。

### 核心数据对象

- Test Management：Project、Folder、Template、TestCase、TestRun、TestResult、TestPlan、SubTestPlan；
- Automation：Build、Session、Test ID、Log、Screenshot、RCA；
- AI：上传文件映射、生成任务、Low Code Automation steps、自愈 selector/plan；
- 其他：Device/Browser Live Session、Accessibility Scan/Issue/Auth Config、Percy Build/Change/Approval。

### 页面和用户流程

MCP 无自有页面，返回 BrowserStack 平台链接。用户安装并提供 BrowserStack credentials 后，在 IDE 中：

1. 创建 Project/Folder；
2. 创建或批量生成 Case；
3. 创建 Run/Plan；
4. 启动手工或自动测试；
5. 回写 Result；
6. 获取日志、截图、RCA；
7. Agent 提出代码修复方案，用户批准后由宿主 Agent 修改本地代码。

### AI 生成流程

- 本地文件先上传获取 mapping ID，再由 BrowserStack AI 创建 Test Case；
- Manual Case 可转换为 Low Code Automation steps；
- 失败 Session 可获取 RCA；
- 自愈 selector 先整理为 edit plan，MCP 本身不自动修改文件。

这些 AI 能力依赖 BrowserStack 后端，开源仓库主要是工具编排和 API adapter，无法离线独立复现生成质量。

### API 或 MCP 设计

公开 README 列出 44 个细粒度工具，其中测试管理包括 `createProjectOrFolder`、`createTestCase`、`updateTestCase`、`listTestCases`、`createTestRun`、`updateTestRun`、`addTestResult`、`createTestCasesFromFile`、Test Plan 查询等。

值得参考的设计：

- 工具名称用业务动作，不直接暴露底层 HTTP；
- 更新采用 patch 语义，只修改传入字段；
- 写操作参数显式要求 project/folder/run identifier；
- 本地 MCP 才能访问本地文件/进程，Remote MCP 禁用这些工具；
- RCA 和自愈只返回 proposal/plan，不自动改代码；
- 读、写、执行、审批工具分开；
- 返回平台 deep link，便于人在 UI 中复核。

### 平台与本地 Agent 的边界

- BrowserStack 平台：项目、用例、运行、结果、设备、分析和 AI 服务；
- 本地 MCP：凭据、文件上传、Local tunnel、本地测试文件发现和命令编排；
- 宿主 Agent：阅读本地仓库、呈现修复建议、经用户批准后编辑代码。

这是本次样本中边界最完整的参考，但当前产品应避免把长期平台密钥直接放在 MCP env 中，优先采用设备授权/OAuth 或短期 scoped token。

### 人工审核机制

- 写操作由 Agent 发起，但 MCP 配置与宿主通常可要求确认；
- RCA/自愈明确只给建议，不直接改文件；
- Percy 有独立 approve/reject 工具；
- Test Case 的正式评审状态机是否完整由商业平台决定，开源 MCP 本身没有强制 reviewer workflow。

### 用例版本管理能力

依赖 BrowserStack Test Management；开源 MCP 未公开对象级 revision 协议。工具支持 update，但未体现 If-Match/version、diff、baseline 和执行固定 revision。

### 自动化绑定与执行回写

- Case/Run/Result 通过平台 ID 绑定；
- 可配置和执行 Selenium、Playwright 等测试；
- Build/Session/Test ID 作为执行身份；
- `addTestResult` 支持手工结果，Observability 工具读取自动执行证据；
- 本地工具能定位测试文件并生成修改计划。

### 可以复用的设计

- 本地与 Remote MCP 明确的 capability matrix；
- 细粒度业务工具与 patch 更新；
- deep link + ID 同时返回；
- 修复建议与代码写入解耦；
- 上传本地文件前显式工具调用；
- 平台 ID 贯穿 Test Case / Run / Result；
- 结果、日志、截图、RCA 形成证据链。

### 不适合当前产品的部分

- 强依赖 BrowserStack 商业账号和后端；
- 工具面过宽，44 个工具会增加发现成本和误调用风险；
- 长期 username/access key 注入本地环境不够现代；
- 设备云、Percy、Accessibility 等超出当前产品核心；
- 不能把其后端 AI 能力误判为开源实现。

### 开源许可证风险

**高风险且存在冲突**：仓库根 `LICENSE` 是 AGPL-3.0，GitHub 也识别为 AGPL-3.0；但当前 `package.json` 的 `license` 字段声明 ISC。两者不一致时不能自行选择更宽松的 ISC，应按更严格/不确定状态处理并向维护方确认。AGPL 对修改后通过网络提供服务有源码提供义务；不建议复制、嵌入或 fork 到闭源平台。可只借鉴公开工具设计思想并独立实现。另需注意 BrowserStack 商标、API 条款和商业服务条款不由开源许可证替代。

## 4.8 petrkindlmann/qa-skills

官方资料：[仓库与技能目录](https://github.com/petrkindlmann/qa-skills)、[ai-test-generation skill](https://github.com/petrkindlmann/qa-skills/blob/main/skills/ai-test-generation/SKILL.md)。

### 项目定位

面向 Codex、Claude Code、Cursor 等本地 Agent 的 QA Skills 内容库。它不是应用或服务，而是把测试策略、自动化、AI 生成、评审、可靠性、CI 和手工用例管理封装成可触发的工作指令。

### 技术栈

- Agent Skills Standard；
- Markdown `SKILL.md` + 按需 references；
- 少量脚本、工具 registry 和 evals；
- 与 Playwright、Cypress、pytest、Jest/Vitest、k6、CI 等外部工具组合。

### 核心数据对象

它的“对象”是流程工件而非数据库实体：

- `qa-project-context`：技术栈、框架、命名、selector、风险区；
- Explicit Requirement / Implicit Requirement；
- Risk、Invariant、Ambiguity；
- Coverage Matrix；
- Scenario（Given/When/Then）；
- Oracle；
- Test Code；
- Review Decision：KEEP / MODIFY / REJECT / DEFER；
- Reproducibility Metadata：model ID、input hash、skill/CLI/MCP version。

### 页面和用户流程

无页面。用户在仓库内用自然语言触发 skill；Agent 读取项目上下文，按阶段输出中间工件、生成代码、运行机械验证，再要求人工评审。

### AI 生成流程

`ai-test-generation` 明确要求七阶段顺序：

1. Extract：需求、实体、业务规则；
2. Analyze：风险、不变量、边界、歧义；
3. Map：Requirement → Scenario → Priority → Oracle Type 的覆盖矩阵；
4. Generate：happy/boundary/negative/security/a11y/state/concurrency 场景；
5. Design：把 Oracle/断言设计与场景生成分开；
6. Code：确认前述工件后才生成测试代码；
7. Review：人工逐条 KEEP/MODIFY/REJECT/DEFER。

随后用类型检查、静态检查、selector/endpoint 搜索和运行测试来拦截幻觉 API。这个流程比“PRD 直接生成用例”更适合成为当前产品的 AI 设计内核。

### API 或 MCP 设计

自身没有 API/MCP Server；Skill 会根据任务指导 Agent 使用 Playwright CLI/MCP 等工具。它体现的是“Agent 行为规范层”，不是“平台集成协议层”。

### 平台与本地 Agent 的边界

- 本地 Agent 最适合读取代码、现有测试、selector、diff 和框架约定，并生成/验证自动化代码；
- 中心平台应保存 Requirement、Coverage、Scenario、Oracle、文本 Case、Revision 和 Review；
- 当前仓库把所有工件留在本地文件/对话，缺少多用户治理。新产品应把 skill 流程变成平台可持久化的 Job/Artifact 模型。

### 人工审核机制

最强的方法论参考：人工审核是强制步骤，每个生成测试都有四态决策，未解决歧义应 DEFER；审核检查追踪、抽象层级、断言、隔离性、数据、惯例和 flaky 风险。

### 用例版本管理能力

建议记录 model ID、输入 hash、skill/CLI/MCP 版本，具备可复现意识；但没有数据库 revision、diff 和 baseline。可以把这些元数据直接纳入新平台的 `GenerationRun` 和 `TestCaseRevision`。

### 自动化绑定和结果回写

- 生成标准测试代码，并在注释中写 Scenario/Requirement ID；
- 复用 Page Object、fixture、factory 和 selector 规范；
- 可指导 CI 与报告工具，但自身不把结果写回中心平台。

### 可以复用的设计

- 显式需求与隐含需求分离，隐含项必须人工确认；
- 风险、不变量、歧义成为一等工件；
- 覆盖矩阵先于用例和代码；
- Scenario 与 Oracle 分开；
- 机械验证位于人工审核之前，节省审核时间；
- 四态审核决策；
- 模型/输入/工具版本可复现元数据；
- 项目上下文文件作为平台与本地 Agent 的稳定契约。

### 不适合当前产品的部分

- Markdown 指令依赖 Agent 是否遵循，没有服务端强约束；
- 无权限、持久化、并发和审计；
- 文档包含具体模型推荐，容易过时，不应固化进产品规则；
- 直接生成代码的比重高于当前“文本用例管理”核心；
- 本地文件格式不能替代平台 schema。

### 开源许可证风险

MIT，风险低；若复制 substantial prompt/skill 文本仍需保留版权与许可。更建议把方法论抽象成自有状态机、schema 和提示词，而非复制整份 skill，以便形成产品自己的领域术语与评测体系。

## 5. 横向可复用设计

### 5.1 建议的核心领域模型

综合 Specifai、Kiwi 与 qa-skills，建议至少包含：

```text
Workspace / Project
  ├─ RequirementSource          # PRD、Story、URL、附件、外部系统引用
  ├─ Requirement
  │    ├─ AnalysisArtifact      # entity/rule/risk/invariant/ambiguity
  │    └─ TestPoint
  ├─ CoverageMatrixEntry        # requirement_revision → test_point/scenario
  ├─ TestCase
  │    └─ TestCaseRevision      # immutable
  │         ├─ Step[] / Oracle[]
  │         └─ ReviewDecision[]
  ├─ TestSuite / TestPlan       # 可复用 Case Revision 的集合/基线
  ├─ AutomationBinding          # Case/Scenario ↔ repo test identity
  ├─ TestRun                    # environment/build/commit
  │    └─ TestExecution         # 固定 case_revision + binding_revision
  │         └─ Evidence[]       # log/screenshot/report/bug
  └─ GenerationRun              # input hash/model/prompt/tool/metrics/cost
```

关键约束：

- Requirement 和 TestCase 都有不可变 Revision；
- Coverage 连接 revision，而不是只连接可变对象 ID；
- TestExecution 必须固定到 `test_case_revision_id`；
- AutomationBinding 是独立实体，不塞进 Case 的一个 `script` 字段；
- AI 输出先进入 Draft Revision，审核通过才 Published；
- 重生成创建新 revision/候选分支，不覆盖已发布内容。

### 5.2 推荐用户流程

1. 导入 PRD/Story/API Schema/附件；
2. AI 抽取显式需求，并把推断项标为“待确认”；
3. 人工确认歧义、风险和业务不变量；
4. 生成测试点与 Coverage Matrix，展示未覆盖和重复；
5. 用户选择范围、优先级、用例模板和生成预算；
6. AI 生成 Draft Test Cases 和 Oracle；
7. 机械质量门：schema、重复、引用、覆盖、规则检查；
8. 人工逐条 Accept / Modify / Reject / Defer；
9. 发布 Case Revision 和 Test Plan baseline；
10. 本地 Agent 通过 MCP 获取已发布文本用例，生成/绑定自动化；
11. CI Adapter 回写 Run / Execution / Evidence；
12. 需求或代码变更触发 impact analysis，而不是静默改写旧用例。

### 5.3 推荐 AI 状态机

```text
INGESTED
  → EXTRACTED
  → NEEDS_CLARIFICATION ──(人工确认)──┐
  → RISK_ANALYZED                     │
  → COVERAGE_MAPPED  ←────────────────┘
  → CASES_DRAFTED
  → MACHINE_VALIDATED
  → HUMAN_REVIEW
      ├─ APPROVED → PUBLISHED
      ├─ MODIFY   → CASES_DRAFTED
      ├─ REJECTED
      └─ DEFERRED → NEEDS_CLARIFICATION
```

每个阶段输出结构化 artifact，并保存 input/output hash、模型、prompt template version、token/cost、延迟、错误、重试和 evaluator 结果。不要把整条链包装成一次不可观察的 LLM 调用。

### 5.4 推荐 API 与 MCP 分工

#### 平台 REST API

REST 是系统集成与 CI 的稳定接口，负责：

- Requirement/TestCase/Revision/Review CRUD；
- Generation Job 创建、查询、取消；
- Automation Binding 注册与解析；
- Run/Execution 批量写入；
- Evidence 预签名上传；
- Webhook 与外部需求系统同步。

写入应具备：幂等键、乐观锁（ETag/version）、批量接口、scoped token、审计 actor、速率限制和可重放事件。

#### 本地 MCP

MCP 是 Coding Agent 的交互接口，建议分三组：

- 默认只读：`search_requirements`、`get_requirement_revision`、`list_published_test_cases`、`get_coverage_matrix`、`get_automation_binding`；
- 受控建议：`propose_automation_binding`、`propose_test_case_change`、`upload_execution_evidence`；
- 高风险写入：`publish_test_case_revision`、`record_execution_result`，必须有平台权限、幂等键和宿主确认。

不要让 MCP 直接修改本地源代码；它只返回 edit plan/结构化建议，由宿主 Coding Agent 在用户确认和本地 diff 机制下修改。

### 5.5 平台与本地 Agent 的推荐边界

| 中心平台负责 | 本地 Agent/Adapter 负责 |
|---|---|
| 身份、租户、权限、审计 | 读取用户授权的本地仓库 |
| Requirement/TestCase/Revision 真相源 | 发现框架、测试文件、selector、fixture |
| AI Job、模型策略、成本和评测 | 生成/修改自动化代码 |
| Coverage、Review、发布门禁 | 类型检查、静态检查和本地试跑 |
| Run/Execution/Evidence 归档 | 收集 runner 原生结果和 CI 元数据 |
| 稳定 ID 和冲突检测 | 用稳定 external identity 绑定平台对象 |
| Webhook/REST/MCP 授权 | 在明确批准后执行本地写操作 |

## 6. 不建议复用的共性模式

- 用 summary/title 作为自动化用例唯一身份；
- AI 重生成时覆盖原对象；
- 把“可以编辑”当成“已经有人审核”；
- 仅用 temperature=0 宣称确定性；
- 用 CSV/Markdown 文件作为多用户平台唯一真相源；
- 让自动化插件创建 Case 后直接进入可执行/已确认状态；
- 执行结果绑定可变 Case，而不是 Case Revision；
- 给本地 MCP 长期全权限平台密钥；
- 一个万能 MCP 工具同时读取、生成、发布和改代码；
- 把商业后端能力误认为开源 MCP 仓库内已实现；
- 将 Product Version/Build 混同于 Test Case Version。

## 7. 许可证风险汇总

| 项目 | 公开许可证 | 风险判断 | 建议 |
|---|---|---|---|
| presidio-oss/specif-ai | MIT | 低 | 可参考；复制代码需保留 notice，仍建议重写 |
| presidio-oss/specifai-mcp-server | MIT | 低 | 可参考协议分层；不要依赖 experimental 契约 |
| kiwitcms/Kiwi | GPL-2.0 | 高 | 不嵌入闭源产品，不 fork；仅参考模型或独立协议集成 |
| kiwitcms/tcms-api | LGPL-2.1 | 中 | 可作为独立依赖候选，但分发/修改方式需法务确认 |
| kiwitcms/pytest-plugin | GPL-3.0 | 高 | 不复制；基于 pytest 官方 hook 自行实现 |
| ai-testcase-generation-engine | MIT | 低 | 参考阶段拆分和 schema，工程上重写 |
| browserstack/mcp-server | 根 LICENSE 为 AGPL-3.0；package.json 标 ISC | **高/不明确** | 按 AGPL/冲突处理；向维护方确认；不要复制或 fork |
| petrkindlmann/qa-skills | MIT | 低 | 抽象方法论；复制 substantial 文本需保留 notice |

> 本节是工程风险识别，不构成法律意见。发布或商业化前应由法务核对具体版本、依赖树、分发方式、网络使用方式、商标和第三方服务条款。

## 8. 推荐架构与项目选择

### 8.1 哪个项目适合作为产品设计参考

**首选 Specifai。**

原因：它已经把 Solution、PRD、Story、Test Case、AI Chat、Inline Edit、生成前补充上下文、重生成归档和外部集成组织成连贯 UI。当前产品应缩小范围，保留“需求分析 → 测试点 → 文本用例 → 审核 → 自动化绑定”主线，不照搬全套 SDLC 文档和 Electron 形态。

**人工执行与评审页面补充参考 Kiwi TCMS。** Kiwi 的 Plan/Run/Execution 页面和 Confirmed 门禁比 Specifai 成熟。

### 8.2 哪个项目适合作为数据模型参考

**首选 Kiwi TCMS，但必须现代化。**

保留 Plan / Case / Run / Execution、Product / Version / Build、Tag / Component / Property、Reviewer/Status/Permission；新增 Requirement 实体、Coverage Matrix、TestPoint、不可变 TestCaseRevision、GenerationRun、ReviewDecision、AutomationBinding 和 Evidence。

### 8.3 哪个项目适合作为 AI 流程参考

**首选 qa-skills 的七阶段流程。** 它最明确地把显式/隐式需求、风险、不变量、歧义、覆盖矩阵、Scenario、Oracle、代码与人工审核分开。

**ai-testcase-generation-engine 作为 MVP 工程切分参考。** 它的五模块适合第一版 worker，但覆盖规则不能只检查 functional/negative/edge 是否存在。

**Specifai 作为 AI 流程的产品承载参考。** 即如何把补充上下文、生成、重生成和归档放进页面。

### 8.4 哪个项目适合作为 MCP 和 Agent 参考

- **本地只读知识桥**：Specifai MCP；
- **远端平台工具粒度、安全确认、本地/远端能力矩阵**：BrowserStack MCP；
- **本地 Agent 行为与质量门**：qa-skills；
- **CI/runner 回写适配器**：tcms-api + pytest-plugin。

推荐组合是“平台 REST API 为系统接口、MCP 为 Agent 交互接口、runner SDK 为执行回写接口”，三者不要混成一个协议。

### 8.5 是否值得 fork

**结论：不建议 fork 任一项目作为主产品底座，只参考后重新实现。**

理由：

- Specifai 的本地 Electron/文件架构与多用户平台目标差异大；
- Kiwi 的 GPL-2.0、传统 Django 单体和非 REST RPC 增加法律与演进成本；
- BrowserStack MCP 有 AGPL/ISC 冲突且依赖商业后端；
- qa-skills 和 AI engine 是方法/原型，不是平台；
- 目标产品需要把“对象 revision、AI 生成批次、人工审核、自动化绑定和执行证据”放进同一套领域模型，这是现有项目都没有完整实现的组合。

可以考虑的直接依赖仅限成熟、许可证兼容的通用库；上述项目的业务实现应保持“clean-room 风格”的独立设计：依据公开行为与抽象原则写自有 schema、接口、状态机和 UI。

## 9. 建议的实施顺序

1. 先定义 Requirement/TestPoint/TestCaseRevision/Coverage/Review schema 和状态机；
2. 实现文本用例平台、审计和评审，不先做自动执行；
3. 上线结构化 AI pipeline，并建立固定评测集；
4. 提供只读 MCP，让 Coding Agent 消费已发布用例；
5. 增加 AutomationBinding 与 pytest/Playwright 等薄 adapter；
6. 再做批量 Execution/Evidence 回写和质量趋势；
7. 最后扩展需求系统双向同步、远端 MCP 和更多 runner。

这个顺序能确保 AI、MCP 和自动化围绕稳定的测试资产内核演进，而不是让平台沦为不同 Agent 与脚本之间的临时文件中转站。
