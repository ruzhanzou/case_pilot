import type { ExecutionRecordDto, ExecutionStatusApi } from "./casepilot-api";

export type ExecutionRecordDraft = {
  recordId: string;
  baseUpdatedAt: string;
  status: ExecutionStatusApi;
  actualResult: string;
  defectRef: string;
};

export function draftFromRecord(record: ExecutionRecordDto): ExecutionRecordDraft {
  return {
    recordId: record.id,
    baseUpdatedAt: record.updated_at,
    status: record.status,
    actualResult: record.actual_result,
    defectRef: record.defect_ref,
  };
}

export function executionRecordUpdate(
  record: ExecutionRecordDto,
  patch: Partial<Pick<ExecutionRecordDto, "status" | "completed_step_ids" | "actual_result" | "defect_ref">>,
  draft: ExecutionRecordDraft | null,
) {
  return {
    status: patch.status ?? record.status,
    completed_step_ids: patch.completed_step_ids ?? record.completed_step_ids,
    actual_result: patch.actual_result ?? record.actual_result,
    defect_ref: patch.defect_ref ?? record.defect_ref,
    base_updated_at: draft?.recordId === record.id ? draft.baseUpdatedAt : record.updated_at,
  };
}
