import assert from 'node:assert/strict';
import test from 'node:test';
import { caseContentRows } from '../lib/case-content';
test('case-level checks are independent of procedure length without losing content', () => {
  const rows = caseContentRows('Open\nEnter credentials\nSubmit', 'A session is established');
  assert.deepEqual(rows.map(s => s.action).filter(Boolean), ['Open','Enter credentials','Submit']);
  assert.deepEqual(rows.map(s => s.expected).filter(Boolean), ['A session is established']);
  assert.equal(rows[2].expected, '');
  assert.deepEqual(caseContentRows('Submit', 'Session exists\nAccount matches').map(s => s.expected), ['Session exists','Account matches']);
});
