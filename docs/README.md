# CasePilot 材料索引

> 当前统一版本：V1.4
> 最近同步：2026-07-25

## 产品材料

- [产品设计](./product-design-v1.md)：定位、信息架构、界面与核心对象。
- [产品规格](./product-spec-v1.md)：功能需求、数据对象、API、AI 流程与验收标准。
- [完整工作流与交互设计](./product-interaction-design.md)：逐模块交互、异常分支、状态与人工评审。
- [产品逻辑 Review](./product-logic-review-v1.4.md)：本轮统一决策、端到端检查和未完成风险。
- [轻量测试执行设计](./test-execution-design.md)：QA 加载集合、逐条执行、结果记录与数据边界。

## 工程与验收

- [开发基线](./development-baseline-v1.md)
- [开发进度](./development-progress.md)
- [登录与简单生成验收](./acceptance-login-generation-v0.1.md)

## 调研与设计

- [开源项目调研](./opensource-research.md)
- [Figma AI Workbench V2.1](https://www.figma.com/design/fRnEKJHcshgCIa1CmYXbLx?node-id=38-2)
- [Figma 测试执行 V1.4](https://www.figma.com/design/fRnEKJHcshgCIa1CmYXbLx?node-id=77-3)

## 统一术语

- 用户可见用例状态只有五种：Pending、通过、不通过、跳过、堵塞。
- 测试执行结果独立保存为未执行、通过、不通过、跳过、堵塞，不覆盖用例状态。
- 评审是事件历史，不是第二套用例状态。
- Candidate Revision 与 Published Revision 是版本生命周期，不作为用户可见状态列。
- 模型选择值为 `auto`、`pro`、`local`，并保存到生成任务输入快照。
- 正常连接状态不常驻顶部；只有异常影响操作时才提示。
