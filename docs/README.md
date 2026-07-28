# CasePilot 材料索引

> 当前实现版本：V0.6 AI 用例工作台
> 产品路线图版本：V1.5
> 最近同步：2026-07-27

## 产品材料

- [产品设计](./product-design-v1.md)：定位、信息架构、界面与核心对象。
- [产品规格](./product-spec-v1.md)：功能需求、数据对象、API、AI 流程与验收标准。
- [完整工作流与交互设计](./product-interaction-design.md)：逐模块交互、异常分支、状态与人工评审。
- [产品逻辑 Review](./product-logic-review-v1.4.md)：本轮统一决策、端到端检查和未完成风险。
- [轻量测试执行设计](./test-execution-design.md)：任务历史、任务创建、多人执行、结果记录与数据边界。

## 工程与验收

- [开发基线](./development-baseline-v1.md)
- [开发进度](./development-progress.md)
- [V0.2 用例管理与 QA 执行验收](./acceptance-case-management-execution-v0.2.md)
- [V0.3 用例脑图与集合执行验收](./acceptance-mind-map-collection-execution-v0.3.md)
- [V0.1 登录与简单生成验收（历史）](./acceptance-login-generation-v0.1.md)
- [V0.5 执行任务历史与多人协作验收](./acceptance-execution-collaboration-v0.5.md)
- [V0.6 AI 用例工作台验收](./acceptance-ai-workbench-v0.6.md)

## 调研与设计

- [开源项目调研](./opensource-research.md)
- [Figma AI Workbench V2.2](https://www.figma.com/design/fRnEKJHcshgCIa1CmYXbLx?node-id=38-2)
- [Figma 脑图全屏 V4](https://www.figma.com/design/fRnEKJHcshgCIa1CmYXbLx?node-id=110-25)
- [Figma 测试执行任务历史 V4](https://www.figma.com/design/fRnEKJHcshgCIa1CmYXbLx?node-id=102-2)
- [Figma 多人协作执行详情 V4](https://www.figma.com/design/fRnEKJHcshgCIa1CmYXbLx?node-id=77-3)
- [Figma 新建任务必填校验 V4](https://www.figma.com/design/fRnEKJHcshgCIa1CmYXbLx?node-id=111-25)

## 统一术语

- 用例集合和用例资产没有 QA 执行状态。
- 未执行、通过、不通过、跳过、堵塞只保存在独立执行任务中。
- 评审是 Review Event，发布状态属于 Revision/Baseline 生命周期。
- Candidate Revision 与 Published Revision 是版本生命周期，不作为用户可见状态列。
- 当前运行版本已启用 AI 工作台和本地候选生成；真实模型、文件解析与自动
  应用改写仍属于后续服务端里程碑。
- 正常连接状态不常驻顶部；只有异常影响操作时才提示。

## 当前实现与路线图边界

- V0.6 的真实实现范围增加聊天创建页、附件上下文、分阶段候选生成、三栏
  工作台、脑图/列表切换、用例详情、改写建议和候选批量写入。
- 产品设计、规格和开源调研中的真实 Provider、文档解析、生成任务恢复与
  发布评审仍是后续架构范围。
- 当前 OpenAPI 不包含 Mock 或 AI 生成路由；独立 Agent 与 Mock Provider 仅作为后续基础设施保留。
- V0.1、V0.2 验收文件保留历史行为证据；当前资产/执行状态边界以 V0.5
  验收和轻量测试执行设计为准。
