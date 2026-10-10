"use client";

import { useState } from "react";
import { Sparkles, X } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { useI18n } from "@/lib/i18n";

export function CasePolishDialog({ title, hasUnsavedChanges, onClose, onGenerate }: {
  title: string;
  hasUnsavedChanges: boolean;
  onClose: () => void;
  onGenerate: (instruction: string) => Promise<void>;
}) {
  const { pick } = useI18n();
  const options = [
    { id: "title", label: pick("Clarify title", "标题规范化"), detail: pick("Express the scenario and test objective concisely.", "突出测试场景与验证目标，精简重复表述。") },
    { id: "preconditions", label: pick("Organize preconditions", "整理前置条件"), detail: pick("Separate account, data and environment prerequisites.", "分条整理账号、数据和环境等准备条件。") },
    { id: "steps", label: pick("Split procedure steps", "拆分操作步骤"), detail: pick("Keep one clear, executable action per step.", "每步一个动作，操作明确、顺序清晰。") },
    { id: "checks", label: pick("Make checkpoints verifiable", "明确校验点"), detail: pick("Use observable results and remove vague wording.", "明确可观察的预期结果，消除模糊描述。") },
  ];
  const [selected, setSelected] = useState(["title", "preconditions", "steps", "checks"]);
  const [requirement, setRequirement] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  return <Dialog open onOpenChange={open => { if (!open && !submitting) onClose(); }}>
    <DialogContent className="case-polish-dialog" showCloseButton={false}>
      <div className="case-polish-heading">
        <DialogTitle><Sparkles size={20} /> {pick("AI polish", "AI 润色")}</DialogTitle>
        <button type="button" disabled={submitting} aria-label={pick("Close AI polish", "关闭 AI 润色")} onClick={onClose}><X size={18} /></button>
      </div>
      <DialogDescription>{pick("Choose improvements for this case. Review the proposed changes in the workstation before accepting them.", "选择当前用例的优化方向，生成后在工作区审阅建议，采纳后才会生效。")}</DialogDescription>
      <p className="case-polish-target">{title}</p>
      <form onSubmit={async event => {
        event.preventDefault();
        if (submitting || (!selected.length && !requirement.trim())) return;
        setSubmitting(true);
        setError("");
        try {
          await onGenerate([
            pick("Polish only the selected test case and prepare a modification proposal for review.", "仅润色当前选中的测试用例，生成修改建议供用户审阅。"),
            pick("Preserve the original scenario, business rules, module and priority. Do not invent requirements, test data or expected results; flag missing information for confirmation.", "保留原有测试场景、业务规则、模块和优先级。不编造需求、测试数据或预期结果，缺失信息标记为待确认。"),
            ...options.filter(option => selected.includes(option.id)).map(option => `${option.label}：${option.detail}`),
            ...(requirement.trim() ? [pick("Additional requirements: ", "补充要求：") + requirement.trim()] : []),
          ].join("\n"));
        } catch (caught) {
          setError(caught instanceof Error ? caught.message : pick("Could not generate suggestions. Please retry.", "生成建议失败，请重试。"));
        } finally { setSubmitting(false); }
      }}>
        <fieldset disabled={submitting}>
          <legend>{pick("Structure improvements", "基础结构优化")}</legend>
          <div className="case-polish-options">{options.map(option => <label key={option.id}>
            <input type="checkbox" checked={selected.includes(option.id)} onChange={event => setSelected(current => event.target.checked ? [...current, option.id] : current.filter(id => id !== option.id))} />
            <span><strong>{option.label}</strong><small>{option.detail}</small></span>
          </label>)}</div>
          <label className="case-polish-requirement">{pick("Additional requirements (optional)", "补充优化要求（可选）")}
            <textarea rows={3} maxLength={3000} value={requirement} onChange={event => setRequirement(event.target.value)} placeholder={pick("For example: use concise language and distinguish actions from checkpoints.", "例如：表述更简洁，区分操作步骤与校验点。")}/>
          </label>
        </fieldset>
        {hasUnsavedChanges && <p className="case-polish-note">{pick("Your current candidate edits will be saved before generating suggestions.", "将先保存当前候选用例的编辑，再基于最新内容生成建议。")}</p>}
        {error && <p role="alert" className="case-polish-error">{error}</p>}
        <footer><button type="button" disabled={submitting} onClick={onClose}>{pick("Cancel", "取消")}</button>
          <button className="case-polish-submit" type="submit" disabled={submitting || (!selected.length && !requirement.trim())}><Sparkles size={16}/>{submitting ? pick("Preparing…", "正在准备…") : hasUnsavedChanges ? pick("Save and generate suggestions", "保存并生成建议") : pick("Generate suggestions", "生成优化建议")}</button>
        </footer>
      </form>
    </DialogContent>
  </Dialog>;
}
