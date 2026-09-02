export const conversationExamples = [
  {
    title: "生成登录用例",
    description: "覆盖正常流程、频控、过期和弱网场景",
    prompt:
      "为手机号验证码登录生成测试用例，覆盖正常流程、频控、验证码过期和弱网场景。",
  },
  {
    title: "梳理测试范围",
    description: "先问答，不创建用例集合",
    prompt: "一个完整的支付退款功能通常需要覆盖哪些测试维度？",
  },
  {
    title: "局部修改用例",
    description: "进入工作台后选择节点再改写",
    prompt: "把选中的登录用例补充弱网恢复检查，并保持其他字段不变。",
  },
] as const;
