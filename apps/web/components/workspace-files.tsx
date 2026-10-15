"use client";

import { useEffect, useState } from "react";
import { Download, FileText, LoaderCircle } from "lucide-react";
import { type ConversationDto, downloadKnowledgeDocument, previewKnowledgeDocument } from "@/lib/casepilot-api";
import { useI18n } from "@/lib/i18n";
import styles from "./workspace-files.module.css";

type Attachment = { id: string; name: string; size: number; status: string };

export function WorkspaceFiles({ workspace }: { workspace: ConversationDto }) {
  const { pick } = useI18n();
  const files = new Map<string, Attachment>();
  const groups = [...workspace.messages.map(message => message.metadata.attachments), workspace.context.pending_attachments];
  for (const group of groups) {
    if (!Array.isArray(group)) continue;
    for (const file of group) {
      if (file && typeof file.id === "string" && typeof file.name === "string") files.set(file.id, file);
    }
  }
  const [selectedId, setSelectedId] = useState("");
  const selected = files.get(selectedId) ?? files.values().next().value;
  if (!files.size) return <div className={styles.empty}>
    <FileText size={32} aria-hidden="true" />
    <strong>{pick("No uploaded files yet", "暂无上传文件")}</strong>
    <p>{pick("Add attachments in the conversation to view them here.", "通过对话输入框添加附件，即可在这里查看。")}</p>
  </div>;
  return <div className={styles.layout}>
    <nav className={styles.list} aria-label={pick("Uploaded files", "上传文件")}>
      {[...files.values()].map(file => <button type="button" key={file.id} aria-pressed={selected?.id === file.id} onClick={() => setSelectedId(file.id)}>
        <FileText size={18} aria-hidden="true" />
        <span><strong>{file.name}</strong><small>{Math.max(1, Math.ceil(file.size / 1024))} KB · {file.status === "ready" ? pick("Ready", "已就绪") : file.status === "failed" ? pick("Processing failed", "解析失败") : pick("Processing", "解析中")}</small></span>
      </button>)}
    </nav>
    {selected && <FilePreview key={`${selected.id}:${selected.status}`} file={selected} />}
  </div>;
}

function FilePreview({ file }: { file: Attachment }) {
  const { pick } = useI18n();
  const [preview, setPreview] = useState<{ content: string; truncated: boolean } | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState("");
  const download = async () => {
    setDownloading(true);
    setDownloadError("");
    try {
      const blob = await downloadKnowledgeDocument(file.id);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = file.name;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (caught) {
      setDownloadError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setDownloading(false);
    }
  };
  useEffect(() => {
    const controller = new AbortController();
    previewKnowledgeDocument(file.id, controller.signal).then(result => {
      if (!controller.signal.aborted) setPreview(result);
    }).catch(caught => {
      if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : String(caught));
    });
    return () => controller.abort();
  }, [file.id, attempt]);
  return <section className={styles.preview} aria-label={pick("File preview", "文件预览")}>
    <header><strong>{file.name}</strong><button type="button" disabled={downloading} onClick={() => void download()}><Download size={16} aria-hidden="true" />{downloading ? pick("Downloading…", "正在下载…") : pick("Download original", "下载原文件")}</button></header>
    {downloadError && <p role="alert">{downloadError}</p>}
    {error ? <div role="alert"><p>{error}</p><button type="button" onClick={() => { setError(""); setAttempt(value => value + 1); }}>{pick("Retry", "重试")}</button></div>
      : !preview ? <p role="status"><LoaderCircle size={18} className="auth-spinner" /> {pick("Loading file…", "正在加载文件…")}</p>
      : preview.content ? <><p className={styles.hint}>{pick("Extracted content", "文件解析内容")}{preview.truncated && pick(" · Preview limited; download the original for full content", " · 仅展示部分内容，完整内容请下载原文件")}</p><pre>{preview.content}</pre></>
      : <p>{file.status === "failed" ? pick("Processing failed. Download the original to view it.", "文件解析失败，可下载原文件查看。") : file.status === "ready" ? pick("No text preview available. Download the original to view it.", "此文件暂无可预览文本，可下载原文件查看。") : pick("The file is still processing. You can download the original now.", "文件正在解析中，你也可以先下载原文件查看。")}</p>}
  </section>;
}
