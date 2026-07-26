import type { TestCase } from "@/lib/mock-data";

export const caseStatusOptions: TestCase["status"][] = [
  "Pending",
  "通过",
  "不通过",
  "跳过",
  "堵塞",
];

export const caseStatusMeta: Record<
  TestCase["status"],
  { tone: "pending" | "passed" | "failed" | "skipped" | "blocked" }
> = {
  Pending: { tone: "pending" },
  通过: { tone: "passed" },
  不通过: { tone: "failed" },
  跳过: { tone: "skipped" },
  堵塞: { tone: "blocked" },
};

export function CaseStatusBadge({
  status,
  compact = false,
}: {
  status: TestCase["status"];
  compact?: boolean;
}) {
  const meta = caseStatusMeta[status];

  return (
    <span
      className={`case-status case-status--${meta.tone} ${
        compact ? "case-status--compact" : ""
      }`}
    >
      <i aria-hidden="true" />
      {status}
    </span>
  );
}
