import type { CaseChangeSetDto, ConversationDto } from "./casepilot-api";

/** A refresh may outlive its navigation. Check ownership after every read. */
export async function refreshCurrentWorkspace(options: {
  isCurrent: () => boolean;
  loadWorkspace: () => Promise<ConversationDto>;
  applyWorkspace: (workspace: ConversationDto) => void;
  loadChangeSet: (id: string) => Promise<CaseChangeSetDto>;
  applyChangeSet: (changeSet: CaseChangeSetDto) => void;
}): Promise<ConversationDto | null> {
  if (!options.isCurrent()) return null;
  const workspace = await options.loadWorkspace();
  if (!options.isCurrent()) return null;
  options.applyWorkspace(workspace);
  const review = workspace.operation_plan?.operations.find(
    item => item.status === "awaiting_confirmation" && item.related_change_set_id,
  );
  if (review?.related_change_set_id) {
    const changeSet = await options.loadChangeSet(review.related_change_set_id);
    if (!options.isCurrent()) return null;
    if (changeSet.status === "ready") options.applyChangeSet(changeSet);
  }
  return workspace;
}

/** An old observer must neither update a new thread nor clear a newer job. */
export function createJobObserverGuard(
  navigation: { active: boolean },
  currentNavigation: { current: { active: boolean } },
  watchedJob: { current: string },
  jobId: string,
): () => boolean {
  return () => navigation.active && currentNavigation.current === navigation && watchedJob.current === jobId;
}
