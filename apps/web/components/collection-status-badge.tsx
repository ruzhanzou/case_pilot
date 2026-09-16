import {
  CheckCircle2,
  CircleDashed,
  ClipboardCheck,
  FileSearch,
  LoaderCircle,
  Sparkles,
} from "lucide-react";
import { useI18n } from "@/lib/i18n";

export type CollectionLifecycleStatus =
  | "empty"
  | "brief_drafting"
  | "brief_review"
  | "generating"
  | "candidate_review"
  | "maintenance"
  | "importing";

const statusDetails = {
  empty: { en: "Empty", zh: "空集合", tone: "neutral", icon: CircleDashed },
  brief_drafting: {
    en: "Drafting brief", zh: "整理测试说明",
    tone: "processing",
    icon: LoaderCircle,
  },
  brief_review: {
    en: "Brief awaiting review", zh: "测试说明待确认",
    tone: "attention",
    icon: FileSearch,
  },
  generating: { en: "AI generating", zh: "AI 生成中", tone: "processing", icon: Sparkles },
  candidate_review: {
    en: "Candidates awaiting review", zh: "候选待评审",
    tone: "attention",
    icon: ClipboardCheck,
  },
  maintenance: {
    en: "Active", zh: "正式维护",
    tone: "ready",
    icon: CheckCircle2,
  },
  importing: { en: "Importing", zh: "导入中", tone: "processing", icon: LoaderCircle },
} satisfies Record<
  CollectionLifecycleStatus,
  { en: string; zh: string; tone: string; icon: typeof CircleDashed }
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
  const { pick } = useI18n();
  const details = statusDetails[status];
  const label = pick(details.en, details.zh);
  const Icon = details.icon;
  const spinning = ["brief_drafting", "generating", "importing"].includes(
    status,
  );

  return (
    <span
      className={`collection-status collection-status--${details.tone}${compact ? " is-compact" : ""}`}
      aria-label={pick(`Collection status: ${label}`, `用例集状态：${label}`)}
      title={pick(`Collection status: ${label}`, `用例集状态：${label}`)}
    >
      <Icon size={compact ? 12 : 13} className={spinning ? "auth-spinner" : ""} />
      {label}
    </span>
  );
}
