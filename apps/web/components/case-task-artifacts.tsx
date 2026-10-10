"use client";

import { useState } from "react";
import { Streamdown } from "streamdown";
import type { GenerationStage, ConversationDto, TestCaseDto, WorkspaceCandidateDto } from "@/lib/casepilot-api";
import { candidatesForTask, type WorkspaceTask } from "@/lib/workspace-tasks";
import { useI18n } from "@/lib/i18n";

type Props = {
  generationProgress?: GenerationStage | null;
  task: WorkspaceTask;
  conversation: ConversationDto;
  busy: boolean;
  cases: TestCaseDto[];
  onLocate: (id: string) => void;
  onToggleCandidate: (candidate: WorkspaceCandidateDto) => void;
  onCommit: () => void;
  onBrief: (version: number) => void;
  onGenerate: () => void;
  onRefine?: () => void;
  pendingCandidateRefs?: string[];
};

export function CaseTaskArtifacts({ task, conversation, busy, cases, onLocate, onToggleCandidate, onCommit, onBrief, onGenerate, onRefine, generationProgress, pendingCandidateRefs = [] }: Props) {
  const { pick } = useI18n();
  if (task.message.intent === "CASE_QUERY") {
    const snapshots = task.operation?.result.query_cases;
    if (!Array.isArray(snapshots)) return null;
    return <QueryResults key={task.id} snapshots={snapshots as TestCaseDto[]} cases={cases} onLocate={onLocate} />;
  }
  const generation = task.message.intent === "CASE_GENERATE" ? task : task.versions?.findLast(round => round.operation?.intent === "CASE_GENERATE");
  if (!generation) return null;
  const candidates = candidatesForTask(task, conversation);
  const brief = conversation.test_briefs.filter((item) => item.source_operation_id === generation.operation?.id).at(-1);
  const currentBrief = conversation.test_briefs.at(-1);
  const canConfirmBrief = brief && brief.id === currentBrief?.id && conversation.context.phase === "brief_review" && !brief.content.open_questions.some((item) => item.blocking);
  const canEdit = candidates.some((item) => item.status === "candidate") && !["cancelled", "not_applied"].includes(task.status);
  const needsReview = candidates.some(item => item.status === "candidate" && item.included && pendingCandidateRefs.includes(item.ref));
  const canCommit = canEdit && !needsReview && candidates.some((item) => item.status === "candidate" && item.included);
  return <div className="task-generation-results">
    {brief && <section className="task-brief-result"><header><strong>{pick("Test scope", "测试范围")} · V{brief.version}</strong><button type="button" onClick={() => onBrief(brief.version)}>{pick("View full brief", "查看完整说明")}</button></header><p>{brief.content.test_object}</p><p>{brief.content.scope.join(" · ")}</p>{brief.content.open_questions.length > 0 && <ul>{brief.content.open_questions.map((item, index) => <li key={item.id ?? index}>{item.question}</li>)}</ul>}{canConfirmBrief && <button type="button" disabled={busy} onClick={onGenerate}>{pick("Confirm scope and generate", "确认范围并生成用例")}</button>}</section>}
    {generationProgress?.total_count && <section className="generation-progress-card" aria-label={pick("Generation progress", "生成进度")}>
      <strong>{pick(`${generationProgress.generated_count ?? 0} / ${generationProgress.total_count} cases verified`, `已核对 ${generationProgress.generated_count ?? 0} / ${generationProgress.total_count} 条`)}</strong>
      <progress max={generationProgress.total_count} value={generationProgress.generated_count ?? 0} aria-label={pick("Verified cases", "已核对用例数量")} />
      {generationProgress.active_batches?.length ? generationProgress.active_batches.map((batch) => <p key={batch.start}>{pick(`Cases ${batch.start}–${batch.start + batch.count - 1}`, `第 ${batch.start}–${batch.start + batch.count - 1} 条`)} · {batch.stage === "test_case.grounded" ? pick("Checking requirements", "核对需求中") : pick("Generating", "生成中")}{batch.retry_attempt > 0 ? pick(" · Retrying", " · 重试中") : ""}</p>) : (
<p>{generationProgress.name === "test_case.grounded" ? pick("Checking this batch against the original requirements", "正在根据原始需求核对本批用例") : pick("Generating the next batch", "正在生成下一批用例")}{generationProgress.batch_start_index && generationProgress.batch_count ? pick(` · Cases ${generationProgress.batch_start_index}–${generationProgress.batch_start_index + generationProgress.batch_count - 1}`, ` · 第 ${generationProgress.batch_start_index}–${generationProgress.batch_start_index + generationProgress.batch_count - 1} 条`) : ""}</p>
      )}
      {!!generationProgress.retry_attempt && <p role="status">{pick("Retrying this batch; verified cases are preserved.", "当前批次正在重试，已核对结果已保留。")}</p>}
      <small>{pick("Verified batches appear below. Final review unlocks after all batches pass validation.", "已核对的批次会立即展示在下方；全部生成并通过校验后可统一审核采纳。")}</small>
    </section>}
    {candidates.length > 0 && <section className="task-result-cases" aria-label={pick("Candidate results", "候选结果")}>
      <header>
        <h4>{pick(`${candidates.filter(item => item.status !== "archived").length} candidate cases`, `${candidates.filter(item => item.status !== "archived").length} 条候选用例`)}</h4>
        {canEdit && <div className="task-candidate-actions">
          {onRefine && <button type="button" disabled={busy} onClick={onRefine}>{pick("Edit cases", "修改用例")}</button>}
          <button type="button" className="is-primary" disabled={busy || !canCommit} onClick={onCommit}>
            {pick(`Accept selected (${candidates.filter(item => item.status === "candidate" && item.included).length})`, `采纳已选（${candidates.filter(item => item.status === "candidate" && item.included).length}）`)}
          </button>
        </div>}
      </header>
      {candidates.some(item => item.status === "generating") && <p role="status" data-testid="generation-batch-preview">{pick("Batch preview — results appear as they finish. Adoption is available after generation and validation complete.", "分批预览：已生成内容会逐批更新，整轮生成和校验完成后可采纳。")}</p>}
      {needsReview && <p role="status">{pick("Review the AI changes for selected candidates before adding them to the official collection.", "所选候选存在待审阅的 AI 修改，请先采纳或丢弃建议，再纳入正式集合。")}</p>}
      {candidates.map((candidate, index) => <details key={candidate.id}><summary>{candidate.status === "candidate" && <input type="checkbox" aria-label={pick(`Include ${candidate.ref}`, `纳入 ${candidate.ref}`)} checked={candidate.included} disabled={busy} onClick={(event) => event.stopPropagation()} onChange={() => onToggleCandidate(candidate)} />}<strong>{index + 1}. {candidate.ref} · {String(candidate.snapshot.title ?? "")}</strong><small>V{candidate.version} · {candidate.status === "generating" ? pick("Preview · not yet adoptable", "生成预览 · 暂不可采纳") : candidate.status === "incorporated" ? pick("Added", "已纳入") : candidate.status === "excluded" ? pick("Not included", "未纳入") : candidate.status === "archived" ? pick("Historical candidate", "历史候选") : pick("Awaiting review", "待审阅")}</small></summary><p>{String(candidate.snapshot.module ?? "")} · {pick("Priority", "优先级")}：<span className={`priority-badge priority-badge--${String(candidate.snapshot.priority).toLowerCase()}`}>{String(candidate.snapshot.priority ?? "—")}</span> · {String(candidate.snapshot.case_type ?? "")}</p><p><strong>{pick("Preconditions", "前置条件")}</strong>：{((candidate.snapshot.preconditions ?? []) as string[]).join("；") || "—"}</p><strong>{pick("Procedure", "操作步骤")}</strong><Streamdown>{candidate.snapshot.steps.filter(step => step.action.trim()).map((step, index) => `${index + 1}. ${step.action}`).join("\n\n")}</Streamdown><strong>{pick("Case checkpoints", "用例校验点")}</strong><Streamdown>{candidate.snapshot.steps.filter(step => step.expected.trim()).map((step, index) => `${index + 1}. ${step.expected}`).join("\n\n")}</Streamdown>{candidate.status === "candidate" && <button type="button" onClick={() => onLocate(candidate.id)}>{pick("Edit candidate", "编辑候选")}</button>}</details>)}
    </section>}
  </div>;
}


function QueryResults({ snapshots, cases, onLocate }: Pick<Props, "cases" | "onLocate"> & { snapshots: TestCaseDto[] }) {
  const { pick } = useI18n();
  const [search, setSearch] = useState("");
  const [module, setModule] = useState("");
  const [page, setPage] = useState(0);
  const available = new Set(cases.map((item) => item.id));
  const modules = [...new Set(snapshots.map((item) => item.module))];
  const filtered = snapshots.filter((item) => (!module || item.module === module) &&
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
        {modules.map((name) => <option key={name} value={name}>{name || pick("Unassigned", "未分配模块")}</option>)}
      </select>
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
