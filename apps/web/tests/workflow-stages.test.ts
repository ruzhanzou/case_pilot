import assert from 'node:assert/strict';
import test from 'node:test';
import { summarizeWorkflowStages } from '../lib/workflow-stages';
test('batch records collapse to ordered phases with the latest status', () => {
  const stages = [{ stage: 'generate', status: 'running' }, { stage: 'audit', status: 'completed' }, { stage: 'generate', status: 'completed' }, { stage: 'audit', status: 'failed' }];
  assert.deepEqual(summarizeWorkflowStages(stages), [{stage:'generate',status:'completed'}, {stage:'audit',status:'failed'}]);
  assert.equal(stages.length, 4);
  assert.deepEqual(summarizeWorkflowStages([]), []);
});
