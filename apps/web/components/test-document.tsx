"use client";

import { CaseStatusBadge } from "@/components/case-status";
import type { TestCase } from "@/lib/mock-data";
import { Check, Download, FileJson, FileText, Link2, ShieldAlert } from "lucide-react";

type TestDocumentProps = {
  collectionName: string;
  testCases: TestCase[];
};

export function TestDocument({ collectionName, testCases }: TestDocumentProps) {
  const modules = [...new Set(testCases.map((testCase) => testCase.module))];
  const passedCount = testCases.filter((testCase) => testCase.status === "通过").length;
  const pendingCount = testCases.filter((testCase) => testCase.status === "Pending").length;
  const highPriorityCount = testCases.filter((testCase) => testCase.priority === "P0").length;
  const markdown = `# ${collectionName}测试说明

## 1. 测试范围
${modules.length > 0 ? modules.join("、") : "尚未生成测试范围"}。

## 2. 风险与待确认项
- 当前有 ${pendingCount} 条 Pending 用例需要人工确认
- AI 生成内容需要结合原始需求材料复核

## 3. 覆盖概览
共 ${testCases.length} 条候选用例，其中 P0 ${highPriorityCount} 条，已通过 ${passedCount} 条。
`;

  const download = (format: "md" | "json") => {
    const content = format === "md"
      ? markdown
      : JSON.stringify({
          title: `${collectionName}测试说明`,
          modules,
          cases: testCases,
          status_summary: {
            pending: pendingCount,
            passed: passedCount,
          },
        }, null, 2);
    const blob = new Blob(
      [content],
      { type: format === "md" ? "text/markdown;charset=utf-8" : "application/json;charset=utf-8" },
    );
    const url = URL.createObjectURL(blob);
    const anchor = window.document.createElement("a");
    anchor.href = url;
    anchor.download = `${collectionName}测试说明.${format}`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="document-view">
      <div className="document-toolbar">
        <div><span className="live-dot" />结构化测试说明 · 与当前用例集实时同步</div>
        <div>
          <button type="button" onClick={() => download("json")}><FileJson size={15} />JSON</button>
          <button className="button-primary" type="button" onClick={() => download("md")}><Download size={15} />导出 Markdown</button>
        </div>
      </div>

      <article className="test-document">
        <header>
          <div className="doc-mark"><FileText size={20} /></div>
          <div><span>TEST DESIGN SPECIFICATION</span><h1>{collectionName}测试说明</h1></div>
          <small>集合基线 V1<br />更新于刚刚</small>
        </header>

        <div className="doc-meta">
          <div><span>数据来源</span><strong>{collectionName}</strong></div>
          <div><span>覆盖规模</span><strong><Check size={14} />{modules.length} 个模块</strong></div>
          <div><span>确认进度</span><strong>{passedCount} / {testCases.length} 条</strong></div>
        </div>

        <section>
          <span className="doc-section-number">01</span>
          <div>
            <h2>范围与目标</h2>
            <p>
              {testCases.length > 0
                ? `围绕${modules.join("、")}生成可执行测试用例，覆盖主流程、异常流程、边界值和关键校验点。所有 AI 生成内容先进入 Pending，确认后才能成为正式测试资产。`
                : "当前用例集尚未生成用例。请先通过对话补充测试目标或上传需求材料。"}
            </p>
          </div>
        </section>

        <section>
          <span className="doc-section-number">02</span>
          <div className="doc-section-wide"><h2>覆盖概览</h2>
            <div className="coverage-grid">
              <div><strong>{modules.length}</strong><span>业务模块</span></div>
              <div><strong>{testCases.length}</strong><span>测试点</span></div>
              <div><strong>{testCases.length}</strong><span>候选用例</span></div>
              <div><strong>{highPriorityCount}</strong><span>P0 用例</span></div>
            </div>
          </div>
        </section>

        <section>
          <span className="doc-section-number">03</span>
          <div className="doc-section-wide"><h2>风险与待确认项</h2>
            <div className="risk-row"><ShieldAlert size={17} /><div><strong>{pendingCount} 条 Pending 用例待确认</strong><p>建议逐条核对前置条件、执行步骤和校验点是否与需求事实一致。</p></div><span>高</span></div>
            <div className="risk-row"><ShieldAlert size={17} /><div><strong>AI 推断需要需求证据</strong><p>当前 Mock 生成结果用于流程验收，接入真实模型后需要保留来源定位与推断标记。</p></div><span>中</span></div>
          </div>
        </section>

        <section>
          <span className="doc-section-number">04</span>
          <div className="doc-section-wide"><h2>关键用例</h2>
            <table>
              <thead><tr><th>编号</th><th>用例名称</th><th>优先级</th><th>状态</th><th>追踪</th></tr></thead>
              <tbody>
                {testCases.slice(0, 6).map((testCase) => (
                  <tr key={testCase.id}>
                    <td>{testCase.id}</td>
                    <td>{testCase.title}</td>
                    <td><b>{testCase.priority}</b></td>
                    <td><CaseStatusBadge status={testCase.status} compact /></td>
                    <td><Link2 size={13} />{testCase.module}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </article>
    </div>
  );
}
