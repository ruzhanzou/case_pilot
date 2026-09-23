import type { ExecutionRunSummaryDto } from "./casepilot-api";

export function matchesExecutionSearch(run: ExecutionRunSummaryDto, query: string): boolean {
  const terms = query.normalize("NFKC").trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const text = [run.description, run.source_name, run.collection_name, run.creator_name,
    ...run.assignee_names, ...run.contributor_names].filter(Boolean).join(" ").normalize("NFKC").toLocaleLowerCase();
  return terms.every((term) => text.includes(term));
}
