"use client";

import {
  CaseStatusBadge,
  caseStatusOptions,
} from "@/components/case-status";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { TestCase } from "@/lib/mock-data";
import { motion } from "motion/react";
import { Check, ChevronDown, PanelRightClose, RotateCcw, Sparkles, Workflow, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

const rewriteOptions = ["表达更清晰", "补充边界条件", "增加校验点"];

export function CaseInspector({
  testCase,
  onRequestReview,
  onCollapse,
  onStatusChange,
}: {
  testCase: TestCase;
  onRequestReview: () => void;
  onCollapse: () => void;
  onStatusChange: (status: TestCase["status"]) => void;
}) {
  const [mode, setMode] = useState<"idle" | "loading" | "preview" | "accepted">("idle");
  const [rewriteType, setRewriteType] = useState(rewriteOptions[2]);
  const rewriteTimer = useRef<number | null>(null);

  useEffect(() => () => {
    if (rewriteTimer.current !== null) window.clearTimeout(rewriteTimer.current);
  }, []);

  const requestRewrite = () => {
    setMode("loading");
    rewriteTimer.current = window.setTimeout(() => setMode("preview"), 850);
  };

  return (
    <aside className="inspector">
      <div className="inspector__heading">
        <div>
          <span className="eyebrow">用例详情</span>
          <h2>{testCase.id}</h2>
        </div>
        <div className="inspector__heading-actions">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                className="case-status-trigger"
                type="button"
                aria-label={`修改用例状态，当前为${testCase.status}`}
              >
                <CaseStatusBadge status={testCase.status} compact />
                <ChevronDown size={13} />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="case-status-menu">
              {caseStatusOptions.map((status) => (
                <DropdownMenuItem
                  className="case-status-option"
                  key={status}
                  onSelect={() => onStatusChange(status)}
                >
                  <CaseStatusBadge status={status} />
                  {status === testCase.status ? <Check size={15} /> : null}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
          <button type="button" onClick={onCollapse} aria-label="收起用例详情" title="收起用例详情">
            <PanelRightClose size={17} />
          </button>
        </div>
      </div>

      <div className="case-title-block">
        <div className="case-title-badges">
          <span className={`priority priority--${testCase.priority.toLowerCase()}`}>{testCase.priority}</span>
          {testCase.tags.map((tag) => <span className="case-tag" key={tag}>{tag}</span>)}
          {testCase.automated && <span className="automation-badge"><Workflow size={12} />已绑定自动化</span>}
        </div>
        <h3>{testCase.title}</h3>
        <p>{testCase.module} · {testCase.type}</p>
      </div>

      <section className="inspector-section">
        <div className="section-label">前置条件 <span>{testCase.preconditions.length}</span></div>
        <ol className="compact-list">
          {testCase.preconditions.map((item) => <li key={item}>{item}</li>)}
        </ol>
      </section>

      <section className="inspector-section">
        <div className="section-label">执行步骤与校验点 <span>{testCase.steps.length}</span></div>
        <div className="step-list">
          {testCase.steps.map((step, index) => (
            <div className="step-card" key={step.id}>
              <span className="step-card__index">{index + 1}</span>
              <div><p>{step.action}</p><small><Check size={12} />{step.expected}</small></div>
            </div>
          ))}
        </div>
      </section>

      <section className="ai-rewrite">
        <div className="ai-rewrite__title"><Sparkles size={15} /><strong>AI 改写</strong><span>不覆盖原文</span></div>
        <div className="rewrite-actions">
          <button className="rewrite-select" type="button" onClick={() => setRewriteType(rewriteOptions[(rewriteOptions.indexOf(rewriteType) + 1) % rewriteOptions.length])}>
            {rewriteType}<ChevronDown size={14} />
          </button>
          <button className="rewrite-run" type="button" onClick={requestRewrite} disabled={mode === "loading"}>
            {mode === "loading" ? "生成中…" : "生成候选"}
          </button>
        </div>

        {mode === "preview" && (
          <motion.div className="rewrite-preview" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
            <span className="rewrite-preview__tag">候选修改 · +2 校验点</span>
            <p><del>不重复扣减库存</del></p>
            <p><ins>库存扣减流水数量保持为 1，库存最终值与首次回调后完全一致。</ins></p>
            <div className="rewrite-preview__buttons">
              <button type="button" onClick={() => setMode("idle")}><X size={14} />放弃</button>
              <button type="button" onClick={() => setMode("accepted")}><Check size={14} />接受修改</button>
            </div>
          </motion.div>
        )}

        {mode === "accepted" && (
          <motion.div className="rewrite-accepted" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            <span><Check size={14} />已保存为候选版本 v3</span>
            <button type="button" onClick={() => setMode("idle")}><RotateCcw size={13} />撤回</button>
          </motion.div>
        )}
      </section>

      <footer className="inspector__footer">
        <span>来源：{testCase.source}</span>
        <button type="button" onClick={onRequestReview}>提交评审</button>
      </footer>
    </aside>
  );
}
