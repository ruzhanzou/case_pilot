import type { Locale } from "@/lib/i18n";

const labels: Record<Locale, Record<string, string>> = {
  "zh-CN": {
    queued: "等待执行",
    running: "正在执行",
    awaiting_confirmation: "等待确认",
    awaiting_intent: "等待选择操作",
    awaiting_collection: "等待选择集合",
    awaiting_target: "待确认或补充",
    completed: "已完成",
    skipped: "已跳过",
    failed: "执行失败",
    cancelled: "已取消",
  },
  en: {
    queued: "Queued",
    running: "Running",
    awaiting_confirmation: "Awaiting confirmation",
    awaiting_intent: "Choose an action",
    awaiting_collection: "Choose a collection",
    awaiting_target: "Confirm or clarify",
    completed: "Completed",
    skipped: "Skipped",
    failed: "Failed",
    cancelled: "Cancelled",
  },
};

export function operationStatusLabels(locale: Locale): Record<string, string> {
  return labels[locale];
}

export function operationStatusLabel(status: string, locale: Locale): string {
  return labels[locale][status] ?? (locale === "zh-CN" ? "处理中" : "Processing");
}
