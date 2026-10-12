import type { ConversationTarget } from './casepilot-api';

export type RewriteSelection = { key: string; label: string; target: ConversationTarget };

export function toggleRewriteSelection(current: RewriteSelection[], target: ConversationTarget, label: string, countLabel = (count: number) => `${count} cases`): RewriteSelection[] {
  const key = JSON.stringify(target);
  if (target.kind !== 'case') return current.some(item => item.key === key)
    ? current.filter(item => item.key !== key) : [...current, { key, label, target }];
  const cases = new Set(current.flatMap(item => item.target.kind === 'case' ? item.target.case_ids ?? [] : []));
  const refs = new Set(current.flatMap(item => item.target.kind === 'case' ? item.target.candidate_refs ?? [] : []));
  const remove = (target.case_ids ?? []).every(id => cases.has(id)) && (target.candidate_refs ?? []).every(ref => refs.has(ref));
  if (!remove) return [...current, { key, label, target }];
  return current.flatMap(item => {
    if (item.target.kind !== 'case') return [item];
    const next = { ...item.target,
      case_ids: (item.target.case_ids ?? []).filter(id => !target.case_ids?.includes(id)),
      candidate_refs: (item.target.candidate_refs ?? []).filter(ref => !target.candidate_refs?.includes(ref)),
    };
    const count = next.case_ids.length + next.candidate_refs.length;
    if (!count) return [];
    const unchanged = count === (item.target.case_ids?.length ?? 0) + (item.target.candidate_refs?.length ?? 0);
    return [{ key: JSON.stringify(next), label: unchanged ? item.label : countLabel(count), target: next }];
  });
}

export function matchesRewriteScope(targets: ConversationTarget[], scope: Record<string, unknown>): boolean {
  if (targets.some(target => target.kind !== 'case' || target.collection_id)) return false;
  const same = (actual: string[], expected: unknown) => {
    const ids = new Set(actual);
    const other = new Set(Array.isArray(expected) ? expected as string[] : []);
    return ids.size === other.size && [...ids].every(id => other.has(id));
  };
  return same(targets.flatMap(target => target.case_ids ?? []), scope.case_ids)
    && same(targets.flatMap(target => target.candidate_refs ?? []), scope.candidate_refs);
}
