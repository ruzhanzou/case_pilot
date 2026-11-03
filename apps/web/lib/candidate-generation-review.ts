import type { ConversationDto, WorkspaceCandidateDto } from "./casepilot-api";

type ReviewNote = { code: string; message: string; objectId?: string; severity?: string };
export type CandidateReviewGroup = {
  key: string;
  count: number;
  status: "pending_manual" | "not_assessed";
  notes: ReviewNote[];
};

/** Generation diagnostics do not certify the current candidate or its coverage. */
export function candidateReviewGroups(
  conversation: Pick<ConversationDto, "generation_reviews" | "messages">,
  candidates: WorkspaceCandidateDto[],
): CandidateReviewGroup[] {
  const groups = new Map<string, CandidateReviewGroup>();
  for (const candidate of candidates) {
    const jobId = candidate.generation_job_id;
    const key = jobId ?? "manual";
    if (groups.has(key)) {
      groups.get(key)!.count += 1;
      continue;
    }
    const review = jobId ? conversation.generation_reviews?.[jobId] : undefined;
    const trusted = review?.authority === "server_generation_job"
      && review.generation_job_id === jobId
      && review.independent_quality_verified === false
      && ["pending_manual", "not_assessed"].includes(review.status)
      && Array.isArray(review.issues);
    const notes: ReviewNote[] = [];
    if (trusted) {
      for (const issue of review.issues) {
        if (typeof issue?.message === "string") notes.push({ code: issue.code, message: issue.message, severity: issue.severity, ...(issue.object_id ? { objectId: issue.object_id } : {}) });
      }
    }
    if (jobId) {
      // Old API messages retain useful notes, but never gain verified status.
      for (const message of conversation.messages.filter(item => item.related_job_id === jobId)) {
        const issues = message.metadata.generation_quality_issues;
        if (!Array.isArray(issues)) continue;
        for (const issue of issues) {
          if (issue && typeof issue === "object" && "message" in issue && typeof issue.message === "string") {
            notes.push({ code: "code" in issue && typeof issue.code === "string" ? issue.code : "unknown", message: issue.message, ...("severity" in issue && typeof issue.severity === "string" ? { severity: issue.severity } : {}), ...("object_id" in issue && typeof issue.object_id === "string" ? { objectId: issue.object_id } : {}) });
          }
        }
      }
    }
    const merged = new Map<string, ReviewNote>();
    const rank = new Map<string, number>([["error", 3], ["warning", 2], ["unknown", 1], ["info", 0]]);
    for (const note of notes) {
      const identity = JSON.stringify([note.code, note.objectId, note.message]);
      const prior = merged.get(identity);
      if (!prior || (rank.get(note.severity ?? "unknown") ?? 1) > (rank.get(prior.severity ?? "unknown") ?? 1)) merged.set(identity, note);
    }
    groups.set(key, { key, count: 1, status: trusted ? review.status : "not_assessed", notes: [...merged.values()] });
  }
  return [...groups.values()];
}
