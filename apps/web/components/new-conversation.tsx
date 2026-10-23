"use client";

// UI identifiers must also work on HTTP origins without crypto.randomUUID.
import { nanoid } from "nanoid/non-secure";

import { ConversationAttachments } from "@/components/conversation-attachments";

import {
  confirmConversationOperationCollection,
  listGenerationModels,
  type AgentModelId,
  type GenerationStrategy,
  type CaseCollectionDto,
  type ConversationDto,
  type ConversationIntent,
  type ConversationTurnDto,
} from "@/lib/casepilot-api";
import { conversationExamples } from "@/content/conversation-examples";
import { useI18n, type TranslationKey } from "@/lib/i18n";
import {
  ArrowUp,
  BookOpen,
  ChevronDown,
  Bot,
  History,
  Library,
  LoaderCircle,
  Plus,
  FileUp,
  CheckCircle2,
  CircleAlert,
  Sparkles,
} from "lucide-react";
import {
  type FormEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Streamdown } from "streamdown";

type NewConversationProps = {
  spaceName: string;
  saving: boolean;
  pendingMessage: string | null;
  conversation: ConversationDto | null;
  collections: CaseCollectionDto[];
  onSend: (input: {
    content: string;
    modelId: AgentModelId;
    useSpaceKnowledge: boolean;
    generationStrategy: GenerationStrategy;
    sourceCollectionIds: string[];
  }) => Promise<void>;
  onRemoveAttachment: (id: string) => Promise<void>;
  onUploadFiles: (files: File[], onProgress?: (percent: number) => void) => Promise<void>;
  onOpenLibrary: () => void;
  onOpenHistory: () => void;
  onConfirmCollection: (
    turn: ConversationTurnDto,
  ) => Promise<void>;
  onContinueInNewConversation: (
    operationId: string,
    collectionId: string,
  ) => Promise<void>;
  onCancelOperation: (operationId: string) => Promise<void>;
  onConfirmIntent: (
    messageId: string,
    intent: ConversationIntent,
  ) => Promise<void>;
  onConfirmOperation: (
    operationId: string,
    intent: ConversationIntent,
  ) => Promise<void>;
};

const coreIntentLabelKeys: Record<ConversationIntent, TranslationKey> = {
  CASE_GENERATE: "intent.generate",
  CASE_MODIFY: "intent.modify",
  CASE_DELETE: "intent.delete",
  CASE_QUERY: "intent.query",
  CASE_REVIEW: "intent.review",
  CASE_DEDUP: "intent.dedup",
  COVERAGE_ANALYZE: "intent.coverage",
  KNOWLEDGE_QA: "intent.knowledge",
  SMALL_TALK: "intent.chat",
  UNRESOLVED: "intent.clarify",
};

const exampleKeys = [
  ["example.generate.title", "example.generate.description", "example.generate.prompt"],
  ["example.scope.title", "example.scope.description", "example.scope.prompt"],
  ["example.modify.title", "example.modify.description", "example.modify.prompt"],
] as const;

const coreIntents: ConversationIntent[] = [
  "CASE_GENERATE",
  "CASE_MODIFY",
  "KNOWLEDGE_QA",
  "SMALL_TALK",
];

export function NewConversation({
  spaceName,
  saving,
  pendingMessage,
  conversation,
  collections,
  onSend,
  onUploadFiles,
  onRemoveAttachment,
  onOpenLibrary,
  onOpenHistory,
  onConfirmCollection,
  onContinueInNewConversation,
  onCancelOperation,
  onConfirmIntent,
  onConfirmOperation,
}: NewConversationProps) {
  const { t, pick } = useI18n();
  const [useSpaceKnowledge, setUseSpaceKnowledge] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [generationStrategy, setGenerationStrategy] = useState<GenerationStrategy>("generate");
  const [sourceCollectionIds, setSourceCollectionIds] = useState<string[]>([]);
  const [modelId, setModelId] = useState<AgentModelId>("auto");
  const [models, setModels] = useState([
    { id: "auto" as AgentModelId, label: t("model.auto") },
  ]);
  const messageEndRef = useRef<HTMLDivElement>(null);
  const streamScrollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [attachments, setAttachments] = useState<{ id: string; name: string; size: number; percent: number; status: "uploading" | "processing" | "ready" | "failed" }[]>([]);
  const uploading = attachments.some(file => file.status === "uploading" || file.status === "processing");
  const [collectionChoice, setCollectionChoice] = useState("");
  const [newCollectionName, setNewCollectionName] = useState("");
  const [confirmingCollection, setConfirmingCollection] = useState(false);
  const [openingWorkbench, setOpeningWorkbench] = useState(false);
  const [collectionError, setCollectionError] = useState("");
  const collectionSubmitRef = useRef(false);
  const confirmedCollectionRef = useRef<{ operationId: string; turn: ConversationTurnDto } | null>(null);
  const hasConversation = Boolean(conversation?.messages.length || pendingMessage);
  const latestConversationMessage = conversation?.messages.at(-1);
  const hasRunningAssistant =
    latestConversationMessage?.role === "assistant" &&
    latestConversationMessage.status === "running";
  const collectionOperation = conversation?.operation_plan?.operations.find(
    (operation) => operation.status === "awaiting_collection",
  );
  const collectionPrompt = [...(conversation?.messages ?? [])]
    .reverse()
    .find((message) => message.status === "awaiting_collection");
  const suggestedCollectionId = String(
    collectionPrompt?.metadata.suggested_collection_id ?? "",
  );
  const allowCreateCollection = Boolean(
    collectionPrompt?.metadata.allow_create_collection,
  );
  const effectiveCollectionChoice = newCollectionName
    ? ""
    : collectionPrompt?.metadata.require_new_collection ? "" : collectionChoice || suggestedCollectionId;

  useEffect(() => {
    void listGenerationModels()
      .then((result) => {
        setModels(
          result.models.map((model) => ({
            id: model.id,
            label: model.label,
          })),
        );
        setModelId(result.default_model_id);
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!hasConversation) return;
    if (hasRunningAssistant) {
      if (streamScrollTimerRef.current) return;
      streamScrollTimerRef.current = setTimeout(() => {
        streamScrollTimerRef.current = null;
        messageEndRef.current?.scrollIntoView({ behavior: "auto" });
      }, 96);
      return;
    }
    messageEndRef.current?.scrollIntoView({
      behavior: "smooth",
    });
  }, [conversation?.messages, hasConversation, hasRunningAssistant]);

  useEffect(
    () => () => {
      if (streamScrollTimerRef.current) {
        clearTimeout(streamScrollTimerRef.current);
      }
    },
    [],
  );

  const modelLabel = useMemo(
    () => models.find((model) => model.id === modelId)?.label ?? t("model.auto"),
    [modelId, models, t],
  );

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const content = prompt.trim();
    if (!content || saving) return;
    setPrompt("");
    void onSend({ content, modelId, useSpaceKnowledge, generationStrategy, sourceCollectionIds: generationStrategy === "generate" ? [] : sourceCollectionIds }).catch(() => {
      setPrompt(content);
    });
  };

  const submitCollectionChoice = async () => {
    if (collectionSubmitRef.current || saving || !collectionOperation ||
      (!effectiveCollectionChoice && !newCollectionName.trim())) return;
    collectionSubmitRef.current = true;
    setConfirmingCollection(true);
    setCollectionError("");
    try {
      const cached = confirmedCollectionRef.current;
      const turn = cached?.operationId === collectionOperation.id ? cached.turn :
        await confirmConversationOperationCollection(collectionOperation.id, {
          collectionId: effectiveCollectionChoice || undefined,
          createCollectionName: newCollectionName.trim() || undefined,
        });
      confirmedCollectionRef.current = { operationId: collectionOperation.id, turn };
      setOpeningWorkbench(true);
      await onConfirmCollection(turn);
    } catch (error) {
      setCollectionError(error instanceof Error ? error.message : pick("Unable to open the workspace. Please retry.", "打开工作台失败，请重试。"));
    } finally {
      collectionSubmitRef.current = false;
      setConfirmingCollection(false);
      setOpeningWorkbench(false);
    }
  };

  const composer = (
    <form className="new-conversation__composer" onSubmit={submit}>
          {attachments.length > 0 && (
            <div className="principle-attachments">
              {attachments.map((file) => (
                <div key={file.id} className="principle-attachment" data-status={file.status}>
                  <FileUp size={20} aria-hidden="true" />
                  <div className="principle-attachment__body">
                    <strong title={file.name}>{file.name}</strong>
                    <small role="status">{Math.max(1, Math.round(file.size / 1024))} KB · {file.status === "ready" ? pick("Ready", "已就绪") : file.status === "failed" ? pick("Failed · select file to retry", "失败 · 请重新选择文件") : file.status === "processing" ? (/\.xlsx?$/i.test(file.name) ? pick("Uploaded · organizing Excel cases…", "已上传 · 正在识别整理 Excel 用例…") : pick("Uploaded · processing document", "已上传 · 正在解析资料")) : pick(`Uploading ${file.percent}%`, `上传中 ${file.percent}%`)}</small>
                    {file.status === "uploading" && <progress aria-label={pick(`Upload progress for ${file.name}`, `${file.name} 上传进度`)} value={file.percent} max={100} />}
                  </div>
                  {file.status === "ready" ? <CheckCircle2 size={16} aria-label={pick("Ready", "已就绪")} /> : file.status === "failed" ? <CircleAlert size={16} /> : <LoaderCircle size={16} className="auth-spinner" aria-hidden="true" />}
                </div>
              ))}
            </div>
          )}
          {!pendingMessage && <ConversationAttachments pending disabled={saving} onRemove={id => { void onRemoveAttachment(id); }} metadata={{ attachments: (
            Array.isArray(conversation?.context.pending_attachments) ? conversation.context.pending_attachments : []
          ).filter((file: { name: string }) => !attachments.some(local => local.name === file.name && local.status !== "failed")) }} />}
      <textarea
        value={prompt}
        onChange={(event) => setPrompt(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            event.currentTarget.form?.requestSubmit();
          }
        }}
        placeholder={t("conversation.placeholder")}
        aria-label={t("conversation.write")}
        rows={3}
        autoFocus={!hasConversation}
      />
      <footer>
        <input
          ref={fileRef}
          hidden
          type="file"
          accept=".pdf,.txt,.xlsx,.xls,application/pdf,text/plain,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel"
          multiple
          onChange={(event) => {
            const files = Array.from(event.target.files ?? []);
            event.target.value = "";
            if (!files.length) return;
            const entries = files.map(file => ({ id: nanoid(), name: file.name, size: file.size, percent: 0, status: "uploading" as const }));
            const ids = new Set(entries.map(file => file.id));
            setAttachments(current => [...current, ...entries]);
            const update = (values: Partial<(typeof attachments)[number]>) => setAttachments(current => current.map(file => ids.has(file.id) ? { ...file, ...values } : file));
            void onUploadFiles(files, percent => update({ percent, status: percent === 100 ? "processing" : "uploading" }))
              .then(() => setAttachments(current => current.filter(file => !ids.has(file.id))))
              .catch(() => update({ status: "failed" }));
          }}
        />
        <button
          type="button"
          className="new-conversation__add"
          disabled={saving}
          onClick={() => fileRef.current?.click()}
          aria-label={t("conversation.addKnowledge")}
          title={t("conversation.uploadHint")}
        >
          <Plus size={20} />
        </button>
        <button type="button" role="switch" aria-checked={useSpaceKnowledge}
          disabled={saving} onClick={() => setUseSpaceKnowledge(value => !value)}
          aria-label={pick("Search space knowledge", "搜索空间知识库")}>
          {pick("Space knowledge", "空间知识库")}：{useSpaceKnowledge ? pick("On", "开") : pick("Off", "关")}
        </button>
        <span className="new-conversation__access" aria-live="polite">
          {saving ? (
            <LoaderCircle className="auth-spinner" size={15} />
          ) : (
            <Sparkles size={15} />
          )}
          {uploading ? pick("Preparing attachment…", "正在准备附件…") : saving ? t("conversation.processing") : t("conversation.autoIntent")}
        </span>
        <label className="new-conversation__strategy-picker">
        <select aria-label={pick("Generation strategy", "用例生成策略")} value={generationStrategy} disabled={saving} onChange={event => {
          const strategy = event.target.value as GenerationStrategy;
          setGenerationStrategy(strategy);
          setPrompt(current => `策略：${strategy}\n${current.replace(/^策略：[a-z_]+\n/, "")}`);
        }}>
          <option value="generate">{pick("Generate new cases", "直接生成")}</option>
          <option value="select">{pick("Select existing assets", "选择现有资产组成新集合")}</option>
          <option value="select_and_generate">{pick("Reuse, then generate missing coverage", "先复用，再补充生成")}</option>
        </select>
          <span aria-hidden="true">{generationStrategy === "generate" ? pick("Generate", "直接生成") : generationStrategy === "select" ? pick("Select assets", "选用资产") : pick("Reuse + generate", "复用并生成")}<ChevronDown size={14} /></span>
        </label>
        <label className="new-conversation__model">
          <span className="sr-only">{t("conversation.model")}</span>
          <select
            aria-label={t("conversation.model")}
            value={modelId}
            onChange={(event) => setModelId(event.target.value)}
            disabled={saving}
          >
            {models.map((model) => (
              <option key={model.id} value={model.id}>
                {model.label}
              </option>
            ))}
          </select>
          <span aria-hidden="true">{modelLabel}</span>
        </label>
        <button
          type="submit"
          className="new-conversation__send"
          disabled={!prompt.trim() || saving}
          aria-label={saving ? t("conversation.sending") : t("conversation.send")}
        >
          {saving ? (
            <LoaderCircle className="auth-spinner" size={19} />
          ) : (
            <ArrowUp size={20} />
          )}
        </button>
      </footer>
      {generationStrategy !== "generate" && <fieldset className="new-conversation__sources" disabled={saving}>
        <legend>{pick("Source collections (multiple)", "来源用例集（可多选）")}</legend>
        {generationStrategy === "select_and_generate" && <p>{pick("Leave empty to search by test object across the space.", "不选集合时，按测试对象检索空间内的用例资产。")}</p>}
        <div className="new-conversation__source-list">
        {collections.map(collection => <label key={collection.id}>
          <input type="checkbox" checked={sourceCollectionIds.includes(collection.id)} onChange={event => setSourceCollectionIds(current => event.target.checked ? [...current, collection.id] : current.filter(id => id !== collection.id))} />
          <span>{collection.name}<small>{pick(`${collection.case_count} cases`, `${collection.case_count} 条用例`)}</small></span>
        </label>)}
        </div>
        {generationStrategy === "select" && !sourceCollectionIds.length && <p>{pick("Choose multiple source collections, or leave empty to search by test object.", "可选择多个来源集合；不选择时按测试对象检索。")}</p>}
      </fieldset>}
      {!hasConversation && (
        <div className="new-conversation__context">
          <span>
            <BookOpen size={17} />
            {spaceName}
          </span>
          <span>{t("conversation.knowledgeEnabled")}</span>
          <button type="button" onClick={onOpenLibrary}>
            <Library size={16} />
            {t("nav.cases")}
          </button>
        </div>
      )}
    </form>
  );

  return (
    <section
      className={`new-conversation${
        hasConversation ? " new-conversation--active" : ""
      }`}
    >
      <button
        type="button"
        className="new-conversation__history"
        onClick={onOpenHistory}
      >
        <History size={17} />
        {t("conversation.history")}
      </button>

      {hasConversation && conversation ? (
        <div className="new-conversation__thread">
          <div className="new-conversation__thread-top">
            <header>
              <span>CASEPILOT</span>
              <h1>{conversation.title}</h1>
            </header>
            {conversation.operation_plan &&
              conversation.operation_plan.operations.length > 1 && (
              <ol className="conversation-operation-plan" aria-label={pick("Multi-action progress", "多意图执行进度")}>
                {conversation.operation_plan.operations.map((operation) => (
                  <li key={operation.id} data-status={operation.status}>
                    <span>{operation.sequence + 1}</span>
                    <strong>{t(coreIntentLabelKeys[operation.intent])}</strong>
                    <small>{operation.status}</small>
                    {operation.status === "awaiting_intent" && (
                      <div className="conversation-operation-confirmation">
                        {coreIntents.map((intent) => (
                          <button
                            type="button"
                            key={intent}
                            disabled={saving}
                            onClick={() => void onConfirmOperation(operation.id, intent)}
                          >
                            {t(coreIntentLabelKeys[intent])}
                          </button>
                        ))}
                      </div>
                    )}
                  </li>
                ))}
              </ol>
              )}
            {collectionOperation && (
              <form
              className="conversation-collection-picker"
              onSubmit={(event) => {
                event.preventDefault();
                void submitCollectionChoice();
              }}
            >
              <strong>{t("conversation.confirmCollection")}</strong>
              <p>{t("conversation.collectionLocked")}</p>
              <select
                value={effectiveCollectionChoice}
                disabled={saving || confirmingCollection || Boolean(collectionPrompt?.metadata.require_new_collection)}
                onChange={(event) => {
                  setCollectionChoice(event.target.value);
                  setNewCollectionName("");
                }}
              >
                <option value="" disabled>{t("conversation.chooseCollection")}</option>
                {collections.map((collection) => (
                  <option key={collection.id} value={collection.id}>
                    {collection.name}（{collection.case_count}）
                  </option>
                ))}
              </select>
              {allowCreateCollection && (
                <input
                  value={newCollectionName}
                  placeholder={t("conversation.newCollection")}
                  maxLength={160}
                  disabled={saving || confirmingCollection}
                  onChange={(event) => {
                    setNewCollectionName(event.target.value);
                    if (event.target.value) setCollectionChoice("");
                  }}
                />
              )}
              <button
                type="submit"
                disabled={
                  saving || confirmingCollection ||
                  (!effectiveCollectionChoice && !newCollectionName.trim())
                }
                aria-busy={confirmingCollection}
              >
                {confirmingCollection && <LoaderCircle className="auth-spinner" size={17} aria-hidden="true" />}
                {confirmingCollection
                  ? openingWorkbench ? pick("Opening workspace…", "正在打开工作台…") : pick("Confirming collection…", "正在确认集合…")
                  : t("conversation.enterWorkbench")}
              </button>
              {confirmingCollection && <p role="status">{pick("Please wait while we prepare your workspace.", "正在准备工作台，请稍候。")}</p>}
              {collectionError && <p role="alert">{collectionError}</p>}
              </form>
            )}
          </div>
          <div className="new-conversation__messages" aria-live="polite">
            {conversation.messages.map((message) => (
              <article
                key={message.id}
                className={`new-conversation__message new-conversation__message--${message.role}`}
              >
                {message.role === "assistant" && (
                  <span className="new-conversation__avatar">
                    <Bot size={17} />
                  </span>
                )}
                <div>
                  {message.role === "assistant" && (
                    <strong>CasePilot</strong>
                  )}
                  <ConversationAttachments metadata={message.metadata} />
                  {message.status === "running" && !message.content ? (
                    <span className="new-conversation__thinking">
                      <LoaderCircle className="auth-spinner" size={15} />
                      {t("conversation.thinking")}
                    </span>
                  ) : (
                    <Streamdown
                      animated={{
                        animation: "fadeIn",
                        duration: 90,
                        easing: "ease-out",
                        sep: "char",
                        stagger: 8,
                      }}
                      caret="block"
                      isAnimating={message.status === "running"}
                    >
                      {message.content}
                    </Streamdown>
                  )}
                  {message.status === "awaiting_intent" && (
                    <div className="conversation-intent-confirmation">
                      <span>{t("conversation.intentUnknown")}</span>
                      <div>
                        {[
                          message.intent,
                          ...coreIntents.filter(
                            (intent) => intent !== message.intent,
                          ),
                        ]
                          .filter(
                            (intent): intent is ConversationIntent =>
                              Boolean(intent),
                          )
                          .slice(0, 4)
                          .map((intent) => (
                            <button
                              type="button"
                              key={intent}
                              disabled={saving}
                              onClick={() =>
                                void onConfirmIntent(message.id, intent)
                              }
                            >
                              {t(coreIntentLabelKeys[intent])}
                            </button>
                          ))}
                      </div>
                    </div>
                  )}
                  {message.metadata.action === "new_conversation_required" && (
                    <div className="conversation-cross-collection">
                      <span>{t("conversation.crossCollection")}</span>
                      <button
                        type="button"
                        disabled={saving}
                        onClick={() => {
                          const operationId = String(
                            message.metadata.operation_id ?? "",
                          );
                          const collectionId = String(
                            message.metadata.requested_collection_id ?? "",
                          );
                          if (operationId && collectionId) {
                            void onContinueInNewConversation(operationId, collectionId);
                          }
                        }}
                      >
                        {t("conversation.openCollection")}
                      </button>
                      <button
                        type="button"
                        className="is-secondary"
                        disabled={saving}
                        onClick={() => {
                          const operationId = String(
                            message.metadata.operation_id ?? "",
                          );
                          if (operationId) void onCancelOperation(operationId);
                        }}
                      >
                        {t("conversation.cancel")}
                      </button>
                    </div>
                  )}
                </div>
              </article>
            ))}
            {pendingMessage && (
              <article className="new-conversation__message new-conversation__message--user">
                <div>
                  <ConversationAttachments metadata={{ attachments: conversation?.context.pending_attachments ?? [] }} />
                  <p>{pendingMessage}</p>
                </div>
              </article>
            )}
            {saving && !uploading && !hasRunningAssistant && (
              <article className="new-conversation__message new-conversation__message--assistant">
                <span className="new-conversation__avatar">
                  <Bot size={17} />
                </span>
                <div>
                  <strong>CasePilot</strong>
                  <span className="new-conversation__thinking">
                    <LoaderCircle className="auth-spinner" size={15} />
                    {t("conversation.thinking")}
                  </span>
                </div>
              </article>
            )}
            <div ref={messageEndRef} />
          </div>
          <div className="new-conversation__dock">{composer}</div>
        </div>
      ) : (
        <div className="new-conversation__landing">
          <div className="new-conversation__hero">
            <h1>{t("conversation.hero")}</h1>
            <p>{t("conversation.heroHint")}</p>
          </div>
          {composer}
          <p className="new-conversation__routing-note">
            {t("conversation.routing")}
          </p>
          <div className="new-conversation__examples">
            <span>{t("conversation.examples")}</span>
            <div>
              {conversationExamples.map((example, index) => (
                <button
                  type="button"
                  key={example.title}
                  onClick={() => setPrompt(t(exampleKeys[index][2]))}
                >
                  <strong>{t(exampleKeys[index][0])}</strong>
                  <small>{t(exampleKeys[index][1])}</small>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
