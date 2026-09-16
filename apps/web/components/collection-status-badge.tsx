import {
  CheckCircle2,
  CircleDashed,
  ClipboardCheck,
  FileSearch,
  LoaderCircle,
  Sparkles,
} from "lucide-react";

export type CollectionLifecycleStatus =
  | "empty"
  | "brief_drafting"
  | "brief_review"
  | "generating"
  | "candidate_review"
  | "maintenance"
  | "importing";

const statusDetails = {
  empty: { label: "空集合", tone: "neutral", icon: CircleDashed },
  brief_drafting: {
    label: "整理测试说明",
    tone: "processing",
    icon: LoaderCircle,
  },
  brief_review: {
    label: "测试说明待确认",
    tone: "attention",
    icon: FileSearch,
  },
  generating: { label: "AI 生成中", tone: "processing", icon: Sparkles },
  candidate_review: {
    label: "候选待评审",
    tone: "attention",
    icon: ClipboardCheck,
  },
  maintenance: {
    label: "正式维护",
    tone: "ready",
    icon: CheckCircle2,
  },
  importing: { label: "导入中", tone: "processing", icon: LoaderCircle },
} satisfies Record<
  CollectionLifecycleStatus,
  { label: string; tone: string; icon: typeof CircleDashed }
>;

export function collectionStatusFromPhase(
  phase: string,
  caseCount: number,
): CollectionLifecycleStatus {
  if (
    phase === "brief_drafting" ||
    phase === "brief_review" ||
    phase === "generating" ||
    phase === "candidate_review"
  ) {
    return phase;
  }
  return caseCount ? "maintenance" : "empty";
}

export function CollectionStatusBadge({
  status,
  compact = false,
}: {
  status: CollectionLifecycleStatus;
  compact?: boolean;
}) {
  const details = statusDetails[status];
  const Icon = details.icon;
  const spinning = ["brief_drafting", "generating", "importing"].includes(
    status,
  );

  return (
    <span
      className={`collection-status collection-status--${details.tone}${compact ? " is-compact" : ""}`}
      aria-label={`用例集状态：${details.label}`}
      title={`用例集状态：${details.label}`}
    >
      <Icon size={compact ? 12 : 13} className={spinning ? "auth-spinner" : ""} />
      {details.label}
    </span>
  );
}
