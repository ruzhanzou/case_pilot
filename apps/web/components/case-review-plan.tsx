"use client";

import type { CaseChangeSetDto, TestCaseDto, WorkspaceCandidateDto, TaskReviewDecisions } from "@/lib/casepilot-api";
import { useI18n } from "@/lib/i18n";
import { useMemo, useState } from "react";

export type CaseReviewFinding = {
  title: string;
  severity: "high" | "medium" | "low";
  case_refs: string[];
  evidence: string;
  recommendation: string;
  basis?: "requirement" | "potential";
  relationship?: "duplicate" | "overlap" | "contains" | "quality" | "coverage" | null;
  unique_coverage?: string[];
  requirement_refs?: string[];
};

export type CaseReviewReport = {
  summary: string;
  findings: CaseReviewFinding[];
  limitations: string[];
};

type Props = {
  hidden?: boolean;
  changedSinceReview?: boolean;
  report: CaseReviewReport;
  checkedCount: number;
  cases: TestCaseDto[];
  candidates: WorkspaceCandidateDto[];
  candidateCases: TestCaseDto[];
  onLocate: (caseId: string) => void;
  onEdit: (testCase: TestCaseDto) => void;
  onPrepareDelete: (caseIds: string[]) => Promise<void>;
  changeSet: CaseChangeSetDto | null;
  busy: boolean;
  intent?: string;
  decisions?: TaskReviewDecisions;
  onSaveDecisions?: (decisions: TaskReviewDecisions) => void;
  onFollowup?: (action: "generate" | "rewrite" | "merge", findings: CaseReviewFinding[], keepIds?: string[]) => void;
};

const pageSize = 20;

export function CaseReviewPlan({ hidden = false, changedSinceReview = false, report, checkedCount, cases, candidates, candidateCases, onLocate, onEdit, onPrepareDelete, changeSet, busy, intent, onFollowup, decisions, onSaveDecisions }: Props) {
  const { pick } = useI18n();
  const [selectedFindings, setSelectedFindings] = useState<number[]>(decisions?.selected ?? []);
  const [ignoredFindings, setIgnoredFindings] = useState<number[]>(decisions?.ignored ?? []);
  const [query, setQuery] = useState("");
  const [severity, setSeverity] = useState("all");
  const [module, setModule] = useState("all");
  const [page, setPage] = useState(1);
  const [keepByFinding, setKeepByFinding] = useState<Record<number, string>>(decisions?.keep_by_finding ?? {});
  const [previewFinding, setPreviewFinding] = useState<number | null>(null);
  const saveDecisions = (selected: number[], ignored: number[], keep = keepByFinding) => {
    setSelectedFindings(selected);
    setIgnoredFindings(ignored);
    setKeepByFinding(keep);
    onSaveDecisions?.({ selected, ignored, keep_by_finding: keep });
  };
  const caseByRef = useMemo(() => {
    const byRef = new Map([...cases, ...candidateCases].map((item) => [item.id, item]));
    const byId = new Map([...cases, ...candidateCases].map((item) => [item.id, item]));
    candidates.forEach((candidate) => {
      const testCase = byId.get(candidate.id);
      if (testCase) byRef.set(candidate.ref, testCase);
    });
    return byRef;
  }, [cases, candidates, candidateCases]);
  const modules = useMemo(() => [...new Set(report.findings.flatMap((finding) =>
    finding.case_refs.map((ref) => caseByRef.get(ref)?.module).filter((value): value is string => Boolean(value)),
  ))].sort((a, b) => a.localeCompare(b)), [caseByRef, report.findings]);
  const filtered = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    return report.findings.map((finding, index) => ({ finding, index })).filter(({ finding }) => {
      if (severity !== "all" && finding.severity !== severity) return false;
      const related = finding.case_refs.map((ref) => caseByRef.get(ref)).filter((item): item is TestCaseDto => Boolean(item));
      if (module !== "all" && !related.some((item) => item.module === module)) return false;
      return !normalized || [
        finding.title, finding.evidence, finding.recommendation,
        ...related.flatMap((item) => [item.case_key, item.title, item.module]),
      ].some((value) => value.toLocaleLowerCase().includes(normalized));
    });
  }, [caseByRef, module, query, report.findings, severity]);
  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const currentPage = Math.min(page, pageCount);
  const visibleFindings = filtered.slice((currentPage - 1) * pageSize, currentPage * pageSize);

  return (
    <section hidden={hidden} style={hidden ? { display: "none" } : undefined} className="case-review-plan" aria-label={pick("Case workspace", "用例工作区")}>
      <header className="case-review-plan__header">
        <div>
          <span>{pick("REVIEW & CHANGES", "检查与变更")}</span>
          <h2>{intent === "COVERAGE_ANALYZE" ? pick("Coverage findings", "覆盖分析结果") : intent === "CASE_DEDUP" ? pick("Redundancy findings", "冗余检查结果") : pick("Quality findings", "质量评审结果")}</h2>
          <p>{pick(
            "Findings are suggestions. Review and confirm each change before applying it.",
            "以下为检查建议；每项变更均需审阅确认后应用。",
          )}</p>
        </div>
        <div className="case-review-plan__stats">
          <strong>{checkedCount}</strong><span>{pick("cases checked", "已检查用例")}</span>
          <strong>{report.findings.length}</strong><span>{pick("finding groups", "问题分组")}</span>
        </div>
      </header>

      {changedSinceReview && <p role="status" className="case-review-plan__empty">{pick("The collection has changed since this review. These findings describe the earlier version; review again to confirm what remains.", "此报告生成后集合已变更。以下结论对应检查时的版本，请重新检查以确认剩余问题。")}</p>}


      <div className="case-review-plan__toolbar">
        <input
          type="search"
          aria-label={pick("Search findings", "搜索问题分组")}
          placeholder={pick("Search case ID, title, or recommendation", "搜索用例编号、标题或建议")}
          value={query}
          onChange={(event) => { setQuery(event.target.value); setPage(1); }}
        />
        <select aria-label={pick("Filter severity", "按严重程度筛选")} value={severity} onChange={(event) => { setSeverity(event.target.value); setPage(1); }}>
          <option value="all">{pick("All severities", "全部级别")}</option>
          <option value="high">{pick("High", "高")}</option>
          <option value="medium">{pick("Medium", "中")}</option>
          <option value="low">{pick("Low", "低")}</option>
        </select>
        <select aria-label={pick("Filter module", "按模块筛选")} value={module} onChange={(event) => { setModule(event.target.value); setPage(1); }}>
          <option value="all">{pick("All modules", "全部模块")}</option>
          {modules.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
        <span>{pick(`${filtered.length} groups`, `${filtered.length} 组`)}</span>
      </div>

      {onFollowup && <div className="task-finding-actions">
        <span>{pick(`${selectedFindings.length} findings selected`, `已选择 ${selectedFindings.length} 项发现`)}</span>
        {intent === "COVERAGE_ANALYZE" && <button type="button" disabled={busy || changedSinceReview || !selectedFindings.length} onClick={() => onFollowup("generate", selectedFindings.map((index) => report.findings[index]))}>{pick("Generate missing cases", "生成补充用例")}</button>}
        {intent === "CASE_REVIEW" && <button type="button" disabled={busy || changedSinceReview || !selectedFindings.length} onClick={() => onFollowup("rewrite", selectedFindings.map((index) => report.findings[index]))}>{pick("Prepare fixes", "生成修改方案")}</button>}
        <button type="button" disabled={!selectedFindings.length || busy} onClick={() => { saveDecisions([], [...new Set([...ignoredFindings, ...selectedFindings])]); }}>{pick("Ignore selected", "忽略所选")}</button>
        {ignoredFindings.length > 0 && <button type="button" onClick={() => saveDecisions(selectedFindings, [])}>{pick("Restore ignored findings", "恢复忽略项")}</button>}
      </div>}
      <div className="case-review-plan__findings">
        {visibleFindings.map(({ finding, index }) => (
          <article key={`${index}-${finding.title}`} className="case-review-plan__finding" data-ignored={ignoredFindings.includes(index)}>
            <div className="case-review-plan__finding-head">
              {onFollowup && <input type="checkbox" aria-label={pick(`Select finding ${index + 1}`, `选择第 ${index + 1} 项发现`)} checked={selectedFindings.includes(index)} disabled={busy || ignoredFindings.includes(index)} onChange={() => saveDecisions(selectedFindings.includes(index) ? selectedFindings.filter((value) => value !== index) : [...selectedFindings, index], ignoredFindings)} />}
              <span className={`case-review-plan__severity is-${finding.severity}`}>
                {finding.severity === "high" ? pick("High", "高") : finding.severity === "medium" ? pick("Medium", "中") : pick("Low", "低")}
              </span>
              <strong>{finding.title}</strong>
              <small>#{index + 1}</small>
            </div>
            {intent === "COVERAGE_ANALYZE" && <p className="task-finding-basis">{finding.basis === "requirement" ? pick("Requirement-backed gap", "有需求依据的缺口") : pick("Potential gap · needs verification", "潜在缺口 · 待核实")}</p>}
            {finding.relationship && <p className="task-finding-basis">{({ duplicate: pick("Duplicate", "完全重复"), overlap: pick("Partial overlap", "部分重叠"), contains: pick("Contains other coverage", "包含关系"), quality: pick("Quality issue", "质量问题"), coverage: pick("Coverage gap", "覆盖缺口") })[finding.relationship]}</p>}
            {Boolean(finding.requirement_refs?.length) && <p className="task-finding-basis">{pick("Requirement references", "需求依据")}：{finding.requirement_refs?.join(" · ")}</p>}
            {Boolean(finding.unique_coverage?.length) && <ul className="task-unique-coverage">{finding.unique_coverage?.map((item, i) => <li key={i}>{item}</li>)}</ul>}
            <div className="case-review-plan__cases">
              {finding.case_refs.map((ref) => {
                const testCase = caseByRef.get(ref);
                return testCase ? (
                  <button key={ref} type="button" title={testCase.title} onClick={() => onLocate(testCase.id)}>
                    {testCase.case_key}
                  </button>
                ) : <span key={ref}>{pick("Case reference unavailable · Review again", "用例引用不可定位，请重新检查")}</span>;
              })}
            </div>
            {(() => {
              const formalIds = new Set(cases.map((item) => item.id));
              const formalCases = [...new Map(finding.case_refs.map((ref) => caseByRef.get(ref)).filter((item): item is TestCaseDto => item !== undefined && formalIds.has(item.id)).map((item) => [item.id, item])).values()];
              const isDuplicateFinding = intent === "CASE_DEDUP" || /重复|冗余|相似|duplicate|redundan|overlap/i.test(`${finding.title} ${finding.recommendation}`);
              const kept = formalCases.find((item) => item.id === keepByFinding[index]);
              const removable = kept ? formalCases.filter((item) => item.id !== kept.id) : [];
              return isDuplicateFinding && formalCases.length > 1 ? (
                <div className="case-review-plan__decision">
                  <strong>{pick("Choose one case to keep", "选择一条保留用例")}</strong>
                  <div className="case-review-plan__choices">{formalCases.map((item) => (
                    <div key={item.id} className="case-review-plan__choice"><label><input type="radio" name={`keep-${index}`} checked={keepByFinding[index] === item.id} onChange={() => { saveDecisions(selectedFindings, ignoredFindings, { ...keepByFinding, [index]: item.id }); setPreviewFinding(null); }} />{item.case_key}</label><button type="button" disabled={busy || Boolean(changeSet)} onClick={() => onEdit(item)}>{pick("Edit", "编辑")}</button></div>
                  ))}</div>
                  {onFollowup && <button type="button" disabled={!kept || busy || changedSinceReview} onClick={() => onFollowup("merge", [finding], kept ? [kept.id] : [])}>{pick("Merge unique coverage into kept case", "将独有覆盖合并到保留用例")}</button>}
                  {finding.relationship === "overlap" || finding.relationship === "contains" ? <p>{pick("Preserve unique checks in a merge proposal before considering deletion.", "请先审阅合并方案并保留独有验证点，再决定是否删除。")}</p> : previewFinding === index && kept ? (
                    <div className="case-review-plan__preview">
                      <p>{pick(`Keep ${kept.case_key}; propose soft deleting ${removable.map((item) => item.case_key).join(", ")}.`, `保留 ${kept.case_key}；拟软删除 ${removable.map((item) => item.case_key).join("、")}。`)}</p>
                      <div className="case-review-plan__actions"><button type="button" onClick={() => setPreviewFinding(null)}>{pick("Back", "返回")}</button><button type="button" className="is-danger" disabled={busy || changedSinceReview || Boolean(changeSet)} onClick={() => void onPrepareDelete(removable.map((item) => item.id))}>{pick("Create deletion review", "生成删除审阅单")}</button></div>
                    </div>
                  ) : <button type="button" disabled={!kept || busy || changedSinceReview || Boolean(changeSet)} onClick={() => setPreviewFinding(index)}>{pick("Preview changes", "预览变更")}</button>}
                </div>
              ) : formalCases.length === 1 ? <button className="case-review-plan__edit" type="button" disabled={busy || Boolean(changeSet)} onClick={() => onEdit(formalCases[0])}>{pick("Edit case", "编辑用例")}</button> : null;
            })()}
            <details>
              <summary>{pick("Evidence and proposed change", "依据与修改建议")}</summary>
              <p><b>{pick("Evidence", "依据")}：</b>{finding.evidence}</p>
              <p><b>{pick("Proposal", "建议")}：</b>{finding.recommendation}</p>
            </details>
          </article>
        ))}
        {filtered.length === 0 && <p className="case-review-plan__empty">{pick("No matching findings", "没有匹配的问题分组")}</p>}
      </div>

      <footer className="case-review-plan__footer">
        <span>{pick(`Page ${currentPage} of ${pageCount}`, `第 ${currentPage} / ${pageCount} 页`)}</span>
        <div>
          <button type="button" disabled={currentPage === 1} onClick={() => setPage(currentPage - 1)}>{pick("Previous", "上一页")}</button>
          <button type="button" disabled={currentPage === pageCount} onClick={() => setPage(currentPage + 1)}>{pick("Next", "下一页")}</button>
        </div>
      </footer>
      {report.limitations.length > 0 && (
        <details className="case-review-plan__limitations">
          <summary>{pick("Review limitations", "检查限制")}</summary>
          <ul>{report.limitations.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul>
        </details>
      )}
    </section>
  );
}
