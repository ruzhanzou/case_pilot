"use client";

import { CaseSource } from "@/components/workspace-case-sources";
import { CandidatePointLinks } from "@/components/candidate-point-links";
import { useState } from "react";
import { candidateBrief } from "@/lib/candidate-planning";
import { pointAction } from "@/lib/planning-consumption";
import { Streamdown } from "streamdown";
import type { GenerationStage, ConversationDto, TestCaseDto, WorkspaceCandidateDto } from "@/lib/casepilot-api";
import { candidatesForTask, type WorkspaceTask } from "@/lib/workspace-tasks";
import { useI18n } from "@/lib/i18n";

type Props = {
  readOnly?: boolean;
  generationProgress?: GenerationStage | null;
  task: WorkspaceTask;
  conversation: ConversationDto;
  busy: boolean;
  cases: TestCaseDto[];
  onLocate: (id: string) => void;
  onToggleCandidate: (candidate: WorkspaceCandidateDto) => void;
  onCommit: (candidateIds: string[]) => void;
  onBrief: (version: number) => void;
  onPoint: (version: number, pointId: string) => void;
  onGenerate: () => void;
  onRefine?: () => void;
  pendingCandidateRefs?: string[];
  onReviewChanges?: () => void;
};

export function CaseTaskArtifacts({ readOnly = false, task, conversation, busy, cases, onLocate, onToggleCandidate, onCommit, onBrief, onPoint, onGenerate, onRefine, onReviewChanges, generationProgress, pendingCandidateRefs = [] }: Props) {
  const { pick } = useI18n();
  const [candidateSearch, setCandidateSearch] = useState("");
  if (task.message.intent === "CASE_QUERY") {
    const snapshots = task.operation?.result.query_cases;
    if (!Array.isArray(snapshots)) return null;
    return <QueryResults key={task.id} snapshots={snapshots as TestCaseDto[]} cases={cases} onLocate={onLocate} />;
  }
  const generation = task.message.intent === "CASE_GENERATE" ? task : task.versions?.findLast(round => round.operation?.intent === "CASE_GENERATE");
  if (!generation) return null;
  const candidates = candidatesForTask(task, conversation);
  const visibleCandidates = candidates.filter(item => [item.ref, item.snapshot.title, item.snapshot.module].join(" ").toLocaleLowerCase().includes(candidateSearch.trim().toLocaleLowerCase()));
  const candidateJobIds = new Set(candidates.map(item => item.generation_job_id));
  const coveredPointIds = new Set(candidates.filter(candidate => ["candidate", "incorporated"].includes(candidate.status))
    .flatMap(candidate => candidate.snapshot.test_point_ids ?? []));
  const taskBrief = conversation.test_briefs.filter(item => item.source_operation_id === generation.operation?.id).at(-1);
  const plannedPoints = taskBrief?.content.planning?.test_points ?? [];
  const allPointsCovered = plannedPoints.length > 0 && plannedPoints.every(point => coveredPointIds.has(point.id));
  const qualityNotes = [...new Set(conversation.messages
    .filter(message => message.related_job_id && candidateJobIds.has(message.related_job_id))
    .flatMap(message => {
      const issues = message.metadata.generation_quality_issues;
      const missing = Array.isArray(issues) ? issues.filter(issue => issue?.code === "uncovered_test_point") : [];
      const repairedMissingPoints = missing.length > 0 && missing.every(issue => coveredPointIds.has(issue.object_id));
      return Array.isArray(issues) ? issues.flatMap(issue => {
        if (!issue || typeof issue.message !== "string") return [];
        if (issue.code === "uncovered_test_point" && coveredPointIds.has(issue.object_id)) return [];
        if (issue.code === "requirement_coverage_gap" && allPointsCovered && repairedMissingPoints) return [];
        return [issue.message];
      }) : [];
    }))];
  const brief = conversation.test_briefs.filter((item) => item.source_operation_id === generation.operation?.id).at(-1);
  const currentBrief = conversation.test_briefs.at(-1);
  const canConfirmBrief = !readOnly && brief && brief.id === currentBrief?.id && conversation.context.phase === "brief_review" && !brief.content.open_questions.some((item) => item.blocking);
  const canEdit = !readOnly && candidates.some((item) => item.status === "candidate") && !["cancelled", "not_applied"].includes(task.status);
  const needsReview = candidates.some(item => item.status === "candidate" && item.included && pendingCandidateRefs.includes(item.ref));
  const canCommit = canEdit && !needsReview && candidates.some((item) => item.status === "candidate" && item.included);
  return <div className="task-generation-results">
    {brief && <details key={`${brief.id}-${Boolean(canConfirmBrief)}`} className="task-brief-result" open={Boolean(canConfirmBrief) || brief.content.open_questions.length > 0}>
      <summary><strong>{pick("Test scope", "测试范围")} · V{brief.version}</strong><span>{brief.content.test_object}</span></summary>
      <div className="task-brief-body"><p>{brief.content.test_object}</p><p>{brief.content.scope.join(" · ")}</p>
        {brief.content.open_questions.length > 0 && <ul>{brief.content.open_questions.map((item, index) => <li key={item.id ?? index}>{item.question}</li>)}</ul>}
        <div className="task-brief-actions"><button type="button" onClick={() => onBrief(brief.version)}>{pick("View full brief", "查看完整说明")}</button>
          {canConfirmBrief && <button type="button" disabled={busy} onClick={onGenerate}>{pick("Confirm scope and generate", "确认范围并生成用例")}</button>}</div>
      </div>
    </details>}
    {generationProgress?.total_count && <section className="generation-progress-card" aria-label={pick("Generation progress", "生成进度")}>
      <strong>{pick(`${generationProgress.generated_count ?? 0} / ${generationProgress.total_count} cases ready for review`, `待审阅 ${generationProgress.generated_count ?? 0} / ${generationProgress.total_count} 条`)}</strong>
      <progress max={generationProgress.total_count} value={generationProgress.generated_count ?? 0} aria-label={pick("Cases ready for review", "待审阅用例数量")} />
      {generationProgress.active_batches?.length ? generationProgress.active_batches.map((batch) => <p key={batch.start}>{pick(`Cases ${batch.start}–${batch.start + batch.count - 1}`, `第 ${batch.start}–${batch.start + batch.count - 1} 条`)} · {batch.stage === "test_case.grounded" ? pick("Checking requirements", "核对需求中") : pick("Generating", "生成中")}{batch.retry_attempt > 0 ? pick(" · Retrying", " · 重试中") : ""}</p>) : (
<p>{generationProgress.name === "test_case.grounded" ? pick("Checking this batch against the original requirements", "正在根据原始需求核对本批用例") : pick("Generating the next batch", "正在生成下一批用例")}{generationProgress.batch_start_index && generationProgress.batch_count ? pick(` · Cases ${generationProgress.batch_start_index}–${generationProgress.batch_start_index + generationProgress.batch_count - 1}`, ` · 第 ${generationProgress.batch_start_index}–${generationProgress.batch_start_index + generationProgress.batch_count - 1} 条`) : ""}</p>
      )}
      {!!generationProgress.retry_attempt && <p role="status">{pick("Repairing incomplete cases; completed cases are preserved.", "正在修复未完成用例，已完成结果已保留。")}</p>}
      <small>{pick("Completed cases appear below after basic checks. Review them before accepting; unresolved items will be listed.", "通过基础校验的用例会展示在下方；生成结束后请人工审核再采纳，未完成项会单独列出。")}</small>
    </section>}
    {candidates.length > 0 && <section className="task-result-cases" data-testid="workspace-case-sources" aria-label={pick("Candidate results", "候选结果")}>
      <header>
        <div className="task-candidate-overview"><h4><span className="task-candidate-count">{candidates.filter(item => !["archived", "discarded"].includes(item.status)).length}</span> {pick("candidate cases", "条候选用例")}</h4><span className="task-candidate-stats">{pick(`${candidates.filter(item => item.status === "candidate").length} awaiting review · ${candidates.filter(item => item.status === "incorporated").length} added`, `待审阅 ${candidates.filter(item => item.status === "candidate").length} · 已纳入 ${candidates.filter(item => item.status === "incorporated").length}`)}</span></div>
        {canEdit && <div className="task-candidate-actions">
          {onRefine && <button type="button" disabled={busy} onClick={onRefine}>{pick("Edit cases", "修改用例")}</button>}
          <button type="button" className="is-primary" disabled={busy || !canCommit} onClick={() => onCommit(candidates.filter(item => item.status === "candidate" && item.included).map(item => item.id))}>
            {pick(`Add selected to collection (${candidates.filter(item => item.status === "candidate" && item.included).length})`, `纳入正式集合（${candidates.filter(item => item.status === "candidate" && item.included).length}）`)}
          </button>
        </div>}
      </header>
      {qualityNotes.length > 0 && <details className="task-generation-notes" aria-label={pick("Generation notes", "生成说明")} open={qualityNotes.some(note => !note.includes("已完成基础校验"))}>
        <summary>{pick("Generation checks", "生成校验说明")} · {qualityNotes.length}</summary>
        <ul>{qualityNotes.map(note => <li key={note}>{note}</li>)}</ul>
      </details>}
      {candidates.some(item => item.status === "generating") && <p role="status" data-testid="generation-batch-preview">{pick("Batch preview — results appear as they finish. Adoption is available after generation and validation complete.", "分批预览：已生成内容会逐批更新，整轮生成和校验完成后可采纳。")}</p>}
      {needsReview && <div><p role="status">{pick("Review the AI changes for selected candidates before adding them to the official collection.", "所选候选存在待审阅的 AI 修改，请先采纳或丢弃建议，再纳入正式集合。")}</p>{!readOnly && onReviewChanges && <button type="button" disabled={busy} onClick={onReviewChanges}>{pick("Review AI changes", "审阅 AI 修改")}</button>}</div>}
      <div className="task-candidate-filter"><input type="search" aria-label={pick("Search candidate results", "搜索候选结果")} placeholder={pick("Search title, ID or module", "搜索标题、编号或模块")} value={candidateSearch} onChange={event => setCandidateSearch(event.target.value)} /><span role="status">{visibleCandidates.length} / {candidates.length}</span>{candidateSearch && <button type="button" onClick={() => setCandidateSearch("")}>{pick("Clear filter", "清除筛选")}</button>}</div>
      {candidateSearch && !readOnly && <p className="task-filter-note">{pick("Filtering does not change selection. Acceptance includes selected cases outside these results.", "筛选不改变勾选状态，采纳包含筛选外已选的候选用例。")}</p>}
      {!visibleCandidates.length && <p role="status">{pick("No matching candidates. Clear the filter to view all.", "没有匹配的候选用例，可清除筛选查看全部。")}</p>}
      {visibleCandidates.map((candidate) => <details key={candidate.id}><summary>{!readOnly && candidate.status === "candidate" && <input type="checkbox" aria-label={pick(`Include ${candidate.ref}`, `纳入 ${candidate.ref}`)} checked={candidate.included} disabled={busy} onClick={(event) => event.stopPropagation()} onChange={() => onToggleCandidate(candidate)} />}<strong className="task-candidate-title">{candidates.indexOf(candidate) + 1}. {String(candidate.snapshot.title ?? "")}</strong><CandidateSource candidate={candidate} conversation={conversation} compact /><small>关联测试点 {(candidate.snapshot.test_point_ids ?? []).length} 个 · V{candidate.version} · {candidate.status === "generating" ? pick("Preview · not yet adoptable", "生成预览 · 暂不可采纳") : candidate.status === "incorporated" ? pick("Added", "已纳入") : candidate.status === "discarded" ? pick("Deleted candidate", "已删除候选") : candidate.status === "excluded" ? pick("Not included", "未纳入") : candidate.status === "archived" ? pick("Historical candidate", "历史候选") : pick("Awaiting review", "待审阅")}</small></summary><CaseSource item={{ case_key: candidate.ref, source_refs: candidate.snapshot.source_refs }} /><p className="task-candidate-reference">{pick("Candidate ID", "候选编号")}：{candidate.ref}</p><CandidatePointLinks candidate={candidate} conversation={conversation} onOpen={onPoint} /><p>{String(candidate.snapshot.module ?? "")} · {pick("Priority", "优先级")}：<span className={`priority-badge priority-badge--${String(candidate.snapshot.priority).toLowerCase()}`}>{String(candidate.snapshot.priority ?? "—")}</span> · {String(candidate.snapshot.case_type ?? "")}</p><p><strong>{pick("Preconditions", "前置条件")}</strong>：{((candidate.snapshot.preconditions ?? []) as string[]).join("；") || "—"}</p><strong>{pick("Procedure", "操作步骤")}</strong><Streamdown>{candidate.snapshot.steps.filter(step => step.action.trim()).map((step, index) => `${index + 1}. ${step.action}`).join("\n\n")}</Streamdown><strong>{pick("Case checkpoints", "用例校验点")}</strong><Streamdown>{candidate.snapshot.steps.filter(step => step.expected.trim()).map((step, index) => `${index + 1}. ${step.expected}`).join("\n\n")}</Streamdown>{!readOnly && candidate.status === "candidate" && <button type="button" onClick={() => onLocate(candidate.id)}>{pick("Edit candidate", "编辑候选")}</button>}</details>)}
    </section>}
  </div>;
}


function CandidateSource({ candidate, conversation, compact = false }: Pick<Props, "conversation"> & { candidate: WorkspaceCandidateDto; compact?: boolean }) {
  const { pick } = useI18n();
  const brief = candidateBrief(conversation, candidate);
  const planning = brief?.content.planning;
  const labels = { new: pick("New", "新增用例"), reuse: pick("Reused", "直接复用"), modify: pick("Modified from history", "基于历史修改"), copy: pick("Copied", "复制为新用例"), exclude: pick("Excluded", "不纳入本次") };
  const sources = [...new Map((candidate.snapshot.test_point_ids ?? []).flatMap(id => {
    if (!planning?.test_points.some(point => point.id === id)) return [];
    const action = pointAction(planning, id);
    const source = planning.reuse?.decisions.find(item => item.point_id === id)?.source;
    const label = action !== "new" && source ? [source.label, source.locator].filter(Boolean).join(" / ") : "";
    return [[`${action}-${label}`, { action, label }] as const];
  })).values()];
  const refs = [...new Set((candidate.snapshot.source_refs ?? []).map(ref => [ref.label, ref.locator].filter(Boolean).join(" / ")).filter(Boolean))];
  if (compact) return <span className="task-candidate-sources is-compact">{sources.length ? [...new Set(sources.map(source => source.action))].map(action => <span key={action} className="task-source-badge" data-action={action}>{labels[action]}</span>) : <span className="task-source-badge">{refs.length ? pick("Generated", "全新生成") : pick("Source not recorded", "未记录来源")}</span>}</span>;
  return <span className="task-candidate-sources">
    <span className="task-source-caption">{pick("Source", "用例来源")}</span>
    {sources.map(({ action, label }) => <span className="task-source-item" key={`${action}-${label}`}><span className="task-source-badge" data-action={action}>{labels[action]}</span>{label && <span>{label}</span>}</span>)}
    {refs.map(ref => <span key={ref} className="task-source-document">{ref}</span>)}
    {!sources.length && !refs.length && <span>{pick("Source not recorded", "未记录来源")}</span>}
    {brief && <span className="task-source-version">{pick("Test brief", "测试说明")} V{brief.version}</span>}
  </span>;
}


function QueryResults({ snapshots, cases, onLocate }: Pick<Props, "cases" | "onLocate"> & { snapshots: TestCaseDto[] }) {
  const { pick } = useI18n();
  const [search, setSearch] = useState("");
  const [module, setModule] = useState("");
  const [page, setPage] = useState(0);
  const available = new Set(cases.map((item) => item.id));
  const modules = [...new Set(snapshots.map((item) => item.module))];
  const filtered = snapshots.filter((item) => (!module || (item.module || "__unassigned__") === module) &&
    [item.case_key, item.title, item.module, item.priority].join(" ").toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  const pageCount = Math.max(1, Math.ceil(filtered.length / 20));
  const visible = filtered.slice(page * 20, (page + 1) * 20);
  return <section className="task-query-results" aria-label={pick("Query results", "查询结果")}>
    <div className="task-query-toolbar">
      <strong>{pick(`${snapshots.length} matching cases`, `匹配 ${snapshots.length} 条用例`)}</strong>
      <span>{pick("Read-only result", "只读查询结果")}</span>
      <input type="search" aria-label={pick("Search query results", "搜索查询结果")} placeholder={pick("Search ID or title", "搜索编号或标题")} value={search} onChange={(event) => { setSearch(event.target.value); setPage(0); }} />
      <select aria-label={pick("Filter by module", "按模块筛选")} value={module} onChange={(event) => { setModule(event.target.value); setPage(0); }}>
        <option value="">{pick("All modules", "全部模块")}</option>
        {modules.map((name) => <option key={name} value={name || "__unassigned__"}>{name || pick("Unassigned", "未分配模块")}</option>)}
      </select>
      {(search || module) && <button type="button" onClick={() => { setSearch(""); setModule(""); setPage(0); }}>{pick("Clear filters", "清除筛选")}</button>}
    </div>
    <div className="task-query-table-scroll">
      <table className="task-query-table">
        <caption>{pick("Cases at the time of this query. Open a case to see its current version.", "以下为查询时的用例快照，定位用例可查看当前版本。")}</caption>
        <thead><tr>{[pick("Case ID", "用例编号"), pick("Title / details", "用例标题 / 详情"), pick("Module", "所属模块"), pick("Priority", "优先级"), pick("Action", "操作")].map((label) => <th key={label} scope="col">{label}</th>)}</tr></thead>
        <tbody>{visible.map((item) => <tr key={item.id}>
          <td>{item.case_key}</td>
          <td><details><summary>{item.title}</summary>
            {!!item.preconditions?.length && <p><strong>{pick("Preconditions", "前置条件")}</strong><br />{item.preconditions.join("；")}</p>}
            <ol>{item.steps?.map((step, index) => <li key={index}>{step.action}<p>{pick("Expected", "预期")}：{step.expected}</p></li>)}</ol>
          </details></td>
          <td>{item.module}</td><td><span className="task-query-priority" data-priority={item.priority}>{item.priority}</span></td>
          <td><button type="button" disabled={!available.has(item.id)} onClick={() => onLocate(item.id)}>{available.has(item.id) ? pick("Locate case", "定位用例") : pick("Unavailable", "已不可用")}</button></td>
        </tr>)}</tbody>
      </table>
      {!filtered.length && <p className="task-query-empty">{snapshots.length ? pick("No cases match these filters.", "没有符合筛选条件的用例。") : pick("No matching cases found.", "未找到匹配的用例。")}</p>}
    </div>
    <footer className="task-query-pagination"><span role="status">{pick(`${filtered.length} cases · Page ${page + 1} / ${pageCount}`, `${filtered.length} 条用例 · 第 ${page + 1} / ${pageCount} 页`)}</span><button type="button" disabled={page === 0} onClick={() => setPage(page - 1)}>{pick("Previous", "上一页")}</button><button type="button" disabled={page + 1 >= pageCount} onClick={() => setPage(page + 1)}>{pick("Next", "下一页")}</button></footer>
  </section>;
}
