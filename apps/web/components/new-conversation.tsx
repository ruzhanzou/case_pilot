"use client";

import {
  listGenerationModels,
  type AgentModelId,
  type ConversationDto,
} from "@/lib/casepilot-api";
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
  onSend: (input: {
    content: string;
    modelId: AgentModelId;
  }) => Promise<void>;
  onOpenKnowledge: () => void;
  onOpenLibrary: () => void;
  onOpenHistory: () => void;
};

const conversationExamples = [
  {
    title: "生成登录用例",
    content:
      "为手机号验证码登录生成测试用例，覆盖正常流程、频控、验证码过期和弱网场景。",
  },
  {
    title: "梳理测试范围",
    content: "一个完整的支付退款功能通常需要覆盖哪些测试维度？",
  },
  {
    title: "了解 CasePilot",
    content: "CasePilot 可以帮我完成哪些测试工作？",
  },
];

export function NewConversation({
  spaceName,
  saving,
  conversation,
  onSend,
  onOpenKnowledge,
  onOpenLibrary,
  onOpenHistory,
}: NewConversationProps) {
  const [prompt, setPrompt] = useState("");
  const [modelId, setModelId] = useState<AgentModelId>("auto");
  const [models, setModels] = useState([
    { id: "auto" as AgentModelId, label: "自动选择模型" },
  ]);
  const messageEndRef = useRef<HTMLDivElement>(null);
  const hasConversation = Boolean(conversation?.messages.length);

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
    messageEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [conversation?.messages, hasConversation, saving]);

  const modelLabel = useMemo(
    () => models.find((model) => model.id === modelId)?.label ?? "自动选择模型",
    [modelId, models],
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

  const composer = (
    <form className="new-conversation__composer" onSubmit={submit}>
      <textarea
        value={prompt}
        onChange={(event) => setPrompt(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            event.currentTarget.form?.requestSubmit();
          }
        }}
        placeholder="描述你的测试需求，或直接向 CasePilot 提问"
        aria-label="写给 CasePilot"
        rows={3}
        autoFocus={!hasConversation}
      />
      <footer>
        <button
          type="button"
          className="new-conversation__add"
          onClick={onOpenKnowledge}
          aria-label="添加知识资料"
          title="添加知识资料"
        >
          <Plus size={20} />
        </button>
        <span className="new-conversation__access">
          <Sparkles size={15} />
          自动识别意图
        </span>
        <label className="new-conversation__model">
          <span className="sr-only">生成模型</span>
          <select
            aria-label="生成模型"
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
          aria-label={saving ? "正在处理" : "发送"}
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
          <span>空间知识已启用</span>
          <button type="button" onClick={onOpenLibrary}>
            <Library size={16} />
            用例管理
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
        历史对话
      </button>

      {hasConversation && conversation ? (
        <div className="new-conversation__thread">
          <header>
            <span>CASEPILOT</span>
            <h1>{conversation.title}</h1>
          </header>
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
                      正在思考…
                    </span>
                  ) : (
                    <Streamdown>{message.content}</Streamdown>
                  )}
                </div>
              </article>
            ))}
            <div ref={messageEndRef} />
          </div>
          <div className="new-conversation__dock">{composer}</div>
        </div>
      ) : (
        <div className="new-conversation__landing">
          <div className="new-conversation__hero">
            <h1>今天想测试什么？</h1>
            <p>直接描述需求或提问，CasePilot 会先理解你的意图。</p>
          </div>
          {composer}
          <p className="new-conversation__routing-note">
            仅在识别为“生成用例”时进入用例工作区
          </p>
          <div className="new-conversation__examples">
            <span>你可以这样开始</span>
            <div>
              {conversationExamples.map((example) => (
                <button
                  type="button"
                  key={example.title}
                  onClick={() => setPrompt(example.content)}
                >
                  <strong>{example.title}</strong>
                  <small>{example.content}</small>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
