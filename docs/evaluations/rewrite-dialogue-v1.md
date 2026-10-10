# 自然语言改写对话评测集 v1

基线：`709aab8a`。30 个场景、56 轮输入。每轮独立发送，继承真实服务端草稿。机器数据见 [rewrite-dialogue-v1.json](./rewrite-dialogue-v1.json)。

## 测试基线

每个场景拥有独立账号、空间、集合及四条合成用例：A=正确验证码登录/P0，B=错误验证码登录/P1，C=正确密码登录/P2，D=订单支付成功/P1。初始范围按展示顺序 A、B、C；初始要求为步骤更清晰、标题和预期结果保持不变。缺修改方向场景例外。编号、ID和版本在运行时创建；{{A}} 等替换成真实编号。

## 分层判定

- API层：准备阶段使用离线模式建立预览；启用真实模型配置，需要语义理解和范围选择时调用真实模型，纯确认使用产品快捷路径。独立进程捕获队列提交，检查真实任务输入，但不运行 worker。此层不能宣称改写内容和浏览器端到端通过。
- 端到端层：浏览器输入 → API → 真实 worker → 建议差异 → 采纳/取消 → 数据版本。仅使用独立验收集合。
- 内容层：字段赋值和保留字段做等值比较；步骤语义质量仍依据原规则人工核验。正则只提示明显的约束丢失或旧值残留，不替代语义审阅。

每轮断言状态、目标ID集合、修改要求、任务是否启动、任务实际输入、刷新后草稿、正式用例版本。PASS/FAIL/ERROR单列；前一轮失败则后续NOT_RUN，不伪造上下文继续计通过。首次结果与复测分别保存。

范围查询场景在v1检验不会误执行；能否直接回答范围而不要求澄清，另记易用性缺口，安全澄清不代表查询体验通过。

## 场景清单

| ID | 目标 | 顺序输入 | 预期动作 |
|---|---|---|---|
| RW-01 | 纯确认与自动回传选中范围 | 确认 | dispatch |
| RW-02 | 口语确认 | 没问题，就照这个来吧 | dispatch |
| RW-03 | 英文确认 | Looks good, go ahead. | dispatch |
| RW-04 | 确认中追加要求 | 确认，不过前置条件也不要动 → 好的 | preview → dispatch |
| RW-05 | 确认中缩小范围 | 可以，但只改第一条 → 就这样继续 | preview → dispatch |
| RW-06 | 否定一个字段并非取消 | 不要动标题，把步骤拆开 → 确认 | preview → dispatch |
| RW-07 | 调整描述风格 | 简洁一点 → 确认 | preview → dispatch |
| RW-08 | 英文修改要求 | Keep the title and expected results unchanged; make the steps clearer. | preview |
| RW-09 | 修改字段值不应筛选范围 | 把优先级改成P0 → 确认 | preview → dispatch |
| RW-10 | 纠正字段值而非叠加旧值 | 优先级改为P0 → 刚才说错了，改成P2 → 可以继续 | preview → preview → dispatch |
| RW-11 | 模块字段更名并非换范围 | 模块字段改为账号登录，其他要求保留 → 确认 | preview → dispatch |
| RW-12 | 按优先级排除目标 | 范围排除P0的用例 → 确认 | preview → dispatch |
| RW-13 | 按编号选择并抵抗陈旧选中范围 | 只改{{B}} → 确认 | preview → dispatch |
| RW-14 | 相对位置按展示顺序 | 就刚才展示的前三条，只改前两条 → 简洁一点 | preview → preview |
| RW-15 | 换模块仍保留修改要求 | 范围改成支付模块 → 确认 | preview → dispatch |
| RW-16 | 扩大当前范围 | 把{{D}}也加进来，其他不变 → 确认 | preview → dispatch |
| RW-17 | 范围与修改要求同时改变 | 只改{{C}}，优先级改为P1，标题仍保留 → 确认 | preview → dispatch |
| RW-18 | 模糊否定必须澄清 | 不对 → 确认 → 范围没问题，步骤要按操作顺序拆开，标题预期仍不变 → 确认 | clarify → clarify → preview → dispatch |
| RW-19 | 不是这些并未指定新范围 | 不是这些 | clarify |
| RW-20 | 单独否定不能擅自执行或取消 | 不要 | clarify |
| RW-21 | 明确终止任务 | 这次先不改了，结束任务 | cancel |
| RW-22 | 暂停表述保守澄清或取消 | 先别执行，我还要想想 | clarify |
| RW-23 | 混入删除意图 | 先删掉{{B}}，再改其余的 | clarify |
| RW-24 | 混入生成意图 | 同时再生成十条支付用例 | clarify |
| RW-25 | 查询当前范围不应执行 | 当前范围到底是哪些用例？ | clarify |
| RW-26 | 长对话保留约束和纠正值 | 步骤精简一点，前置条件别变 → 优先级统一改为P0 → 不，是P2，不要P0 → 只改{{A}}和{{C}} → 没问题，继续吧 | preview → preview → preview → preview → dispatch |
| RW-27 | 显式重新选择需新预览 | 确认 → 确认 | preview → dispatch |
| RW-28 | 未知编号不扩大为全部 | 只改不存在的编号TC-MISSING-999 | clarify |
| RW-29 | 缺修改方向时先补充要求 | 步骤更清晰 → 确认 | preview → dispatch |
| RW-30 | 已澄清后继续补充保留条件 | 不对 → 范围还是原三条，只把步骤拆开写，其他全部保留 → 预期结果一定别动 → 行，就这么办 | clarify → preview → preview → dispatch |

## 执行方式

在有真实模型配置和测试数据库的独立进程运行：

```sh
PYTHONPATH=apps/api/src .venv/bin/python scripts/qa/evaluate_rewrite_dialogue.py --validate-only
PYTHONPATH=apps/api/src .venv/bin/python scripts/qa/evaluate_rewrite_dialogue.py --output output/rewrite-dialogue-evaluation/first.json
PYTHONPATH=apps/api/src .venv/bin/python scripts/qa/evaluate_rewrite_dialogue.py --ids RW-10,RW-18 --output output/rewrite-dialogue-evaluation/retest.json
```

运行后清理本次创建的账号和空间，不使用或清理其他用户的数据。修改断言须记录理由，不能为了提高通过率放宽预期。

## 性能与门禁

记录每个请求响应时长；本轮不是压测或稳定SLA。确认、要求补充、范围变更分别统计，失败和超时保留。30个不同场景的混合分布不能作为某一场景的稳定p95。

范围扩大、未确认启动、未采纳正式用例变化为阻断项。明确输入却反复澄清属于功能/易用性失败；有意歧义输入正确澄清可通过。盲测表达单列；一旦用于调优则标记已消耗，不能再声称独立盲测。

## 端到端补充集

同一 JSON 的 `manual_e2e_scenarios` 另列 5 组端到端对话，需真实 worker 和界面操作，不纳入上述 30 组 API 通过率：

| ID | 验收闭环 |
|---|---|
| RW-E2E-01 | 补充保留条件 → P0纠正为P2 → 口语确认 → 审阅 → 采纳 → 刷新核对版本 |
| RW-E2E-02 | 首轮新增无来源UI动作 → 暂不采纳 → 提供明确验收依据继续改写 → 再审阅 |
| RW-E2E-03 | 仅采纳A → 继续修改剩余B → 确认A未被重复修改 |
| RW-E2E-04 | 模糊否定 → 刷新 → 补充明确要求 → 刷新 → 确认当前草稿 |
| RW-E2E-05 | 生成建议 → 丢弃 → 刷新后不复活，正式版本不变 |

这些是设计场景，不代表全部已执行。执行范围与首次失败见本次验收报告。
