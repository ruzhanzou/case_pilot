"use client";

import { FileUp, CheckCircle2, CircleAlert, LoaderCircle } from "lucide-react";
import { useI18n } from "@/lib/i18n";

export function ConversationAttachments({ metadata, pending = false }: { metadata: Record<string, unknown>; pending?: boolean }) {
  const { pick } = useI18n();
  const files = Array.isArray(metadata.attachments) ? metadata.attachments : [];
  if (!files.length) return null;
  return <div className="principle-attachments" aria-label={pending ? pick("Pending attachments", "待发送附件") : pick("Conversation attachments", "对话附件")}>
    {files.map((file: { id: string; name: string; size: number; status: string }) => (
      <div key={file.id} className="principle-attachment" data-status={file.status}>
        <FileUp size={20} aria-hidden="true" />
        <div className="principle-attachment__body">
          <strong>{file.name}</strong>
          <span>{Math.max(1, Math.ceil(file.size / 1024))} KB · {file.status === "ready"
            ? pick("Ready", "已就绪") : file.status === "failed"
              ? pick("Processing failed. Please upload again.", "解析失败，请重新上传")
              : pick("Uploaded · Preparing…", "已上传 · 正在解析…")}</span>
        </div>
        {file.status === "ready" ? <CheckCircle2 size={17} aria-hidden="true" />
          : file.status === "failed" ? <CircleAlert size={17} aria-hidden="true" />
            : <LoaderCircle size={17} className="auth-spinner" aria-hidden="true" />}
      </div>
    ))}
  </div>;
}
