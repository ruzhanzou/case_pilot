import assert from 'node:assert/strict';
import test from 'node:test';
import { candidateBrief } from '../lib/candidate-planning';
import type { ConversationDto, WorkspaceCandidateDto } from '../lib/casepilot-api';

test('candidate links stay on their generation version even when IDs are reused in a new brief', () => {
  const conversation = { messages: [{ related_job_id: 'job', metadata: { brief_version: 1 } }], test_briefs: [{ version: 1 }, { version: 2 }] } as unknown as ConversationDto;
  assert.equal(candidateBrief(conversation, { generation_job_id: 'job' } as WorkspaceCandidateDto)?.version, 1);
  assert.equal(candidateBrief(conversation, { generation_job_id: 'missing' } as WorkspaceCandidateDto), undefined);
  assert.equal(candidateBrief(conversation, { generation_job_id: null } as WorkspaceCandidateDto), undefined);
});
