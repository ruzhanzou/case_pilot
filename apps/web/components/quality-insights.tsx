"use client";

import type { TestCase } from "@/lib/mock-data";
import { Activity, AlertTriangle, CheckCircle2, Workflow } from "lucide-react";

type QualityInsightsProps = {
  testCases: TestCase[];
};

export function QualityInsights({ testCases }: QualityInsightsProps) {
  const passed = testCases.filter((item) => item.status === "通过").length;
  const risks = testCases.filter((item) => item.status === "不通过" || item.status === "堵塞").length;
  const automated = testCases.filter((item) => item.automated).length;
  const modules = [...new Set(testCases.map((item) => item.module))];

  return (
    <section className="feature-page">
      <header className="feature-page__title">
        <div>
          <h1>质量洞察</h1>
          <p>汇总当前空间的用例状态、风险分布和自动化覆盖。</p>
        </div>
        <span className="insight-freshness"><Activity size={15} />数据更新于刚刚</span>
      </header>

      <div className="insight-metrics">
        <article><span><CheckCircle2 size={18} /></span><div><strong>{passed}</strong><p>已通过用例</p></div><small>{testCases.length ? Math.round((passed / testCases.length) * 100) : 0}%</small></article>
        <article><span><AlertTriangle size={18} /></span><div><strong>{risks}</strong><p>风险用例</p></div><small>需要关注</small></article>
        <article><span><Workflow size={18} /></span><div><strong>{automated}</strong><p>自动化绑定</p></div><small>{testCases.length ? Math.round((automated / testCases.length) * 100) : 0}%</small></article>
      </div>

      <div className="insight-grid">
        <article className="insight-card">
          <header><h2>模块覆盖</h2><span>{modules.length} 个模块</span></header>
          <div className="coverage-bars">
            {modules.map((module) => {
              const moduleCases = testCases.filter((item) => item.module === module);
              const coverage = Math.max(28, Math.round((moduleCases.length / Math.max(1, testCases.length)) * 100));
              return <div key={module}><span><strong>{module}</strong><small>{moduleCases.length} 条用例</small></span><i><b style={{ width: `${coverage}%` }} /></i><em>{coverage}%</em></div>;
            })}
          </div>
        </article>
        <article className="insight-card">
          <header><h2>待办与风险</h2><span>按优先级</span></header>
          <div className="risk-tasks">
            <div><span className="priority priority--p0">P0</span><p><strong>补充高风险用例评审</strong><small>{testCases.filter((item) => item.priority === "P0" && item.status === "Pending").length} 条 Pending</small></p></div>
            <div><span className="priority priority--p1">P1</span><p><strong>处理失败与堵塞用例</strong><small>{risks} 条需要负责人确认</small></p></div>
            <div><Workflow size={17} /><p><strong>提升自动化覆盖</strong><small>{testCases.length - automated} 条尚未绑定</small></p></div>
          </div>
        </article>
      </div>
    </section>
  );
}
