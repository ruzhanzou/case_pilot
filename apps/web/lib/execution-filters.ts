import type { ExecutionRecordDto } from "./casepilot-api";

export const executionFilterFields = [
  ["title", "Title", "标题"], ["case_key", "Case ID", "用例编号"],
  ["module", "Module", "模块"], ["priority", "Priority", "优先级"],
  ["status", "Execution status", "执行状态"], ["assignee_name", "Assignee", "执行人"],
  ["tags", "Tags", "标签"], ["case_type", "Case type", "用例类型"],
  ["actual_result", "Actual result", "实际结果"], ["defect_ref", "Defect reference", "缺陷链接"],
] as const;
export type ExecutionFilterField = typeof executionFilterFields[number][0];
export type ExecutionFilterOperator = "contains" | "not_contains" | "equals" | "not_equals";
export type ExecutionFilter = {
  id: number;
  field: ExecutionFilterField;
  operator: ExecutionFilterOperator;
  value: string;
};
export type ExecutionFilterMode = "and" | "or";
const normalize = (value: string) => value.normalize("NFKC").trim().toLocaleLowerCase();

export function matchesExecutionFilters(
  record: ExecutionRecordDto, filters: ExecutionFilter[], mode: ExecutionFilterMode,
): boolean {
  const active = filters.filter((filter) => normalize(filter.value));
  if (!active.length) return true;
  const matches = (filter: ExecutionFilter) => {
    const raw = filter.field === "status" || filter.field === "assignee_name" ||
      filter.field === "actual_result" || filter.field === "defect_ref"
      ? record[filter.field] : record.test_case[filter.field];
    const values = (Array.isArray(raw) ? raw : [raw ?? ""]).map(normalize);
    const query = normalize(filter.value);
    const found = values.some((value) => filter.operator === "equals" || filter.operator === "not_equals"
      ? value === query : value.includes(query));
    return filter.operator === "not_contains" || filter.operator === "not_equals" ? !found : found;
  };
  return mode === "and" ? active.every(matches) : active.some(matches);
}
