import type { TestCaseInput } from "@/lib/casepilot-api";

export type SampleCaseDefinition = {
  input: TestCaseInput;
};

export const sampleLoginCases: SampleCaseDefinition[] = [
  {
    input: {
      case_key: "AUTH-001",
      title: "使用正确邮箱与密码登录成功",
      module: "账号与认证",
      priority: "P0",
      case_type: "功能",
      tags: ["登录", "账号", "冒烟"],
      preconditions: [
        "本地示例账号已注册且处于启用状态",
        "PostgreSQL 与 CasePilot API 已启动",
        "浏览器当前未登录",
      ],
      steps: [
        {
          id: "auth-001-input",
          action: "输入正确邮箱与密码并提交登录表单",
          expected: "登录成功并进入默认质量空间",
        },
        {
          id: "auth-001-refresh",
          action: "刷新页面",
          expected: "登录会话保持有效，仍显示用例管理工作台",
        },
      ],
      source: "CasePilot 账号认证示例基线",
    },
  },
  {
    input: {
      case_key: "AUTH-002",
      title: "密码错误时拒绝登录并保留邮箱",
      module: "账号与认证",
      priority: "P0",
      case_type: "异常",
      tags: ["登录", "错误密码", "提示"],
      preconditions: ["账号已注册且处于启用状态", "浏览器当前未登录"],
      steps: [
        {
          id: "auth-002-submit",
          action: "输入正确邮箱和错误密码后提交",
          expected: "登录被拒绝，并显示不泄露账号存在性的统一错误提示",
        },
        {
          id: "auth-002-retain",
          action: "检查登录表单内容",
          expected: "邮箱输入保留，密码字段被清空且重新获得焦点",
        },
      ],
      source: "CasePilot 账号认证示例基线",
    },
  },
  {
    input: {
      case_key: "AUTH-003",
      title: "邮箱格式不合法时阻止提交",
      module: "账号与认证",
      priority: "P1",
      case_type: "边界",
      tags: ["邮箱校验", "前端校验"],
      preconditions: ["打开登录页面"],
      steps: [
        {
          id: "auth-003-format",
          action: "分别输入缺少 @、缺少域名和包含空格的邮箱",
          expected: "每种非法格式均出现明确校验提示，登录请求不发送",
        },
      ],
      source: "CasePilot 账号认证示例基线",
    },
  },
  {
    input: {
      case_key: "AUTH-004",
      title: "连续失败触发账号保护策略",
      module: "登录安全",
      priority: "P0",
      case_type: "安全",
      tags: ["限流", "暴力破解", "堵塞"],
      preconditions: [
        "账号保护策略已配置",
        "测试环境允许重置失败计数",
      ],
      steps: [
        {
          id: "auth-004-failures",
          action: "在限定时间内连续提交错误密码直至达到阈值",
          expected: "系统触发保护策略，后续请求被限流或暂时锁定",
        },
        {
          id: "auth-004-audit",
          action: "查询安全审计记录",
          expected: "记录失败次数、时间和保护动作，不记录明文密码",
        },
      ],
      source: "等待账号保护阈值需求确认",
    },
  },
  {
    input: {
      case_key: "AUTH-005",
      title: "必填项为空时不允许登录",
      module: "账号与认证",
      priority: "P1",
      case_type: "异常",
      tags: ["必填校验", "登录"],
      preconditions: ["打开登录页面"],
      steps: [
        {
          id: "auth-005-empty",
          action: "邮箱和密码均为空时点击登录",
          expected: "邮箱和密码字段分别显示必填提示",
        },
        {
          id: "auth-005-partial",
          action: "仅填写其中一个字段后再次点击登录",
          expected: "只提示未填写字段，登录请求不发送",
        },
      ],
      source: "CasePilot 账号认证示例基线",
    },
  },
  {
    input: {
      case_key: "AUTH-006",
      title: "会话过期后返回登录并保留目标页面",
      module: "会话管理",
      priority: "P0",
      case_type: "异常",
      tags: ["会话过期", "重定向"],
      preconditions: ["用户已登录", "会话可以在测试环境中主动失效"],
      steps: [
        {
          id: "auth-006-expire",
          action: "使当前会话过期后访问用例管理页面",
          expected: "系统跳转到登录页，并保存原目标页面",
        },
        {
          id: "auth-006-login",
          action: "重新登录",
          expected: "登录成功后返回原目标页面，不丢失已持久化数据",
        },
      ],
      source: "CasePilot 会话管理示例基线",
    },
  },
  {
    input: {
      case_key: "AUTH-007",
      title: "记住登录状态并在重新打开浏览器后恢复",
      module: "会话管理",
      priority: "P2",
      case_type: "功能",
      tags: ["记住登录", "Cookie"],
      preconditions: ["产品已启用“记住我”选项"],
      steps: [
        {
          id: "auth-007-remember",
          action: "勾选记住登录后完成登录并关闭浏览器",
          expected: "重新打开浏览器后，在有效期内自动恢复登录状态",
        },
      ],
      source: "当前版本未启用“记住我”，示例保留",
    },
  },
  {
    input: {
      case_key: "AUTH-008",
      title: "退出登录后旧会话立即失效",
      module: "会话管理",
      priority: "P0",
      case_type: "安全",
      tags: ["退出", "会话失效", "安全"],
      preconditions: ["用户已登录并进入用例管理页面"],
      steps: [
        {
          id: "auth-008-logout",
          action: "点击退出登录",
          expected: "返回登录页，服务端会话被撤销",
        },
        {
          id: "auth-008-back",
          action: "使用浏览器后退并刷新受保护页面",
          expected: "无法恢复旧页面数据，仍要求重新登录",
        },
      ],
      source: "CasePilot 会话管理示例基线",
    },
  },
  {
    input: {
      case_key: "AUTH-009",
      title: "重复注册邮箱时给出安全提示",
      module: "账号注册",
      priority: "P1",
      case_type: "异常",
      tags: ["注册", "重复邮箱", "隐私"],
      preconditions: ["目标邮箱已经注册"],
      steps: [
        {
          id: "auth-009-register",
          action: "使用已注册邮箱提交注册表单",
          expected: "注册不产生重复账号，并返回符合隐私策略的提示",
        },
      ],
      source: "CasePilot 账号注册示例基线",
    },
  },
  {
    input: {
      case_key: "AUTH-010",
      title: "注册密码不满足强度要求时显示规则",
      module: "账号注册",
      priority: "P1",
      case_type: "边界",
      tags: ["注册", "密码强度", "校验"],
      preconditions: ["打开账号注册页面"],
      steps: [
        {
          id: "auth-010-weak",
          action: "依次输入过短、全数字和缺少必要字符类型的密码",
          expected: "系统逐项提示未满足的密码规则，无法提交注册",
        },
        {
          id: "auth-010-valid",
          action: "输入满足全部规则的密码",
          expected: "强度提示通过，注册按钮恢复可用",
        },
      ],
      source: "CasePilot 账号注册示例基线",
    },
  },
  {
    input: {
      case_key: "AUTH-011",
      title: "两个标签页并发退出时结果保持一致",
      module: "会话管理",
      priority: "P1",
      case_type: "并发",
      tags: ["多标签页", "退出", "一致性"],
      preconditions: ["同一账号在两个浏览器标签页中保持登录"],
      steps: [
        {
          id: "auth-011-logout",
          action: "在标签页 A 退出登录",
          expected: "标签页 A 返回登录页，服务端会话失效",
        },
        {
          id: "auth-011-refresh",
          action: "在标签页 B 执行任意写操作或刷新页面",
          expected: "标签页 B 识别会话失效并返回登录页",
        },
      ],
      source: "CasePilot 会话管理示例基线",
    },
  },
  {
    input: {
      case_key: "AUTH-012",
      title: "账号停用后现有会话在策略时间内失效",
      module: "登录安全",
      priority: "P0",
      case_type: "安全",
      tags: ["账号停用", "会话撤销", "权限"],
      preconditions: [
        "用户已登录",
        "管理员具备停用账号权限",
        "账号停用后的会话失效策略待确认",
      ],
      steps: [
        {
          id: "auth-012-disable",
          action: "管理员停用当前登录账号",
          expected: "账号状态更新为停用，并触发现有会话撤销流程",
        },
        {
          id: "auth-012-action",
          action: "被停用用户继续访问或提交写操作",
          expected: "操作被拒绝并要求重新认证，停用账号不能再次登录",
        },
      ],
      source: "等待账号停用会话策略确认",
    },
  },
];
