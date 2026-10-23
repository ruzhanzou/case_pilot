import assert from 'node:assert/strict';
import test from 'node:test';
import { sourceRefText } from '../lib/source-ref-text';

test('review preserves original evidence and locator without printing storage fields', () => {
  const result = sourceRefText([{label: '规则.xlsx', locator: '规则!A2', excerpt: '锁定1140秒\n返回E419', document_id: 'internal-id'}]);
  assert.equal(result, '1. 规则.xlsx / 规则!A2\n锁定1140秒\n返回E419');
});
test('structured reuse provenance exposes source case and reason without raw JSON', () => {
  const result = sourceRefText([{label:'旧版用例.xlsx', locator:'行2', excerpt:JSON.stringify({source_key:'excel:opaque-key', action:'modify', case_key:'OLD-001', revision:2, reason:'420秒改为300秒'})}]);
  assert.equal(result, '1. 旧版用例.xlsx / 行2\nOLD-001 · V2 · 420秒改为300秒');
});
test('empty references and JSON requirement excerpts remain unambiguous', () => {
  assert.equal(sourceRefText([]), '—');
  assert.equal(sourceRefText([{label:'接口响应', excerpt:'{"code":"E731"}'}]), '1. 接口响应\n{"code":"E731"}');
});
