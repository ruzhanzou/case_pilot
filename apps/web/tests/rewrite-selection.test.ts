import { test } from 'node:test';
import assert from 'node:assert/strict';
import { matchesRewriteScope, rewriteSelectionLabel, toggleRewriteSelection, type RewriteSelection } from '../lib/rewrite-selection';
const group = (ids: string[], refs: string[] = []): RewriteSelection => {
  const target = { kind: 'case' as const, case_ids: ids, candidate_refs: refs };
  return { key: JSON.stringify(target), label: 'Selected cases', target };
};
test('unchecking a restored grouped case removes membership instead of adding duplicates', () => {
  const result = toggleRewriteSelection([group(['a', 'b'])], { kind: 'case', case_ids: ['a'] }, 'A');
  assert.deepEqual(result.map(item => item.target.case_ids), [['b']]);
  assert.equal(matchesRewriteScope(result.map(i => i.target), { case_ids: ['b'] }), true);
});
test('removing the final formal or candidate target leaves an empty selection', () => {
  assert.deepEqual(toggleRewriteSelection([group(['a'])], { kind: 'case', case_ids: ['a'] }, 'A'), []);
  assert.deepEqual(toggleRewriteSelection([group([], ['ref'])], { kind: 'case', candidate_refs: ['ref'] }, 'A'), []);
});
test('confirmation compares assets across groups, order and duplicates', () => {
  assert.equal(matchesRewriteScope([group(['a']).target, group(['b', 'a'], ['ref']).target], { case_ids: ['b', 'a'], candidate_refs: ['ref'] }), true);
  assert.equal(matchesRewriteScope([group(['a']).target], { case_ids: ['a', 'b'] }), false);
  assert.equal(matchesRewriteScope([{ kind: 'module', module: '登录' }], { case_ids: ['a'] }), false);
});
test('subtracts from every batch while retaining candidate membership', () => {
  const result = toggleRewriteSelection([group(['a', 'b'], ['ref']), group(['a', 'c'])], { kind: 'case', case_ids: ['a'] }, 'A');
  assert.equal(matchesRewriteScope(result.map(i => i.target), { case_ids: ['b', 'c'], candidate_refs: ['ref'] }), true);
});


test('current titles replace persisted selection labels without changing the target', () => {
  const selection = group(['a']);
  const original = structuredClone(selection);
  assert.equal(rewriteSelectionLabel(selection, [{ id: 'a', title: 'Renamed case' }], []), 'Renamed case');
  assert.deepEqual(selection, original);
  const candidates = [{ id: 'candidate-id', ref: 'candidate-ref', snapshot: { title: 'Updated candidate' } }];
  assert.equal(rewriteSelectionLabel(group(['candidate-id']), [], candidates), 'Updated candidate');
  assert.equal(rewriteSelectionLabel(group([], ['candidate-ref']), [], candidates), 'Updated candidate');
});

test('missing assets and grouped or cross-collection selections retain their own labels', () => {
  const cases = [{ id: 'a', title: 'Renamed case' }];
  for (const selection of [group(['missing']), group(['a', 'b']),
    { ...group(['a']), target: { ...group(['a']).target, collection_id: 'other' } },
    { key: 'module', label: 'Selected cases', target: { kind: 'module' as const, module: 'a' } }]) {
    assert.equal(rewriteSelectionLabel(selection, cases, []), 'Selected cases');
  }
});
