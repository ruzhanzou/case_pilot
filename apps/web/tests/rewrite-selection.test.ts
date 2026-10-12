import { test } from 'node:test';
import assert from 'node:assert/strict';
import { matchesRewriteScope, toggleRewriteSelection, type RewriteSelection } from '../lib/rewrite-selection';
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
