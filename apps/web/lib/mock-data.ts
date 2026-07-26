export type CaseStep = {
  id: string;
  action: string;
  expected: string;
};

export type TestCase = {
  id: string;
  title: string;
  module: string;
  priority: "P0" | "P1" | "P2";
  type: "功能" | "异常" | "边界" | "安全";
  status: "Pending" | "通过" | "不通过" | "跳过" | "堵塞";
  tags: string[];
  automated: boolean;
  source: string;
  preconditions: string[];
  steps: CaseStep[];
};

export const testCases: TestCase[] = [
  {
    id: "PAY-008",
    title: "支付成功后重复回调的幂等处理",
    module: "支付回调",
    priority: "P0",
    type: "异常",
    status: "Pending",
    tags: ["支付", "幂等", "回归"],
    automated: true,
    source: "支付结算需求说明 v1.8 / 4.3.2",
    preconditions: [
      "订单已创建且状态为“待支付”",
      "支付网关 Mock 已开启，可重复发送同一 transaction_id",
      "该订单尚未生成支付成功事件",
    ],
    steps: [
      {
        id: "s1",
        action: "发送一次签名正确的支付成功回调。",
        expected: "返回 HTTP 200；订单更新为“已支付”；生成一条支付成功事件。",
      },
      {
        id: "s2",
        action: "使用相同 transaction_id 再次发送完全相同的回调。",
        expected: "仍返回 HTTP 200；不重复扣减库存、不重复发放权益、不新增支付事件。",
      },
      {
        id: "s3",
        action: "查询订单流水、库存流水与消息投递记录。",
        expected: "三类副作用均只有一条有效记录，并保留重复回调审计日志。",
      },
    ],
  },
  {
    id: "PAY-003",
    title: "银行卡支付成功并刷新订单状态",
    module: "支付回调",
    priority: "P0",
    type: "功能",
    status: "通过",
    tags: ["支付", "主流程"],
    automated: true,
    source: "支付结算需求说明 v1.8 / 4.2",
    preconditions: ["存在待支付订单", "支付渠道可用"],
    steps: [
      {
        id: "s1",
        action: "选择银行卡并完成付款。",
        expected: "订单状态在 5 秒内变更为“已支付”。",
      },
    ],
  },
  {
    id: "ORD-014",
    title: "优惠券与会员折扣叠加上限校验",
    module: "订单结算",
    priority: "P1",
    type: "边界",
    status: "不通过",
    tags: ["优惠", "边界"],
    automated: false,
    source: "营销优惠规则 v2.1 / 3.4",
    preconditions: ["用户为金卡会员", "账户中存在满减券"],
    steps: [
      {
        id: "s1",
        action: "选择达到优惠上限的商品并使用满减券。",
        expected: "总优惠不超过订单原价的 50%。",
      },
    ],
  },
];

export const generationStages = [
  { label: "文档解析", detail: "识别标题、表格与业务规则" },
  { label: "需求分析", detail: "抽取角色、流程、约束与歧义" },
  { label: "测试点设计", detail: "构建功能、异常与边界覆盖" },
  { label: "用例生成", detail: "生成步骤、数据与校验点" },
  { label: "质量检查", detail: "去重、追踪与可执行性检查" },
];

export const analysisMarkdown = `已完成 **支付结算需求说明 v1.8** 的分析。

- 识别 3 个业务模块、8 个测试点、24 条候选用例
- 发现 2 处需求歧义：优惠叠加顺序、支付回调重试上限
- 已优先展开 6 条 P0 用例，并为每一步生成独立校验点

建议先评审“支付回调”分支。我已选中风险最高的 **PAY-008**。`;
