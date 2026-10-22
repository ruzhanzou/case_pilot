"use client";

import { memo } from "react";
import type { TestCaseDto } from "@/lib/casepilot-api";
import { useI18n } from "@/lib/i18n";

export type AssetProvenance = Record<string, { case_key: string; revision: string; collections: { id: string; name: string }[] }>;
type SourceCase = Pick<TestCaseDto, "case_key" | "source_refs"> & { source?: string };

/** Source information lives with its case, not in a second collection-wide table. */
export const CaseSource = memo(function CaseSource({ item, provenance }: { item: SourceCase; provenance?: AssetProvenance[string] }) {
  const { pick } = useI18n();
  const reference = (item.source_refs ?? []).map(ref => {
    try {
      const value = JSON.parse(ref.excerpt ?? "{}");
      return value && typeof value === "object" && !Array.isArray(value)
        ? { source_label: ref.label?.replace(/^(修改参考|复用) · /, ""), source_locator: ref.locator, ...value } : {};
    } catch { return {}; }
  }).find(ref => ref.source_key && ["reuse", "modify"].includes(ref.action));
  const origin = reference ?? provenance;
  const excel = reference?.source_key?.startsWith("excel:");
  const refs = [...new Set((item.source_refs ?? []).map(ref => [ref.label, ref.locator].filter(Boolean).join(" / ")).filter(Boolean))];
  const sourceName = origin
    ? (Array.isArray(origin.collections) ? origin.collections : []).map((c: { name: string }) => c.name).join("、") || (excel ? reference.source_label || pick("Excel attachment", "Excel 附件") : pick("Case management", "用例管理"))
    : refs.join("；") || item.source || pick("Not recorded", "未记录来源");
  const manual = item.source?.includes("人工") || item.source === "manual" || refs.some(ref => ref.includes("人工创建"));
  const kind = origin ? reference?.action === "modify" ? "modify" : "reuse" : manual ? "manual" : refs.length ? "new" : "unknown";
  const label = { modify: pick("Adapted", "参考改写"), reuse: pick("Reused", "直接复用"), manual: pick("Manual", "人工创建"), new: pick("Generated", "全新生成"), unknown: pick("Not recorded", "未记录来源") }[kind];
  return <details className="case-source-inline" data-testid="case-source-details">
    <summary><span className="task-source-badge" data-action={kind}>{label}</span><span className="case-source-inline__name" title={sourceName}>{sourceName}</span></summary>
    <dl>
      <dt>{pick("Source", "来源")}</dt><dd>{sourceName}</dd>
      {origin && <><dt>{pick("Original case / version", "原用例 / 版本")}</dt><dd>{origin.case_key || (excel ? reference.source_locator || pick("Not recorded", "未记录编号") : item.case_key)} / {origin.revision ?? pick("Version not recorded", "未记录版本")}</dd></>}
      {reference?.reason && <><dt>{pick("Reason / changes", "理由 / 变化说明")}</dt><dd>{reference.reason}</dd></>}
      {origin && refs.length > 0 && <><dt>{pick("References", "参考资料")}</dt><dd>{refs.join("；")}</dd></>}
    </dl>
  </details>;
});
