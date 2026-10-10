"use client";
import { useState } from "react";
import { useI18n } from "@/lib/i18n";
import { caseContentRows } from "@/lib/case-content";
type Row = { action: string; expected: string };
export function CaseContentFields({ steps, onChange }: { steps: Row[]; onChange: (steps: Row[]) => void }) {
  const { pick } = useI18n();
  const [actions, setActions] = useState(() => steps.map(s => s.action).filter(Boolean).join("\n"));
  const [checks, setChecks] = useState(() => steps.map(s => s.expected).filter(Boolean).join("\n"));
  return <div className="case-content-fields">
    <label>{pick("Procedure (one action per line)", "操作步骤（每行一项）")}<textarea rows={5} value={actions} onChange={event => { setActions(event.target.value); onChange(caseContentRows(event.target.value, checks)); }} /></label>
    <label>{pick("Case checkpoints (one per line)", "用例校验点（每行一项）")}<textarea rows={5} value={checks} onChange={event => { setChecks(event.target.value); onChange(caseContentRows(actions, event.target.value)); }} /></label>
    <small>{pick("Check the overall case outcome. Checkpoints do not need to match actions one-to-one.", "校验整条用例的结果，无需与操作步骤逐条对应。")}</small>
  </div>;
}
