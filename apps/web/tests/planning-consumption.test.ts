import assert from 'node:assert/strict';
import test from 'node:test';
import { consumptionSummary, pointAction } from '../lib/planning-consumption';
import type { TestPlanningDto } from '../lib/casepilot-api';

const planning = {
  feature_points: [],
  test_points: ['a', 'b', 'c'].map(id => ({ id, title: id, objective: id, feature_point_ids: [] })),
  reuse: { strategy: 'change', source_count: 2, summary: { reuse: 1, modify: 1, new: 1 }, note: '',
    decisions: [{ point_id: 'a', action: 'reuse', reason: '未变' }, { point_id: 'b', action: 'modify', reason: '变更' }, { point_id: 'c', action: 'new', reason: '新增' }],
    user_choices: { a: 'new', c: 'exclude' } },
} satisfies TestPlanningDto;

test('display reflects persisted reviewer choices rather than original model totals', () => {
  assert.equal(pointAction(planning, 'a'), 'new');
  assert.deepEqual(consumptionSummary(planning), { copy: 0, new: 1, reuse: 0, modify: 1, exclude: 1, included: 2 });
  assert.deepEqual(consumptionSummary(planning, ['c']), { copy: 0, new: 0, reuse: 0, modify: 0, exclude: 1, included: 0 });
});

test('restoring a suggestion reveals the original action', () => {
  const restored = { ...planning, reuse: { ...planning.reuse, user_choices: {} } };
  assert.equal(pointAction(restored, 'a'), 'reuse');
  assert.equal(consumptionSummary(restored, ['a']).included, 1);
});
