import type { ConversationTarget } from "./casepilot-api";
export type WorkbenchSelection = { schema_version: 1; version: number; active_collection_id: string | null; targets: ConversationTarget[]; items: {ref: string; kind: string; version: string; label: string; case_id?: string; candidate_ref?: string}[]; changed_by?: string };
export function canonicalSelection(value: unknown): WorkbenchSelection | null {
  if (!value || typeof value !== "object") return null;
  const input = value as WorkbenchSelection;
  return input.schema_version === 1 && Number.isSafeInteger(input.version) && input.version >= 0 && Array.isArray(input.targets) && Array.isArray(input.items) ? input : null;
}

/** Serial CAS: queued old intentions are invalidated on any failed acknowledgement. */
export function createSelectionQueue<T, R>(patch: (version: number, input: T) => Promise<R>, versionOf: (result: R) => number) {
  let version = 0, epoch = 0, pending = 0;
  let failure: unknown = null;
  let tail: Promise<unknown> = Promise.resolve();
  return {
    get version() { return version; },
    get pending() { return pending > 0; },
    rebase(next: number) { version = next; epoch++; failure = null; },
    async wait() { await tail; if (failure) throw failure; },
    submit(input: T): Promise<R> {
      const ticket = epoch;
      pending++;
      const request = tail.catch(() => undefined).then(async () => {
        if (ticket !== epoch || failure) throw failure ?? new Error("Selection changed. Review it before continuing.");
        try {
          const result = await patch(version, input);
          if (ticket !== epoch) throw new Error("Selection changed. Review it before continuing.");
          version = versionOf(result);
          return result;
        } catch (error) { if (ticket === epoch) { failure = error; epoch++; } throw error; }
      }).finally(() => { pending--; });
      tail = request;
      return request;
    },
  };
}

/** Legacy clients saved wrappers; canonical writers may leave bare targets.
 * Never derive a broader module/collection scope from a malformed case target.
 */
export function legacySelectionTargets(context: Record<string, unknown>, fallbackLabel: string): { target: ConversationTarget; label: string; key: string }[] {
  if (canonicalSelection(context.workbench_selection)) return [];
  if (!Array.isArray(context.selected_targets)) return [];
  return context.selected_targets.flatMap((raw) => {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return [];
    const item = raw as Record<string, unknown>;
    const value = "target" in item ? item.target : item;
    if (!value || typeof value !== "object" || Array.isArray(value)) return [];
    const target = value as ConversationTarget;
    if (!["case", "module", "condition", "previous_result"].includes(target.kind)) return [];
    for (const refs of [target.case_ids, target.candidate_refs]) {
      if (refs !== undefined && (!Array.isArray(refs) || refs.some(ref => typeof ref !== "string" || !ref.trim()))) return [];
    }
    if (target.kind === "case" && !(target.case_ids?.length || target.candidate_refs?.length)) return [];
    if (target.kind === "module" && (typeof target.module !== "string" || !target.module.trim())) return [];
    if (target.kind === "condition" && (typeof target.condition !== "string" || !target.condition.trim())) return [];
    if (target.kind === "previous_result" && (typeof target.source_operation_id !== "string" || !target.source_operation_id.trim())) return [];
    if (target.collection_id !== undefined && typeof target.collection_id !== "string") return [];
    return [{ target, label: typeof item.label === "string" ? item.label : target.module || fallbackLabel, key: JSON.stringify(target) }];
  });
}
