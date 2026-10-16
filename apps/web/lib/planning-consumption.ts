import type { TestPlanningDto } from './casepilot-api';

export type PlanningAction = 'new' | 'reuse' | 'modify' | 'exclude' | 'copy';
export const planningActionLabels: Record<PlanningAction, string> = {
  copy: '复制为新用例', new: '新增用例', reuse: '直接复用', modify: '基于历史修改', exclude: '不纳入本次',
};

export function pointAction(planning: TestPlanningDto, pointId: string): PlanningAction {
  return planning.reuse?.user_choices?.[pointId]
    ?? planning.reuse?.decisions.find(item => item.point_id === pointId)?.action ?? 'new';
}

export function consumptionSummary(planning: TestPlanningDto, selected?: string[]) {
  const selectedIds = selected?.length ? new Set(selected) : null;
  const decisions = new Map(planning.reuse?.decisions.map(item => [item.point_id, item.action]));
  const counts = { new: 0, reuse: 0, modify: 0, exclude: 0, copy: 0, included: 0 };
  for (const point of planning.test_points) {
    if (selectedIds && !selectedIds.has(point.id)) continue;
    const action = planning.reuse?.user_choices?.[point.id] ?? decisions.get(point.id) ?? 'new';
    counts[action]++;
    if (action !== 'exclude') counts.included++;
  }
  return counts;
}
