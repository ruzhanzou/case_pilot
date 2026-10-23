"use client";

import { FileUp, CheckCircle2, CircleAlert, LoaderCircle, X } from "lucide-react";
import { publicErrorMessage } from "@/lib/casepilot-api";
import { useI18n } from "@/lib/i18n";

type ConversationAttachment = {
  id: string;
  name: string;
  size: number;
  status: string;
  error_code?: string | null;
};

export function activeConversationAttachments(conversation: {
  context: Record<string, unknown>;
  messages: Array<{ metadata: Record<string, unknown> }>;
} | null): ConversationAttachment[] {
  if (!conversation) return [];
  const activeIds = new Set(
    (Array.isArray(conversation.context.document_ids)
      ? conversation.context.document_ids : []).map(String),
  );
  const pendingIds = new Set(
    (Array.isArray(conversation.context.pending_attachments)
      ? conversation.context.pending_attachments : [])
      .map((file: { id?: unknown }) => String(file.id ?? "")),
  );
  const active = new Map<string, ConversationAttachment>();
  for (const message of conversation.messages) {
    const files = Array.isArray(message.metadata.attachments)
      ? message.metadata.attachments as ConversationAttachment[] : [];
    for (const file of files) {
      if (activeIds.has(file.id) && !pendingIds.has(file.id)) active.set(file.id, file);
    }
  }
  return [...active.values()];
}

export function ConversationAttachments({ metadata, pending = false, active = false, onRemove, disabled = false }: { metadata: Record<string, unknown>; pending?: boolean; active?: boolean; onRemove?: (id: string) => void; disabled?: boolean }) {
  const { pick } = useI18n();
  const files = Array.isArray(metadata.attachments) ? metadata.attachments : [];
  if (!files.length) return null;
  return <div className="principle-attachments" aria-label={pending ? pick("Pending attachments", "待发送附件") : active ? pick("Active reference attachments", "当前引用附件") : pick("Conversation attachments", "对话附件")}>
    {active && <p className="principle-attachments__hint">{pick("These files remain available to later messages. Remove a file to stop using it as evidence.", "后续消息仍会使用这些附件作为依据；移除后将停止引用。")}</p>}
    {files.map((file: { id: string; name: string; size: number; status: string; error_code?: string | null }) => (
      <div key={file.id} className="principle-attachment" data-status={file.status}>
        <FileUp size={20} aria-hidden="true" />
        <div className="principle-attachment__body">
          <strong>{file.name}</strong>
          <span>{Math.max(1, Math.ceil(file.size / 1024))} KB · {file.status === "ready"
            ? pick("Ready", "已就绪") : file.status === "expired"
              ? pick("Expired · upload again to use in new requests", "已过期，新任务使用前请重新上传") : file.status === "failed"
              ? file.error_code ? publicErrorMessage(file.error_code) : pick("Processing failed. Please upload again.", "解析失败，请重新上传")
              : /\.xlsx?$/i.test(file.name) ? pick("Organizing Excel cases…", "正在识别整理 Excel 用例…") : pick("Uploaded · Preparing…", "已上传 · 正在解析…")}</span>
        </div>
        {file.status === "ready" ? <CheckCircle2 size={17} aria-hidden="true" />
          : ["failed", "expired"].includes(file.status) ? <CircleAlert size={17} aria-hidden="true" />
            : <LoaderCircle size={17} className="auth-spinner" aria-hidden="true" />}
        {onRemove && <button className="principle-attachment__remove" type="button" disabled={disabled} onClick={() => onRemove(file.id)} aria-label={pick(`Remove ${file.name}`, `移除 ${file.name}`)}><X size={16} aria-hidden="true" /></button>}
      </div>
    ))}
  </div>;
}
