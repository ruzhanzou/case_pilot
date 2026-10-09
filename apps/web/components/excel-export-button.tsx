"use client";

import { useRef, useState } from "react";
import { Download, LoaderCircle } from "lucide-react";
import { useI18n } from "@/lib/i18n";

export function ExcelExportButton({ onExport, disabled, title }: {
  onExport: () => Promise<void>;
  disabled?: boolean;
  title: string;
}) {
  const { pick } = useI18n();
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState(false);
  const pending = useRef(false);
  async function handleExport() {
    if (pending.current || disabled) return;
    pending.current = true;
    setExporting(true);
    setError(false);
    try {
      await onExport();
    } catch {
      setError(true);
    } finally {
      pending.current = false;
      setExporting(false);
    }
  }
  return (
    <div>
      <button type="button" className="management-button" disabled={disabled || exporting}
        title={title} aria-busy={exporting} onClick={() => void handleExport()}>
        {exporting ? <LoaderCircle size={16} className="auth-spinner" /> : <Download size={16} />}
        {exporting ? pick("Exporting…", "正在导出…") : pick("Export Excel", "导出 Excel")}
      </button>
      {error && <p role="alert">{pick("Export failed. Please try again.", "导出失败，请重试。")}</p>}
    </div>
  );
}
