"use client";

import type { TestCaseDto, TestCaseInput } from "@/lib/casepilot-api";
import { useI18n } from "@/lib/i18n";
import { LoaderCircle, Plus, Trash2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

type CaseEditorDialogProps = {
  testCase: TestCaseDto | null;
  initialModule?: string;
  saving: boolean;
  onClose: () => void;
  onSave: (input: TestCaseInput) => Promise<void>;
};

type EditableStep = {
  clientId: string;
  id?: string;
  action: string;
  expected: string;
};

type EditablePrecondition = {
  id: string;
  value: string;
};

const emptyStep = (clientId: string): EditableStep => ({
  clientId,
  action: "",
  expected: "",
});

export function CaseEditorDialog({
  testCase,
  initialModule,
  saving,
  onClose,
  onSave,
}: CaseEditorDialogProps) {
  const { pick } = useI18n();
  const [caseKey, setCaseKey] = useState(testCase?.case_key ?? "");
  const [title, setTitle] = useState(testCase?.title ?? "");
  const [module, setModule] = useState(testCase?.module ?? initialModule ?? "");
  const [priority, setPriority] = useState<TestCaseInput["priority"]>(
    testCase?.priority ?? "P1",
  );
  const [caseType, setCaseType] = useState(testCase?.case_type ?? "功能");
  const [tags, setTags] = useState(testCase?.tags.join("，") ?? "");
  const [source, setSource] = useState(testCase?.source ?? "人工创建");
  const nextPreconditionId = useRef(0);
  const nextStepId = useRef(0);
  const [preconditions, setPreconditions] = useState<EditablePrecondition[]>(() =>
    testCase?.preconditions.length
      ? testCase.preconditions.map((value, index) => ({
          id: `existing-${index}`,
          value,
        }))
      : [{ id: "existing-0", value: "" }],
  );
  const [steps, setSteps] = useState<EditableStep[]>(() =>
    testCase?.steps.length
      ? testCase.steps.map((step, index) => ({
          ...step,
          clientId: `existing-${step.id || index}`,
        }))
      : [emptyStep("existing-0")],
  );
  const [error, setError] = useState("");
  const initialSnapshot = JSON.stringify({
    caseKey: testCase?.case_key ?? "",
    title: testCase?.title ?? "",
    module: testCase?.module ?? initialModule ?? "",
    priority: testCase?.priority ?? "P1",
    caseType: testCase?.case_type ?? "功能",
    tags: testCase?.tags.join("，") ?? "",
    source: testCase?.source ?? "人工创建",
    preconditions: testCase?.preconditions.length
      ? testCase.preconditions
      : [""],
    steps: testCase?.steps.length
      ? testCase.steps.map(({ action, expected }) => ({ action, expected }))
      : [{ action: "", expected: "" }],
  });
  const currentSnapshot = JSON.stringify({
    caseKey,
    title,
    module,
    priority,
    caseType,
    tags,
    source,
    preconditions: preconditions.map((item) => item.value),
    steps: steps.map(({ action, expected }) => ({ action, expected })),
  });
  const isDirty = initialSnapshot !== currentSnapshot;

  useEffect(() => {
    if (!isDirty) return;
    const warnBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", warnBeforeUnload);
    return () => window.removeEventListener("beforeunload", warnBeforeUnload);
  }, [isDirty]);

  const requestClose = () => {
    if (
      isDirty &&
      !window.confirm(
        pick(
          "This test case has unsaved changes. Discard them?",
          "当前用例修改尚未保存，确认放弃这些修改吗？",
        ),
      )
    ) {
      return;
    }
    onClose();
  };

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    const normalizedPreconditions = preconditions
      .map((item) => item.value.trim())
      .filter(Boolean);
    const normalizedSteps = steps
      .map((step) => ({
        id: step.id,
        action: step.action.trim(),
        expected: step.expected.trim(),
      }))
      .filter((step) => step.action && step.expected);
    if (!title.trim()) {
      setError(pick("Enter a test case name", "请填写用例名称"));
      return;
    }
    if (!normalizedSteps.length) {
      setError(
        pick(
          "Add at least one step with an action and expected result",
          "至少需要一个包含操作和预期结果的执行步骤",
        ),
      );
      return;
    }
    await onSave({
      case_key: caseKey.trim() || undefined,
      title: title.trim(),
      module: module.trim(),
      priority,
      case_type: caseType.trim() || "功能",
      tags: tags
        .split(/[,，]/)
        .map((tag) => tag.trim())
        .filter(Boolean),
      preconditions: normalizedPreconditions,
      steps: normalizedSteps,
      source: source.trim() || "人工创建",
      source_refs: testCase?.source_refs,
    });
  };

  const dialog = (
    <div className="management-modal-backdrop" role="presentation">
      <section
        className="management-modal case-editor"
        role="dialog"
        aria-modal="true"
        aria-labelledby="case-editor-title"
      >
        <header className="management-modal__header">
          <div>
            <span className="management-kicker">
              {testCase
                ? pick(`Revision V${testCase.revision_number}`, `修订版本 V${testCase.revision_number}`)
                : pick("New test case", "新建用例")}
            </span>
            <h2 id="case-editor-title">
              {testCase
                ? pick("Edit structured test case", "编辑结构化测试用例")
                : pick("Create structured test case", "创建结构化测试用例")}
            </h2>
          </div>
          <button
            className="management-icon-button"
            type="button"
            onClick={requestClose}
            aria-label={pick("Close editor", "关闭编辑窗口")}
          >
            <X size={19} />
          </button>
        </header>

        <form className="case-editor__form" onSubmit={submit}>
          <div className="case-editor__grid">
            <label>
              {pick("Case ID", "用例编号")}
              <input
                value={caseKey}
                onChange={(event) => setCaseKey(event.target.value)}
                placeholder={pick("Auto-generated or enter AUTH-001", "自动生成或输入 AUTH-001")}
                disabled={Boolean(testCase)}
              />
            </label>
            <label className="case-editor__wide">
              {pick("Test case name", "用例名称")}
              <input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder={pick("Describe a clear, verifiable test objective", "描述明确、可验证的测试目标")}
                autoFocus
              />
            </label>
            <label>
              {pick("Module", "所属模块")}
              <input
                value={module}
                onChange={(event) => setModule(event.target.value)}
                placeholder={pick("e.g. Accounts and authentication", "例如：账号与认证")}
              />
            </label>
            <label>
              {pick("Priority", "优先级")}
              <select
                value={priority}
                onChange={(event) =>
                  setPriority(event.target.value as TestCaseInput["priority"])
                }
              >
                <option value="P0">{pick("P0 · Blocks critical flow", "P0 · 阻断主流程")}</option>
                <option value="P1">{pick("P1 · Important scenario", "P1 · 重要场景")}</option>
                <option value="P2">{pick("P2 · General scenario", "P2 · 一般场景")}</option>
              </select>
            </label>
            <label>
              {pick("Case type", "用例类型")}
              <input
                value={caseType}
                onChange={(event) => setCaseType(event.target.value)}
                placeholder={pick("Functional / Negative / Boundary", "功能 / 异常 / 边界")}
              />
            </label>
            <label>
              {pick("Tags", "标签")}
              <input
                value={tags}
                onChange={(event) => setTags(event.target.value)}
                placeholder={pick("Separate tags with commas", "多个标签以逗号分隔")}
              />
            </label>
            <label className="case-editor__wide">
              {pick("Source", "来源")}
              <input
                value={source}
                onChange={(event) => setSource(event.target.value)}
                placeholder={pick("Requirement, manual entry, or imported file", "需求文档、人工创建或导入文件")}
              />
            </label>
          </div>

          <fieldset className="case-editor__section">
            <div className="case-editor__section-title">
              <legend>{pick("Preconditions", "前置条件")}</legend>
              <button
                type="button"
                onClick={() =>
                  setPreconditions((items) => [
                    ...items,
                    {
                      id: `new-${nextPreconditionId.current++}`,
                      value: "",
                    },
                  ])
                }
              >
                <Plus size={15} /> {pick("Add condition", "添加条件")}
              </button>
            </div>
            <div className="case-editor__rows">
              {preconditions.map((item, index) => (
                <div className="case-editor__row" key={item.id}>
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  <input
                    value={item.value}
                    onChange={(event) =>
                      setPreconditions((items) =>
                        items.map((current, itemIndex) =>
                          itemIndex === index
                            ? { ...current, value: event.target.value }
                            : current,
                        ),
                      )
                    }
                    placeholder={pick("Environment, data, or account requirements", "执行前必须满足的环境、数据或账号条件")}
                  />
                  <button
                    type="button"
                    aria-label={pick(`Delete precondition ${index + 1}`, `删除第 ${index + 1} 条前置条件`)}
                    onClick={() =>
                      setPreconditions((items) =>
                        items.length === 1
                          ? [{ ...items[0], value: "" }]
                          : items.filter((current) => current.id !== item.id),
                      )
                    }
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
              ))}
            </div>
          </fieldset>

          <fieldset className="case-editor__section">
            <div className="case-editor__section-title">
              <legend>{pick("Steps and expected results", "执行步骤与预期结果")}</legend>
              <button
                type="button"
                onClick={() =>
                  setSteps((items) => [
                    ...items,
                    emptyStep(`new-${nextStepId.current++}`),
                  ])
                }
              >
                <Plus size={15} /> {pick("Add step", "添加步骤")}
              </button>
            </div>
            <div className="case-editor__steps">
              {steps.map((step, index) => (
                <div className="case-editor__step" key={step.clientId}>
                  <span className="case-editor__step-index">{index + 1}</span>
                  <label>
                    {pick("Action", "执行操作")}
                    <textarea
                      value={step.action}
                      onChange={(event) =>
                        setSteps((items) =>
                          items.map((current, itemIndex) =>
                            itemIndex === index
                              ? { ...current, action: event.target.value }
                              : current,
                          ),
                        )
                      }
                      placeholder={pick("The exact action for QA to perform", "QA 需要完成的具体操作")}
                      rows={2}
                    />
                  </label>
                  <label>
                    {pick("Expected result / Checkpoint", "预期结果／校验点")}
                    <textarea
                      value={step.expected}
                      onChange={(event) =>
                        setSteps((items) =>
                          items.map((current, itemIndex) =>
                            itemIndex === index
                              ? { ...current, expected: event.target.value }
                              : current,
                          ),
                        )
                      }
                      placeholder={pick("A clear, observable result", "可以观察和判断的明确结果")}
                      rows={2}
                    />
                  </label>
                  <button
                    type="button"
                    aria-label={pick(`Delete step ${index + 1}`, `删除第 ${index + 1} 个执行步骤`)}
                    onClick={() =>
                      setSteps((items) =>
                        items.length === 1
                          ? [emptyStep(items[0].clientId)]
                          : items.filter(
                              (current) => current.clientId !== step.clientId,
                            ),
                      )
                    }
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              ))}
            </div>
          </fieldset>

          {error && <div className="management-inline-error">{error}</div>}

          <footer className="management-modal__footer">
            <button type="button" className="management-button" onClick={requestClose}>
              {pick("Cancel", "取消")}
            </button>
            <button
              type="submit"
              className="management-button management-button--primary"
              disabled={saving}
            >
              {saving && <LoaderCircle className="auth-spinner" size={16} />}
              {testCase
                ? pick("Save as new revision", "保存为新版本")
                : pick("Create test case", "创建用例")}
            </button>
          </footer>
        </form>
      </section>
    </div>
  );

  if (typeof document === "undefined") return null;
  const fullscreenTarget =
    document.fullscreenElement ??
    document.querySelector<HTMLElement>(".case-mind-map.is-fullscreen");
  return createPortal(dialog, fullscreenTarget ?? document.body);
}
