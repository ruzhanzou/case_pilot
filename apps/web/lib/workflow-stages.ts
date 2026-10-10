/** Batch attempts are execution records, not separate workflow steps. */
export function summarizeWorkflowStages<T extends { stage: string }>(stages: T[]): T[] {
  const latest = new Map<string, T>();
  for (const stage of stages) {
    if (stage.stage.startsWith("requirement.batch.")) continue;
    latest.set(stage.stage, stage);
  }
  return [...latest.values()];
}
