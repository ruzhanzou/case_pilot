"use client";

import type { TestCaseDto, TestCaseInput } from "@/lib/casepilot-api";
import { LoaderCircle, Plus, Trash2, X } from "lucide-react";
import { useRef, useState } from "react";

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
      setError("请填写用例名称");
      return;
    }
    if (!normalizedSteps.length) {
      setError("至少需要一个包含操作和预期结果的执行步骤");
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
    });
  };

  return (
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
              {testCase ? `修订版本 V${testCase.revision_number}` : "新建用例"}
            </span>
            <h2 id="case-editor-title">
              {testCase ? "编辑结构化测试用例" : "创建结构化测试用例"}
            </h2>
          </div>
          <button
            className="management-icon-button"
            type="button"
            onClick={onClose}
            aria-label="关闭编辑窗口"
          >
            <X size={19} />
          </button>
        </header>

        <form className="case-editor__form" onSubmit={submit}>
          <div className="case-editor__grid">
            <label>
              用例编号
              <input
                value={caseKey}
                onChange={(event) => setCaseKey(event.target.value)}
                placeholder="自动生成或输入 AUTH-001"
                disabled={Boolean(testCase)}
              />
            </label>
            <label className="case-editor__wide">
              用例名称
              <input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="描述明确、可验证的测试目标"
                autoFocus
              />
            </label>
            <label>
              所属模块
              <input
                value={module}
                onChange={(event) => setModule(event.target.value)}
                placeholder="例如：账号与认证"
              />
            </label>
            <label>
              优先级
              <select
                value={priority}
                onChange={(event) =>
                  setPriority(event.target.value as TestCaseInput["priority"])
                }
              >
                <option value="P0">P0 · 阻断主流程</option>
                <option value="P1">P1 · 重要场景</option>
                <option value="P2">P2 · 一般场景</option>
              </select>
            </label>
            <label>
              用例类型
              <input
                value={caseType}
                onChange={(event) => setCaseType(event.target.value)}
                placeholder="功能 / 异常 / 边界"
              />
            </label>
            <label>
              标签
              <input
                value={tags}
                onChange={(event) => setTags(event.target.value)}
                placeholder="多个标签以逗号分隔"
              />
            </label>
            <label className="case-editor__wide">
              来源
              <input
                value={source}
                onChange={(event) => setSource(event.target.value)}
                placeholder="需求文档、人工创建或导入文件"
              />
            </label>
          </div>

          <fieldset className="case-editor__section">
            <div className="case-editor__section-title">
              <legend>前置条件</legend>
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
                <Plus size={15} /> 添加条件
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
                    placeholder="执行前必须满足的环境、数据或账号条件"
                  />
                  <button
                    type="button"
                    aria-label={`删除第 ${index + 1} 条前置条件`}
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
              <legend>执行步骤与预期结果</legend>
              <button
                type="button"
                onClick={() =>
                  setSteps((items) => [
                    ...items,
                    emptyStep(`new-${nextStepId.current++}`),
                  ])
                }
              >
                <Plus size={15} /> 添加步骤
              </button>
            </div>
            <div className="case-editor__steps">
              {steps.map((step, index) => (
                <div className="case-editor__step" key={step.clientId}>
                  <span className="case-editor__step-index">{index + 1}</span>
                  <label>
                    执行操作
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
                      placeholder="QA 需要完成的具体操作"
                      rows={2}
                    />
                  </label>
                  <label>
                    预期结果／校验点
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
                      placeholder="可以观察和判断的明确结果"
                      rows={2}
                    />
                  </label>
                  <button
                    type="button"
                    aria-label={`删除第 ${index + 1} 个执行步骤`}
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
            <button type="button" className="management-button" onClick={onClose}>
              取消
            </button>
            <button
              type="submit"
              className="management-button management-button--primary"
              disabled={saving}
            >
              {saving && <LoaderCircle className="auth-spinner" size={16} />}
              {testCase ? "保存为新版本" : "创建用例"}
            </button>
          </footer>
        </form>
      </section>
    </div>
  );
}
