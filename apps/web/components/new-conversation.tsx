"use client";

import {
  confirmConversationOperationCollection,
  listGenerationModels,
  type AgentModelId,
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
  Bot,
  History,
  Library,
  LoaderCircle,
  Plus,
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
  conversation: ConversationDto | null;
  collections: CaseCollectionDto[];
  onSend: (input: {
    content: string;
    modelId: AgentModelId;
  }) => Promise<void>;
  onUploadFiles: (files: File[]) => Promise<void>;
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
  conversation,
  collections,
  onSend,
  onUploadFiles,
  onOpenLibrary,
  onOpenHistory,
  onConfirmCollection,
  onContinueInNewConversation,
  onCancelOperation,
  onConfirmIntent,
  onConfirmOperation,
}: NewConversationProps) {
  const { t, pick } = useI18n();
  const [prompt, setPrompt] = useState("");
  const [modelId, setModelId] = useState<AgentModelId>("auto");
  const [models, setModels] = useState([
    { id: "auto" as AgentModelId, label: t("model.auto") },
  ]);
  const messageEndRef = useRef<HTMLDivElement>(null);
  const streamScrollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [attachmentNames, setAttachmentNames] = useState<string[]>([]);
  const [collectionChoice, setCollectionChoice] = useState("");
  const [newCollectionName, setNewCollectionName] = useState("");
  const [confirmingCollection, setConfirmingCollection] = useState(false);
  const hasConversation = Boolean(conversation?.messages.length);
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
    : collectionChoice || suggestedCollectionId;

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
    void onSend({ content, modelId }).catch(() => {
      setPrompt(content);
    });
  };

  const submitCollectionChoice = () => {
    if (
      confirmingCollection ||
      (!effectiveCollectionChoice && !newCollectionName.trim())
    ) {
      return;
    }
    setConfirmingCollection(true);
    void confirmConversationOperationCollection(collectionOperation!.id, {
      collectionId: effectiveCollectionChoice || undefined,
      createCollectionName: newCollectionName.trim() || undefined,
    })
      .then(onConfirmCollection)
      .finally(() => setConfirmingCollection(false));
  };

  const composer = (
    <form className="new-conversation__composer" onSubmit={submit}>
      {attachmentNames.length > 0 && (
        <div className="new-conversation__attachments">
          {attachmentNames.map((name) => <span key={name}>{name}</span>)}
        </div>
      )}
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
          accept=".pdf,.txt,application/pdf,text/plain"
          multiple
          onChange={(event) => {
            const files = Array.from(event.target.files ?? []);
            event.target.value = "";
            if (!files.length) return;
            void onUploadFiles(files).then(() => {
              setAttachmentNames((current) => [
                ...current,
                ...files.map((file) => file.name),
              ]);
            });
          }}
        />
        <button
          type="button"
          className="new-conversation__add"
          onClick={() => fileRef.current?.click()}
          aria-label={t("conversation.addKnowledge")}
          title={t("conversation.uploadHint")}
        >
          <Plus size={20} />
        </button>
        <span className="new-conversation__access" aria-live="polite">
          {saving ? (
            <LoaderCircle className="auth-spinner" size={15} />
          ) : (
            <Sparkles size={15} />
          )}
          {saving ? t("conversation.processing") : t("conversation.autoIntent")}
        </span>
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
                submitCollectionChoice();
              }}
            >
              <strong>{t("conversation.confirmCollection")}</strong>
              <p>{t("conversation.collectionLocked")}</p>
              <select
                value={effectiveCollectionChoice}
                disabled={saving || confirmingCollection}
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
                onPointerDown={(event) => {
                  event.preventDefault();
                  submitCollectionChoice();
                }}
              >
                {t("conversation.enterWorkbench")}
              </button>
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
            {saving && !hasRunningAssistant && (
              <article className="new-conversation__message new-conversation__message--assistant">
                <span className="new-conversation__avatar">
                  <Bot size={17} />
                </span>
                <div>
                  <strong>CasePilot</strong>
                  <span className="new-conversation__thinking">
                    <LoaderCircle className="auth-spinner" size={15} />
                    {t("conversation.preparing")}
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
