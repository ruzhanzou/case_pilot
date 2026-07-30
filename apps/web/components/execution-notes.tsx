"use client";

import { LoaderCircle, Save } from "lucide-react";
import type { RefObject } from "react";

type ExecutionNotesProps = {
  actualResult: string;
  defectRef: string;
  dirty: boolean;
  saving: boolean;
  readOnly?: boolean;
  readOnlyLabel?: string;
  actualResultRef: RefObject<HTMLTextAreaElement | null>;
  onActualResultChange: (value: string) => void;
  onDefectRefChange: (value: string) => void;
  onSave: () => Promise<void>;
};

export function ExecutionNotes({
  actualResult,
  defectRef,
  dirty,
  saving,
  readOnly = false,
  readOnlyLabel = "批次已结束",
  actualResultRef,
  onActualResultChange,
  onDefectRefChange,
  onSave,
}: ExecutionNotesProps) {
  return (
    <section className="execution-notes">
      <h3>执行记录</h3>
      <label>
        实际结果
        <textarea
          ref={actualResultRef}
          rows={3}
          value={actualResult}
          disabled={readOnly}
          onChange={(event) => onActualResultChange(event.target.value)}
          placeholder="记录与预期结果的差异、环境信息或补充说明"
        />
      </label>
      <label>
        缺陷编号或链接
        <input
          value={defectRef}
          disabled={readOnly}
          onChange={(event) => onDefectRefChange(event.target.value)}
          placeholder="例如 BUG-1024（可选）"
        />
      </label>
      <button
        className="management-button management-button--primary"
        type="button"
        disabled={saving || readOnly || !dirty}
        onClick={() => void onSave()}
      >
        {saving ? (
          <LoaderCircle className="auth-spinner" size={16} />
        ) : (
          <Save size={16} />
        )}
        {readOnly ? readOnlyLabel : dirty ? "保存执行记录" : "记录已保存"}
      </button>
    </section>
  );
}
