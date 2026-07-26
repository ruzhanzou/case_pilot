"use client";

import { CaseStatusBadge } from "@/components/case-status";
import type { TestCase } from "@/lib/mock-data";
import { ChevronDown, Search, Tag, Workflow } from "lucide-react";

type AllCasesProps = {
  testCases: TestCase[];
  onOpenCase: (id: string) => void;
};

export function AllCases({ testCases, onOpenCase }: AllCasesProps) {
  return (
    <section className="feature-page">
      <header className="feature-page__title">
        <div>
          <h1>全部用例</h1>
          <p>跨用例集查看当前空间的测试资产、标签与自动化绑定状态。</p>
        </div>
        <div className="feature-page__stats">
          <span><strong>{testCases.length}</strong>用例</span>
          <span><strong>{testCases.filter((item) => item.priority === "P0").length}</strong>P0</span>
          <span><strong>{testCases.filter((item) => item.automated).length}</strong>已自动化</span>
        </div>
      </header>

      <div className="feature-filterbar">
        <label><Search size={16} /><input placeholder="搜索名称、编号或标签" /></label>
        <button type="button">全部用例集<ChevronDown size={15} /></button>
        <button type="button">全部优先级<ChevronDown size={15} /></button>
        <button type="button">全部状态<ChevronDown size={15} /></button>
      </div>

      <div className="feature-table-wrap">
        <table className="feature-table">
          <thead><tr><th>编号与名称</th><th>优先级</th><th>模块</th><th>状态</th><th>标签</th><th>自动化</th></tr></thead>
          <tbody>
            {testCases.map((item) => (
              <tr key={item.id} onClick={() => onOpenCase(item.id)}>
                <td><code>{item.id}</code><strong>{item.title}</strong></td>
                <td><span className={`priority priority--${item.priority.toLowerCase()}`}>{item.priority}</span></td>
                <td>{item.module}</td>
                <td><CaseStatusBadge status={item.status} compact /></td>
                <td><div className="case-tag-list"><Tag size={13} />{item.tags.map((tag) => <span className="case-tag" key={tag}>{tag}</span>)}</div></td>
                <td>{item.automated ? <span className="automation-badge"><Workflow size={12} />已绑定</span> : <span className="automation-empty">未绑定</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
