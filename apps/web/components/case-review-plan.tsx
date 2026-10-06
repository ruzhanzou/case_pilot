"use client";

import type { CaseChangeSetDto, TestCaseDto, WorkspaceCandidateDto } from "@/lib/casepilot-api";
import { useI18n } from "@/lib/i18n";
import { useMemo, useState } from "react";

export type CaseReviewFinding = {
  title: string;
  severity: "high" | "medium" | "low";
  case_refs: string[];
  evidence: string;
  recommendation: string;
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
};

const pageSize = 20;

export function CaseReviewPlan({ hidden = false, changedSinceReview = false, report, checkedCount, cases, candidates, candidateCases, onLocate, onEdit, onPrepareDelete, changeSet, busy }: Props) {
  const { pick } = useI18n();
  const [query, setQuery] = useState("");
  const [severity, setSeverity] = useState("all");
  const [module, setModule] = useState("all");
  const [page, setPage] = useState(1);
  const [keepByFinding, setKeepByFinding] = useState<Record<number, string>>({});
  const [previewFinding, setPreviewFinding] = useState<number | null>(null);
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
    <section hidden={hidden} style={hidden ? { display: "none" } : undefined} className="case-review-plan" aria-label={pick("Review and change plan", "检查与修改计划")}>
      <header className="case-review-plan__header">
        <div>
          <span>{pick("REVIEW PLAN", "检查计划")}</span>
          <h2>{pick("Review and change plan", "检查与修改计划")}</h2>
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
      <ol className="case-review-plan__steps">
        <li className="is-done"><span>1</span><div><strong>{pick("Check cases", "检查用例")}</strong><small>{pick("Completed", "已完成")}</small></div></li>
        <li className="is-current"><span>2</span><div><strong>{pick("Review proposed changes", "审阅修改建议")}</strong><small>{pick("Choose which cases to keep", "确认每组保留的用例")}</small></div></li>
        <li><span>3</span><div><strong>{pick("Apply after confirmation", "确认后应用变更")}</strong><small>{changedSinceReview ? pick("Collection updated · Recheck recommended", "集合已更新 · 建议重新检查") : changeSet ? pick("Awaiting confirmation", "待确认") : pick("Not started", "尚未开始")}</small></div></li>
      </ol>

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

      <div className="case-review-plan__findings">
        {visibleFindings.map(({ finding, index }) => (
          <article key={`${index}-${finding.title}`} className="case-review-plan__finding">
            <div className="case-review-plan__finding-head">
              <span className={`case-review-plan__severity is-${finding.severity}`}>
                {finding.severity === "high" ? pick("High", "高") : finding.severity === "medium" ? pick("Medium", "中") : pick("Low", "低")}
              </span>
              <strong>{finding.title}</strong>
              <small>#{index + 1}</small>
            </div>
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
              const isDuplicateFinding = /重复|冗余|相似|duplicate|redundan|overlap/i.test(`${finding.title} ${finding.recommendation}`);
              const kept = formalCases.find((item) => item.id === keepByFinding[index]);
              const removable = kept ? formalCases.filter((item) => item.id !== kept.id) : [];
              return isDuplicateFinding && formalCases.length > 1 ? (
                <div className="case-review-plan__decision">
                  <strong>{pick("Choose one case to keep", "选择一条保留用例")}</strong>
                  <div className="case-review-plan__choices">{formalCases.map((item) => (
                    <div key={item.id} className="case-review-plan__choice"><label><input type="radio" name={`keep-${index}`} checked={keepByFinding[index] === item.id} onChange={() => { setKeepByFinding((current) => ({ ...current, [index]: item.id })); setPreviewFinding(null); }} />{item.case_key}</label><button type="button" onClick={() => onEdit(item)}>{pick("Edit", "编辑")}</button></div>
                  ))}</div>
                  {previewFinding === index && kept ? (
                    <div className="case-review-plan__preview">
                      <p>{pick(`Keep ${kept.case_key}; propose soft deleting ${removable.map((item) => item.case_key).join(", ")}.`, `保留 ${kept.case_key}；拟软删除 ${removable.map((item) => item.case_key).join("、")}。`)}</p>
                      <div className="case-review-plan__actions"><button type="button" onClick={() => setPreviewFinding(null)}>{pick("Back", "返回")}</button><button type="button" className="is-danger" disabled={busy || Boolean(changeSet)} onClick={() => void onPrepareDelete(removable.map((item) => item.id))}>{pick("Create deletion review", "生成删除审阅单")}</button></div>
                    </div>
                  ) : <button type="button" disabled={!kept || busy || Boolean(changeSet)} onClick={() => setPreviewFinding(index)}>{pick("Preview changes", "预览变更")}</button>}
                </div>
              ) : formalCases.length === 1 ? <button className="case-review-plan__edit" type="button" onClick={() => onEdit(formalCases[0])}>{pick("Edit case", "编辑用例")}</button> : null;
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
