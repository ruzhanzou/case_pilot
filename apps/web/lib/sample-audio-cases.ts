import type { SampleCaseDefinition } from "@/lib/sample-cases";

const source = "Audio Feature 场景设计基线";

export const sampleAudioCases: SampleCaseDefinition[] = [
  {
    input: {
      case_key: "AUDIO-001",
      title: "首次进入时申请麦克风权限并完成初始化",
      module: "入口与初始化",
      priority: "P0",
      case_type: "功能",
      tags: ["首次进入", "麦克风权限"],
      preconditions: ["首次安装并启动应用", "系统麦克风权限尚未选择"],
      steps: [
        {
          id: "audio-001-enter",
          action: "进入 Audio Feature 页面并允许麦克风权限",
          expected: "系统仅申请必要权限，页面初始化成功且录制入口可用",
        },
      ],
      source,
    },
  },
  {
    input: {
      case_key: "AUDIO-002",
      title: "拒绝麦克风权限后给出可恢复引导",
      module: "入口与初始化",
      priority: "P0",
      case_type: "异常",
      tags: ["权限拒绝", "错误提示", "可恢复"],
      preconditions: ["系统麦克风权限尚未选择"],
      steps: [
        {
          id: "audio-002-deny",
          action: "进入页面并拒绝麦克风权限后点击开始录制",
          expected: "录制不启动，页面说明权限用途并提供前往系统设置的入口",
        },
        {
          id: "audio-002-recover",
          action: "在系统设置中允许权限后返回页面",
          expected: "权限状态自动刷新，无需重启应用即可开始录制",
        },
      ],
      source,
    },
  },
  {
    input: {
      case_key: "AUDIO-003",
      title: "音频服务初始化失败时支持重试",
      module: "入口与初始化",
      priority: "P1",
      case_type: "异常",
      tags: ["初始化失败", "重试"],
      preconditions: ["麦克风权限已开启", "模拟音频服务初始化失败"],
      steps: [
        {
          id: "audio-003-fail",
          action: "进入 Audio Feature 页面",
          expected: "页面显示明确错误且不进入虚假的可录制状态",
        },
        {
          id: "audio-003-retry",
          action: "恢复服务后点击重试",
          expected: "初始化成功，原错误消失且录制入口恢复可用",
        },
      ],
      source,
    },
  },
  {
    input: {
      case_key: "AUDIO-004",
      title: "正常开始录制并实时显示录制状态",
      module: "录制控制",
      priority: "P0",
      case_type: "功能",
      tags: ["开始录制", "主流程", "冒烟"],
      preconditions: ["麦克风权限已开启", "音频服务初始化成功", "存储空间充足"],
      steps: [
        {
          id: "audio-004-start",
          action: "点击开始录制并持续说话 10 秒",
          expected: "只创建一条录音，计时、音量反馈和录制状态持续更新",
        },
      ],
      source,
    },
  },
  {
    input: {
      case_key: "AUDIO-005",
      title: "快速连续点击开始时只创建一次录制",
      module: "录制控制",
      priority: "P1",
      case_type: "并发",
      tags: ["防重复", "连续点击"],
      preconditions: ["页面处于可录制状态"],
      steps: [
        {
          id: "audio-005-repeat",
          action: "在 1 秒内连续多次点击开始录制",
          expected: "系统只启动一个录制任务，不产生重复音频或叠加计时",
        },
      ],
      source,
    },
  },
  {
    input: {
      case_key: "AUDIO-006",
      title: "存储空间不足时阻止录制并明确提示",
      module: "录制控制",
      priority: "P0",
      case_type: "边界",
      tags: ["存储空间", "容量边界"],
      preconditions: ["麦克风权限已开启", "设备可用存储空间低于产品阈值"],
      steps: [
        {
          id: "audio-006-start",
          action: "点击开始录制",
          expected: "录制不启动，提示空间不足及处理建议，不留下空白记录",
        },
      ],
      source,
    },
  },
  {
    input: {
      case_key: "AUDIO-007",
      title: "麦克风被其他应用占用时启动失败可恢复",
      module: "录制控制",
      priority: "P0",
      case_type: "异常",
      tags: ["麦克风占用", "设备冲突"],
      preconditions: ["麦克风权限已开启", "麦克风被其他应用独占"],
      steps: [
        {
          id: "audio-007-busy",
          action: "点击开始录制",
          expected: "系统不进入录制状态，并提示麦克风当前不可用",
        },
        {
          id: "audio-007-retry",
          action: "释放麦克风后再次点击开始",
          expected: "无需重启即可正常开始录制",
        },
      ],
      source,
    },
  },
  {
    input: {
      case_key: "AUDIO-008",
      title: "录制中音频波形与输入音量同步更新",
      module: "实时音频",
      priority: "P1",
      case_type: "功能",
      tags: ["波形", "音量", "实时反馈"],
      preconditions: ["已开始录制", "环境允许改变输入音量"],
      steps: [
        {
          id: "audio-008-volume",
          action: "依次保持静音、轻声说话和正常音量说话",
          expected: "波形随输入强弱变化，界面持续响应且不会错误停止录制",
        },
      ],
      source,
    },
  },
  {
    input: {
      case_key: "AUDIO-009",
      title: "长时间静音不会意外结束录制",
      module: "实时音频",
      priority: "P1",
      case_type: "边界",
      tags: ["静音", "超时边界"],
      preconditions: ["已开始录制"],
      steps: [
        {
          id: "audio-009-silence",
          action: "保持静音超过自动检测阈值后继续说话",
          expected: "系统按产品规则保持或提示状态；继续输入的声音被完整录入",
        },
      ],
      source,
    },
  },
  {
    input: {
      case_key: "AUDIO-010",
      title: "切换蓝牙音频设备后录制连续且设备状态正确",
      module: "中断与恢复",
      priority: "P1",
      case_type: "兼容性",
      tags: ["蓝牙", "设备切换", "音频路由"],
      preconditions: ["已开始录制", "蓝牙耳机已配对"],
      steps: [
        {
          id: "audio-010-connect",
          action: "录制中连接蓝牙耳机并继续说话",
          expected: "页面显示当前输入设备，切换过程有明确反馈且应用不崩溃",
        },
        {
          id: "audio-010-disconnect",
          action: "断开蓝牙耳机并继续说话",
          expected: "输入路由按系统规则恢复，最终音频可正常播放且时间轴连续",
        },
      ],
      source,
    },
  },
  {
    input: {
      case_key: "AUDIO-011",
      title: "来电打断后按规则暂停并恢复录制",
      module: "中断与恢复",
      priority: "P0",
      case_type: "状态",
      tags: ["来电", "音频中断", "恢复"],
      preconditions: ["移动设备正在录制", "设备可接收测试来电"],
      steps: [
        {
          id: "audio-011-call",
          action: "录制中接听来电后结束通话",
          expected: "录制按系统规则暂停或安全结束，页面状态与实际录音状态一致",
        },
        {
          id: "audio-011-resume",
          action: "通话结束后恢复录制",
          expected: "系统可恢复且不覆盖中断前音频，不产生重复片段",
        },
      ],
      source,
    },
  },
  {
    input: {
      case_key: "AUDIO-012",
      title: "切后台和锁屏期间录制行为符合系统规则",
      module: "中断与恢复",
      priority: "P0",
      case_type: "状态",
      tags: ["后台", "锁屏", "状态同步"],
      preconditions: ["已开始录制", "已配置产品声明的后台录音能力"],
      steps: [
        {
          id: "audio-012-background",
          action: "将应用切到后台并锁屏，持续说话后返回应用",
          expected: "录制按产品规则继续或暂停，系统指示和页面状态一致，无静默丢失",
        },
      ],
      source,
    },
  },
  {
    input: {
      case_key: "AUDIO-013",
      title: "正常停止后生成完整且可播放的录音",
      module: "停止与保存",
      priority: "P0",
      case_type: "功能",
      tags: ["停止录制", "保存", "冒烟"],
      preconditions: ["已连续录制有效音频"],
      steps: [
        {
          id: "audio-013-stop",
          action: "点击停止并等待保存完成",
          expected: "计时停止且不再采集音频，只生成一条时长正确、可播放的记录",
        },
      ],
      source,
    },
  },
  {
    input: {
      case_key: "AUDIO-014",
      title: "保存失败后重试不会产生重复记录",
      module: "停止与保存",
      priority: "P0",
      case_type: "异常",
      tags: ["保存失败", "重试", "幂等"],
      preconditions: ["已完成一段录制", "模拟首次保存失败"],
      steps: [
        {
          id: "audio-014-fail",
          action: "停止录制并触发保存失败",
          expected: "本地临时音频不丢失，页面说明失败原因并提供重试",
        },
        {
          id: "audio-014-retry",
          action: "恢复服务后多次点击重试",
          expected: "最终只产生一条完整记录，临时数据在确认成功后清理",
        },
      ],
      source,
    },
  },
  {
    input: {
      case_key: "AUDIO-015",
      title: "播放、暂停和拖动进度后定位准确",
      module: "回放与管理",
      priority: "P0",
      case_type: "功能",
      tags: ["播放", "暂停", "进度条"],
      preconditions: ["存在一条已保存且内容已知的录音"],
      steps: [
        {
          id: "audio-015-play",
          action: "播放录音，暂停后拖动到不同时间点继续播放",
          expected: "播放状态、当前时间和进度条同步，定位内容与目标时间一致",
        },
      ],
      source,
    },
  },
  {
    input: {
      case_key: "AUDIO-016",
      title: "删除录音前确认且删除后不可继续访问",
      module: "回放与管理",
      priority: "P1",
      case_type: "数据",
      tags: ["删除", "确认", "数据一致性"],
      preconditions: ["存在一条已保存录音"],
      steps: [
        {
          id: "audio-016-cancel",
          action: "点击删除后取消确认",
          expected: "录音及其元数据保持不变",
        },
        {
          id: "audio-016-confirm",
          action: "再次删除并确认",
          expected: "记录从列表移除，缓存与详情不可继续访问且不会误删其他录音",
        },
      ],
      source,
    },
  },
  {
    input: {
      case_key: "AUDIO-017",
      title: "达到最大录制时长时安全停止并保存",
      module: "性能与稳定性",
      priority: "P0",
      case_type: "边界",
      tags: ["最大时长", "自动停止", "数据完整性"],
      preconditions: ["最大录制时长已配置", "设备存储空间充足"],
      steps: [
        {
          id: "audio-017-limit",
          action: "持续录制至最大允许时长",
          expected: "到达上限前有明确提示，到达上限后安全停止并保存完整音频",
        },
      ],
      source,
    },
  },
  {
    input: {
      case_key: "AUDIO-018",
      title: "长时间录制的资源占用与稳定性符合指标",
      module: "性能与稳定性",
      priority: "P1",
      case_type: "性能",
      tags: ["长时间运行", "CPU", "内存", "功耗"],
      preconditions: ["性能监控工具已开启", "设备电量和存储空间充足"],
      steps: [
        {
          id: "audio-018-record",
          action: "持续录制产品规定的稳定性测试时长并周期性操作页面",
          expected: "无崩溃、卡死或音频损坏，CPU、内存、温升和功耗不超过验收指标",
        },
      ],
      source,
    },
  },
];
