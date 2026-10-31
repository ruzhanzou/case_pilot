import type { CaseChangeSetDto } from "./casepilot-api";

/** Both chat and the result pane submit this exact review selection. */
export function reviewableChangeRefs(changeSet: CaseChangeSetDto): string[] {
  if (changeSet.status !== "ready") return [];
  return changeSet.items.filter(item => !["applied", "rejected"].includes(item.status) && item.quality?.passed !== false).map(item => item.ref);
}
export function selectedReviewFields(changeSet: CaseChangeSetDto, selection: Record<string, string[]>): Record<string, string[]> {
  const refs = new Set(reviewableChangeRefs(changeSet));
  return Object.fromEntries(changeSet.items.filter(item => refs.has(item.ref)).map(item => [item.ref,
    (selection[item.ref] ?? []).filter(field => item.field_diff.some(diff => diff.field === field)),
  ]));
}
