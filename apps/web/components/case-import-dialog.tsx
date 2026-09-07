"use client";

import type { TestCaseInput } from "@/lib/casepilot-api";
import {
  MAX_EXCEL_IMPORT_ROWS,
  parseTestCaseExcel,
  type ExcelCaseImportPreview,
} from "@/lib/test-case-excel";
import {
  AlertCircle,
  CheckCircle2,
  FileSpreadsheet,
  LoaderCircle,
  Upload,
  X,
} from "lucide-react";
import { useRef, useState } from "react";

type CaseImportDialogProps = {
  collectionName: string;
  saving: boolean;
  onClose: () => void;
  onImport: (cases: TestCaseInput[]) => Promise<unknown>;
};

const EXCEL_ACCEPT =
  ".xlsx,.xls,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel";

export function CaseImportDialog({
  collectionName,
  saving,
  onClose,
  onImport,
}: CaseImportDialogProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<ExcelCaseImportPreview | null>(null);
  const [parsing, setParsing] = useState(false);
  const [error, setError] = useState("");

  const readFile = async (file?: File) => {
    if (!file) return;
    setParsing(true);
    setError("");
    setPreview(null);
    try {
      if (!/\.xlsx?$/i.test(file.name)) {
        throw new Error("请选择 .xlsx 或 .xls 文件");
      }
      if (file.size > 10 * 1024 * 1024) {
        throw new Error("Excel 文件不能超过 10 MB");
      }
      setPreview(await parseTestCaseExcel(file));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Excel 文件解析失败");
    } finally {
      setParsing(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const canImport = Boolean(
    preview && preview.cases.length && !preview.errors.length && !saving,
  );

  return (
    <div className="management-modal-backdrop" role="presentation">
      <section
        className="management-modal case-import"
        role="dialog"
        aria-modal="true"
        aria-labelledby="case-import-title"
      >
        <header className="management-modal__header">
          <div>
            <span className="management-kicker">{collectionName}</span>
            <h2 id="case-import-title">从 Excel 导入用例</h2>
          </div>
          <button
            type="button"
            className="management-icon-button"
            onClick={onClose}
            disabled={saving}
            aria-label="关闭导入窗口"
          >
            <X size={19} />
          </button>
        </header>

        <div className="case-import__body">
          <button
            type="button"
            className="case-import__dropzone"
            onClick={() => inputRef.current?.click()}
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
              event.preventDefault();
              void readFile(event.dataTransfer.files[0]);
            }}
            disabled={parsing || saving}
          >
            {parsing ? (
              <LoaderCircle className="auth-spinner" size={28} />
            ) : (
              <FileSpreadsheet size={30} />
            )}
            <strong>{parsing ? "正在解析工作簿…" : "选择或拖入 Excel 文件"}</strong>
            <span>支持 .xlsx、.xls，文件不超过 10 MB；读取第一个工作表</span>
          </button>
          <input
            ref={inputRef}
            className="case-import__file-input"
            type="file"
            accept={EXCEL_ACCEPT}
            onChange={(event) => void readFile(event.target.files?.[0])}
          />

          <div className="case-import__columns">
            <strong>列要求</strong>
            <div>
              <span className="is-required">Test_Case_Name 必填</span>
              <span>Test Setup</span>
              <span className="is-required">Test Procedure 必填</span>
              <span className="is-required">Test Validation 必填</span>
              <span>Level</span>
            </div>
            <p>
              Level 支持 P0/P1/P2、0/1/2、High/Medium/Low 或高/中/低；留空按 P1 导入。单次最多 {MAX_EXCEL_IMPORT_ROWS} 条。
            </p>
          </div>

          {error && (
            <div className="case-import__message is-error">
              <AlertCircle size={17} />
              <span>{error}</span>
            </div>
          )}

          {preview && (
            <div className="case-import__preview">
              <div className="case-import__preview-head">
                <div>
                  {preview.errors.length ? (
                    <AlertCircle size={18} />
                  ) : (
                    <CheckCircle2 size={18} />
                  )}
                  <span>
                    <strong>{preview.fileName}</strong>
                    <small>
                      工作表“{preview.sheetName}” · {preview.totalRows} 行 · 可导入 {preview.cases.length} 条
                    </small>
                  </span>
                </div>
                <button type="button" onClick={() => inputRef.current?.click()}>
                  重新选择
                </button>
              </div>

              {!!preview.errors.length && (
                <div className="case-import__errors">
                  {preview.errors.slice(0, 8).map((item) => (
                    <p key={item}>{item}</p>
                  ))}
                  {preview.errors.length > 8 && (
                    <p>另有 {preview.errors.length - 8} 项错误，请修正文件后重新选择。</p>
                  )}
                </div>
              )}

              {!preview.errors.length && (
                <div className="case-import__table-wrap">
                  <table className="case-import__table">
                    <thead>
                      <tr>
                        <th>用例名称</th>
                        <th>Level</th>
                        <th>前置条件</th>
                        <th>步骤</th>
                      </tr>
                    </thead>
                    <tbody>
                      {preview.cases.slice(0, 5).map((testCase, index) => (
                        <tr key={`${testCase.title}-${index}`}>
                          <td>{testCase.title}</td>
                          <td>{testCase.priority}</td>
                          <td>{testCase.preconditions.length || "—"}</td>
                          <td>{testCase.steps.length}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {preview.cases.length > 5 && (
                    <p>仅预览前 5 条，其余 {preview.cases.length - 5} 条将在确认后一起导入。</p>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        <footer className="management-modal__footer">
          <button
            type="button"
            className="management-button"
            onClick={onClose}
            disabled={saving}
          >
            取消
          </button>
          <button
            type="button"
            className="management-button management-button--primary"
            disabled={!canImport}
            onClick={async () => {
              if (!preview) return;
              setError("");
              try {
                await onImport(preview.cases);
              } catch (caught) {
                setError(caught instanceof Error ? caught.message : "用例导入失败");
              }
            }}
          >
            {saving ? (
              <LoaderCircle className="auth-spinner" size={16} />
            ) : (
              <Upload size={16} />
            )}
            导入 {preview?.cases.length || 0} 条用例
          </button>
        </footer>
      </section>
    </div>
  );
}
