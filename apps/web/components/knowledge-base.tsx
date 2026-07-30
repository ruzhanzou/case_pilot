"use client";

import {
  deleteKnowledgeSource,
  listKnowledgeSources,
  reindexKnowledgeSource,
  uploadKnowledgeFiles,
  type KnowledgeSourceDto,
} from "@/lib/casepilot-api";
import {
  AlertTriangle,
  CheckCircle2,
  FileText,
  LoaderCircle,
  RefreshCw,
  Trash2,
  Upload,
} from "lucide-react";
import {
  type ChangeEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

type KnowledgeBaseProps = {
  spaceId: string;
};

const statusLabels: Record<string, string> = {
  uploaded: "等待解析",
  parsing: "正在解析",
  indexing: "正在索引",
  ready: "可检索",
  failed: "处理失败",
};

const diagnosticLabels: Record<string, string> = {
  embedding_unavailable_lexical_only: "仅全文检索（Embedding 不可用）",
};

export function KnowledgeBase({ spaceId }: KnowledgeBaseProps) {
  const [sources, setSources] = useState<KnowledgeSourceDto[]>([]);
  const [files, setFiles] = useState<File[]>([]);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    const result = await listKnowledgeSources(spaceId);
    setSources(result.filter((item) => item.persistence === "space"));
    setError("");
  }, [spaceId]);

  useEffect(() => {
    let active = true;
    void listKnowledgeSources(spaceId)
      .then((result) => {
        if (active) {
          setSources(result.filter((item) => item.persistence === "space"));
        }
      })
      .catch((caught) => {
        if (active) {
          setError(caught instanceof Error ? caught.message : "知识库加载失败");
        }
      });
    return () => {
      active = false;
    };
  }, [spaceId]);

  useEffect(() => {
    const hasPendingSource = sources.some((source) =>
      ["uploaded", "parsing", "indexing"].includes(source.status),
    );
    if (!hasPendingSource) return;
    const timer = window.setInterval(() => {
      void refresh().catch((caught) => {
        setError(caught instanceof Error ? caught.message : "知识库状态刷新失败");
      });
    }, 1000);
    return () => window.clearInterval(timer);
  }, [refresh, sources]);

  const chooseFiles = (event: ChangeEvent<HTMLInputElement>) => {
    setFiles(Array.from(event.target.files ?? []).slice(0, 6));
    event.target.value = "";
  };

  const upload = async () => {
    if (!files.length) return;
    setBusy(true);
    setError("");
    try {
      await uploadKnowledgeFiles(
        spaceId,
        name.trim() || files[0].name,
        files,
        "space",
      );
      setFiles([]);
      setName("");
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "资料上传失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="knowledge-page">
      <section className="knowledge-hero">
        <div>
          <span>SPACE KNOWLEDGE</span>
          <h1>空间知识库</h1>
          <p>
            上传需求、规则和历史缺陷资料。CasePilot 会保留文档定位，
            在生成时自动检索并展示可追溯引用。
          </p>
        </div>
        <button type="button" onClick={() => inputRef.current?.click()}>
          <Upload size={16} /> 选择资料
        </button>
      </section>

      <section className="knowledge-upload">
        <div>
          <label>
            来源名称
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="例如：账号中心 PRD 与验收规则"
            />
          </label>
          <div className="knowledge-upload__files">
            {files.length
              ? files.map((file) => (
                  <span key={`${file.name}-${file.size}`}>
                    <FileText size={14} /> {file.name}
                  </span>
                ))
              : "PDF、DOCX、XLSX、CSV、MD/TXT、PNG/JPEG；单文件不超过 25 MB"}
          </div>
        </div>
        <button type="button" disabled={!files.length || busy} onClick={upload}>
          {busy ? <LoaderCircle className="auth-spinner" size={16} /> : <Upload size={16} />}
          上传并建立索引
        </button>
        <input
          ref={inputRef}
          hidden
          multiple
          type="file"
          accept=".pdf,.docx,.xlsx,.csv,.md,.txt,.png,.jpg,.jpeg"
          onChange={chooseFiles}
        />
      </section>

      {error ? (
        <div className="knowledge-error" role="alert">
          <AlertTriangle size={16} /> {error}
        </div>
      ) : null}

      <section className="knowledge-list">
        <header>
          <div>
            <strong>已保存来源</strong>
            <span>{sources.length} 个长期知识来源</span>
          </div>
          <button type="button" onClick={() => void refresh()}>
            <RefreshCw size={15} /> 刷新状态
          </button>
        </header>
        {!sources.length ? (
          <div className="knowledge-empty">
            <FileText size={24} />
            <strong>还没有空间知识资料</strong>
            <p>上传后，所有空间成员可在生成时自动检索。</p>
          </div>
        ) : (
          sources.map((source) => (
            <article key={source.id} className="knowledge-source">
              <div className="knowledge-source__icon">
                {source.status === "ready" ? (
                  <CheckCircle2 size={18} />
                ) : source.status === "failed" ? (
                  <AlertTriangle size={18} />
                ) : (
                  <LoaderCircle className="auth-spinner" size={18} />
                )}
              </div>
              <div>
                <strong>{source.name}</strong>
                <p>
                  {source.documents
                    .map((document) => `${document.original_name} · V${document.version}`)
                    .join("，")}
                </p>
                <span>
                  {statusLabels[source.status] ?? source.status}
                  {source.error_code
                    ? ` · ${diagnosticLabels[source.error_code] ?? source.error_code}`
                    : ""}
                </span>
              </div>
              <div className="knowledge-source__actions">
                <button
                  type="button"
                  disabled={source.status === "parsing"}
                  onClick={async () => {
                    await reindexKnowledgeSource(source.id);
                    await refresh();
                  }}
                >
                  <RefreshCw size={14} /> 重新索引
                </button>
                <button
                  type="button"
                  onClick={async () => {
                    if (!window.confirm(`删除“${source.name}”及其索引吗？`)) return;
                    await deleteKnowledgeSource(source.id);
                    await refresh();
                  }}
                >
                  <Trash2 size={14} /> 删除
                </button>
              </div>
            </article>
          ))
        )}
      </section>
    </div>
  );
}
