"use client";

import type { ConversationDto, WorkspaceCandidateDto } from '@/lib/casepilot-api';
import { candidateBrief } from '@/lib/candidate-planning';
import { planningActionLabels, pointAction } from '@/lib/planning-consumption';

export function CandidatePointLinks({ candidate, conversation, onOpen }: {
  candidate: WorkspaceCandidateDto;
  conversation: ConversationDto;
  onOpen: (version: number, pointId: string) => void;
}) {
  const brief = candidateBrief(conversation, candidate);
  const planning = brief?.content.planning;
  const ids = [...new Set(candidate.snapshot.test_point_ids ?? [])];
  return <section className="candidate-point-links" aria-label="候选关联测试点">
    <span className="point-links-label">测试点</span>
    {!ids.length && <span>未提供测试点关联</span>}
    {ids.map(id => {
      const point = planning?.test_points.find(point => point.id === id);
      const source = planning?.reuse?.decisions.find(item => item.point_id === id)?.source;
      return <div className="candidate-point-link" key={id}>
        <button type="button" title={point?.title ?? id} disabled={!point || !brief} onClick={() => brief && onOpen(brief.version, id)}>
          {brief ? `V${brief.version} · ` : ''}{point?.title ?? id}
        </button>
        {point && planning && <details className="point-link-source"><summary>{planningActionLabels[pointAction(planning, id)]}</summary><small>生成策略：{planningActionLabels[pointAction(planning, id)]}{source && pointAction(planning, id) !== 'new' ? ` · 来源：${source.label} / ${source.locator}` : ''}</small></details>}
        {!point && <small>原规划不可用，无法定位</small>}
      </div>;
    })}
  </section>;
}
