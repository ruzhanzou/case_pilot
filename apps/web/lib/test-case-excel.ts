import type { TestCaseInput } from "@/lib/casepilot-api";

export const MAX_EXCEL_IMPORT_ROWS = 100;

const REQUIRED_COLUMNS = [
  "Test_Case_Name",
  "Test Procedure",
  "Test Validation",
] as const;

const COLUMN_KEYS = {
  testcasename: "Test_Case_Name",
  testsetup: "Test Setup",
  testprocedure: "Test Procedure",
  testvalidation: "Test Validation",
  level: "Level",
} as const;

type CanonicalColumn = (typeof COLUMN_KEYS)[keyof typeof COLUMN_KEYS];

export type ExcelCaseImportPreview = {
  fileName: string;
  sheetName: string;
  totalRows: number;
  cases: TestCaseInput[];
  errors: string[];
};

function normalizeHeader(value: unknown) {
  return String(value ?? "")
    .replace(/^\uFEFF/, "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]/g, "");
}

function textValue(value: unknown) {
  return String(value ?? "").trim();
}

function splitStructuredLines(value: string) {
  return value
    .split(/\r?\n+/)
    .map((item) =>
      item
        .trim()
        .replace(/^(?:\d+[.)、]|[-*•])\s*/, "")
        .trim(),
    )
    .filter(Boolean);
}

function parsePriority(value: string): TestCaseInput["priority"] | null {
  if (!value) return "P1";
  const normalized = value.toLowerCase().replace(/[\s_-]/g, "");
  if (["p0", "0", "l0", "level0", "critical", "highest", "high", "紧急", "最高", "高", "严重"].includes(normalized)) {
    return "P0";
  }
  if (["p1", "1", "l1", "level1", "medium", "normal", "中", "普通"].includes(normalized)) {
    return "P1";
  }
  if (["p2", "2", "l2", "level2", "low", "低"].includes(normalized)) {
    return "P2";
  }
  return null;
}

function buildSteps(procedure: string, validation: string) {
  const actions = splitStructuredLines(procedure);
  const expectedResults = splitStructuredLines(validation);
  if (
    actions.length > 1 &&
    actions.length === expectedResults.length
  ) {
    return actions.map((action, index) => ({
      action,
      expected: expectedResults[index],
    }));
  }
  return [{ action: procedure, expected: validation }];
}

export async function parseTestCaseExcel(
  file: File,
): Promise<ExcelCaseImportPreview> {
  const XLSX = await import("xlsx");
  const workbook = XLSX.read(await file.arrayBuffer(), { type: "array" });
  const sheetName = workbook.SheetNames[0];
  if (!sheetName) {
    return {
      fileName: file.name,
      sheetName: "",
      totalRows: 0,
      cases: [],
      errors: ["工作簿中没有可读取的工作表"],
    };
  }

  const rows = XLSX.utils.sheet_to_json<unknown[]>(workbook.Sheets[sheetName], {
    header: 1,
    defval: "",
    raw: false,
    blankrows: false,
  });
  const headerRow = rows[0] ?? [];
  const columnIndexes = new Map<CanonicalColumn, number>();
  headerRow.forEach((value, index) => {
    const canonical = COLUMN_KEYS[normalizeHeader(value) as keyof typeof COLUMN_KEYS];
    if (canonical && !columnIndexes.has(canonical)) {
      columnIndexes.set(canonical, index);
    }
  });

  const missingColumns = REQUIRED_COLUMNS.filter(
    (column) => !columnIndexes.has(column),
  );
  if (missingColumns.length) {
    return {
      fileName: file.name,
      sheetName,
      totalRows: Math.max(rows.length - 1, 0),
      cases: [],
      errors: [`缺少必填列：${missingColumns.join("、")}`],
    };
  }

  const dataRows = rows
    .slice(1)
    .map((row, index) => ({ row, excelRow: index + 2 }))
    .filter(({ row }) => row.some((value) => textValue(value)));
  const errors: string[] = [];
  const cases: TestCaseInput[] = [];
  if (!dataRows.length) errors.push("工作表中没有可导入的数据行");
  if (dataRows.length > MAX_EXCEL_IMPORT_ROWS) {
    errors.push(`单次最多导入 ${MAX_EXCEL_IMPORT_ROWS} 条用例，当前有 ${dataRows.length} 条`);
  }

  dataRows.slice(0, MAX_EXCEL_IMPORT_ROWS).forEach(({ row, excelRow }) => {
    const get = (column: CanonicalColumn) =>
      textValue(row[columnIndexes.get(column) ?? -1]);
    const title = get("Test_Case_Name");
    const procedure = get("Test Procedure");
    const validation = get("Test Validation");
    const setup = get("Test Setup");
    const level = get("Level");
    const missingValues = [
      !title && "Test_Case_Name",
      !procedure && "Test Procedure",
      !validation && "Test Validation",
    ].filter(Boolean);
    if (missingValues.length) {
      errors.push(`第 ${excelRow} 行缺少：${missingValues.join("、")}`);
      return;
    }
    if (title.length > 300) {
      errors.push(`第 ${excelRow} 行 Test_Case_Name 超过 300 个字符`);
      return;
    }
    if (procedure.length > 4000 || validation.length > 4000) {
      errors.push(`第 ${excelRow} 行步骤或校验内容超过 4000 个字符`);
      return;
    }
    const priority = parsePriority(level);
    if (!priority) {
      errors.push(`第 ${excelRow} 行 Level 无法识别：${level}`);
      return;
    }
    const preconditions = splitStructuredLines(setup);
    if (preconditions.length > 50) {
      errors.push(`第 ${excelRow} 行 Test Setup 超过 50 项`);
      return;
    }
    const steps = buildSteps(procedure, validation);
    if (steps.length > 100) {
      errors.push(`第 ${excelRow} 行步骤超过 100 项`);
      return;
    }
    cases.push({
      title,
      module: "",
      priority,
      case_type: "功能",
      tags: [],
      preconditions,
      steps,
      source: `Excel 导入：${file.name}`.slice(0, 500),
    });
  });

  return {
    fileName: file.name,
    sheetName,
    totalRows: dataRows.length,
    cases,
    errors,
  };
}
