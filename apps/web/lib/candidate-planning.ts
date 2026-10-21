import type { ConversationDto, WorkspaceCandidateDto } from './casepilot-api';

/** Resolve against the generation record, never against the latest planning version. */
export function candidateBrief(conversation: ConversationDto, candidate: WorkspaceCandidateDto) {
  if (!candidate.generation_job_id) return undefined;
  const message = conversation.messages.find(message => message.related_job_id === candidate.generation_job_id && typeof message.metadata.brief_version === 'number');
  return message ? conversation.test_briefs.find(brief => brief.version === message.metadata.brief_version) : undefined;
}
