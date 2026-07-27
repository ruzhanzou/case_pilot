"use client";

import type { ExecutionRecordDto } from "@/lib/casepilot-api";
import { LoaderCircle, Save } from "lucide-react";
import { useState } from "react";

type ExecutionNotesProps = {
  record: ExecutionRecordDto;
  saving: boolean;
  readOnly?: boolean;
  onSave: (
    patch: Pick<ExecutionRecordDto, "actual_result" | "defect_ref">,
  ) => Promise<void>;
};

export function ExecutionNotes({
  record,
  saving,
  readOnly = false,
  onSave,
}: ExecutionNotesProps) {
  const [actualResult, setActualResult] = useState(record.actual_result);
  const [defectRef, setDefectRef] = useState(record.defect_ref);

  return (
    <section className="execution-notes">
      <h3>执行记录</h3>
      <label>
        实际结果
        <textarea
          rows={3}
          value={actualResult}
          disabled={readOnly}
          onChange={(event) => setActualResult(event.target.value)}
          placeholder="记录与预期结果的差异、环境信息或补充说明"
        />
      </label>
      <label>
        缺陷编号或链接
        <input
          value={defectRef}
          disabled={readOnly}
          onChange={(event) => setDefectRef(event.target.value)}
          placeholder="例如 BUG-1024（可选）"
        />
      </label>
      <button
        className="management-button management-button--primary"
        type="button"
        disabled={saving || readOnly}
        onClick={() =>
          void onSave({
            actual_result: actualResult,
            defect_ref: defectRef,
          })
        }
      >
        {saving ? (
          <LoaderCircle className="auth-spinner" size={16} />
        ) : (
          <Save size={16} />
        )}
        {readOnly ? "批次已结束" : "保存执行记录"}
      </button>
    </section>
  );
}
