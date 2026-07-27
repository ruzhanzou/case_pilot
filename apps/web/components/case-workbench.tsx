"use client";

import { CaseMindMap } from "@/components/case-mind-map";
import { CaseEditorDialog } from "@/components/case-editor-dialog";
import type {
  CaseCollectionDto,
  TestCaseDto,
  TestCaseInput,
} from "@/lib/casepilot-api";
import {
  ArrowUp,
  Bot,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  ClipboardList,
  FileSpreadsheet,
  FileText,
  GitFork,
  List,
  LoaderCircle,
  MessageSquarePlus,
  Paperclip,
  Pencil,
  Plus,
  Save,
  Send,
  Sparkles,
  Tags,
  WandSparkles,
  X,
} from "lucide-react";
import {
  type CSSProperties,
  type ChangeEvent,
  type FormEvent,
  type PointerEvent as ReactPointerEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

type CaseWorkbenchProps = {
  spaceName: string;
  collections: CaseCollectionDto[];
  selectedCollection: CaseCollectionDto | null;
  cases: TestCaseDto[];
  loading: boolean;
  onSelectCollection: (collectionId: string) => void;
  onSelectCase: (caseId: string) => void;
  onCreateCase: (module?: string) => void;
  onEditCase: (testCase: TestCaseDto) => void;
  onImportCases: (inputs: TestCaseInput[]) => Promise<TestCaseDto[]>;
  initialMode?: "create" | "workspace";
  onDirtyChange?: (dirty: boolean) => void;
};

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
};

const generationStages = [
  "理解测试目标",
  "识别风险与边界",
  "组织场景结构",
  "生成结构化用例",
];

const starterPrompts = [
  "根据需求梳理正常、异常和边界场景",
  "补充多人协作与中断恢复用例",
  "检查现有用例集的覆盖缺口",
];

const modelOptions = [
  { value: "auto", label: "自动选择" },
  { value: "test-design-pro", label: "Test Design Pro" },
  { value: "local", label: "本地模型" },
];

function normalizeTitle(prompt: string) {
  const compact = prompt.replace(/\s+/g, " ").trim();
  return compact.length > 30 ? `${compact.slice(0, 30)}…` : compact;
}

function buildGeneratedInputs(
  prompt: string,
  modelLabel: string,
): TestCaseInput[] {
  const sourceTitle = normalizeTitle(prompt) || "当前需求";
  const isAudio = /音频|录音|麦克风|转写|audio/i.test(prompt);
  const isAuth = /登录|账号|密码|验证码|鉴权|权限/i.test(prompt);
  const moduleName = isAudio ? "音频主流程" : isAuth ? "账号与认证" : "核心流程";
  const stamp = Date.now().toString().slice(-6);
  const scenarios = isAudio
    ? [
        ["正常开始录音并持续显示输入反馈", "P0", "点击开始录音并连续说话", "录音状态稳定，音量或波形持续更新"],
        ["首次使用时完成麦克风授权", "P0", "首次进入并允许麦克风权限", "权限申请只出现一次，录音入口立即可用"],
        ["拒绝麦克风权限后提供恢复引导", "P0", "拒绝权限后再次尝试录音", "说明受限原因，并提供可执行的设置入口"],
        ["网络中断后保留本地录音并恢复处理", "P1", "录音中断开网络并在 20 秒后恢复", "本地录音不中断，恢复后不重复或丢失结果"],
        ["长时间静音不会误结束录音", "P1", "录音中保持静音 60 秒后继续说话", "录音任务保持有效，后续音频继续被接收"],
        ["切换音频输入设备后状态保持一致", "P2", "录音中连接或断开蓝牙耳机", "设备切换有反馈，录音状态和时间轴保持连续"],
      ]
    : isAuth
      ? [
          ["使用正确凭据完成登录", "P0", "输入有效账号与正确凭据并提交", "登录成功并进入目标工作空间"],
          ["错误凭据不会创建登录会话", "P0", "输入错误凭据并提交", "拒绝登录，提示明确且不泄露账号信息"],
          ["连续失败触发账号保护策略", "P0", "连续提交错误凭据直至达到阈值", "按规则限流或锁定，并明确说明恢复方式"],
          ["会话过期后安全返回登录页", "P1", "等待会话过期后访问受保护页面", "原会话失效，返回登录页且不展示敏感内容"],
          ["网络恢复后允许重新提交", "P1", "提交时断网，恢复网络后重试", "失败反馈可恢复，不产生重复会话"],
        ]
      : [
          [`${sourceTitle}主流程可完整完成`, "P0", "使用有效数据完成核心操作", "流程成功结束并生成唯一业务结果"],
          [`${sourceTitle}必填输入为空时阻止提交`, "P0", "清空必填内容后提交", "在对应位置提示错误且不产生业务数据"],
          [`${sourceTitle}服务异常时给出可恢复反馈`, "P1", "模拟服务暂时不可用并执行操作", "错误说明清晰，恢复后可以安全重试"],
          [`${sourceTitle}重复操作保持幂等`, "P1", "快速连续执行两次相同操作", "只产生一次有效结果，不出现重复数据"],
          [`${sourceTitle}临界数据按规则处理`, "P2", "分别提交最小值、最大值和超限值", "边界内成功，超限值被明确阻止"],
        ];

  return scenarios.map(([title, priority, action, expected], index) => ({
    case_key: `AI-${stamp}-${String(index + 1).padStart(2, "0")}`,
    title,
    module: moduleName,
    priority: priority as TestCaseInput["priority"],
    case_type: "功能",
    tags: [
      index === 0 ? "主流程" : index === 1 ? "异常" : index === 2 ? "恢复" : "边界",
      "AI 候选",
    ],
    preconditions: [
      "已进入目标功能页面",
      index > 1 ? "基础服务与测试数据已准备" : "使用有效测试账号",
    ],
    steps: [
      {
        id: `step-${index + 1}`,
        action,
        expected,
      },
    ],
    source: `AI Workbench · ${modelLabel} · ${sourceTitle}`,
  }));
}

function toPreviewCase(input: TestCaseInput, index: number): TestCaseDto {
  return {
    id: `candidate-${index}`,
    case_key: input.case_key ?? `AI-DRAFT-${index + 1}`,
    collection_ids: [],
    current_revision_id: `candidate-revision-${index}`,
    revision_number: 1,
    title: input.title,
    module: input.module,
    priority: input.priority,
    case_type: input.case_type,
    tags: input.tags,
    preconditions: input.preconditions,
    steps: input.steps.map((step, stepIndex) => ({
      id: step.id ?? `candidate-${index}-step-${stepIndex}`,
      action: step.action,
      expected: step.expected,
    })),
    source: input.source,
    created_at: new Date().toISOString(),
  };
}

function fileIcon(file: File) {
  return /sheet|excel|csv/i.test(file.type) || /\.(xlsx?|csv)$/i.test(file.name)
    ? FileSpreadsheet
    : FileText;
}

export function CaseWorkbench({
  spaceName,
  collections,
  selectedCollection,
  cases,
  loading,
  onSelectCollection,
  onSelectCase,
  onCreateCase,
  onEditCase,
  onImportCases,
  initialMode = "create",
  onDirtyChange,
}: CaseWorkbenchProps) {
  const [screen, setScreen] = useState<"create" | "workspace">(initialMode);
  const [prompt, setPrompt] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>(() =>
    initialMode === "workspace"
      ? [
          {
            id: "assistant-existing",
            role: "assistant",
            content: `已打开“${selectedCollection?.name ?? "当前用例集"}”。你可以查看脑图、选择用例，或继续输入需求补充候选用例。`,
          },
        ]
      : [],
  );
  const [activeStage, setActiveStage] = useState(-1);
  const [isGenerating, setIsGenerating] = useState(false);
  const [generatedInputs, setGeneratedInputs] = useState<TestCaseInput[]>([]);
  const [generatedCases, setGeneratedCases] = useState<TestCaseDto[]>([]);
  const [selectedCandidateIds, setSelectedCandidateIds] = useState<string[]>([]);
  const [candidateEditorIndex, setCandidateEditorIndex] = useState<number | null>(
    null,
  );
  const [selectedCaseId, setSelectedCaseId] = useState("");
  const [viewMode, setViewMode] = useState<"mind-map" | "list">("mind-map");
  const [saving, setSaving] = useState(false);
  const [savedNotice, setSavedNotice] = useState("");
  const [rewritePrompt, setRewritePrompt] = useState("");
  const [modelId, setModelId] = useState("auto");
  const [chatWidth, setChatWidth] = useState(340);
  const [inspectorWidth, setInspectorWidth] = useState(350);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const resizeCleanupRef = useRef<(() => void) | null>(null);
  const hasUnsavedDraft =
    isGenerating ||
    generatedInputs.length > 0 ||
    Boolean(prompt.trim()) ||
    files.length > 0;

  useEffect(
    () => () => {
      if (timerRef.current) clearInterval(timerRef.current);
      resizeCleanupRef.current?.();
    },
    [],
  );

  useEffect(() => {
    onDirtyChange?.(hasUnsavedDraft);
    return () => onDirtyChange?.(false);
  }, [hasUnsavedDraft, onDirtyChange]);

  useEffect(() => {
    if (!hasUnsavedDraft) return;
    const warnBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", warnBeforeUnload);
    return () => window.removeEventListener("beforeunload", warnBeforeUnload);
  }, [hasUnsavedDraft]);

  const visibleCases = generatedCases.length ? generatedCases : cases;
  const selectedCase =
    visibleCases.find((item) => item.id === selectedCaseId) ??
    visibleCases[0] ??
    null;

  const modules = useMemo(
    () => new Set(visibleCases.map((item) => item.module || "未分类")).size,
    [visibleCases],
  );
  const selectedModelLabel =
    modelOptions.find((option) => option.value === modelId)?.label ??
    modelOptions[0].label;
  const selectedCandidateCount = selectedCandidateIds.length;

  const confirmDiscardDraft = () =>
    !hasUnsavedDraft ||
    window.confirm("当前对话或候选用例尚未保存，确认放弃并继续吗？");

  const toggleCandidate = (caseId: string) => {
    setSelectedCandidateIds((current) =>
      current.includes(caseId)
        ? current.filter((id) => id !== caseId)
        : [...current, caseId],
    );
  };

  const editCandidate = (testCase: TestCaseDto) => {
    const index = generatedCases.findIndex((item) => item.id === testCase.id);
    if (index >= 0) setCandidateEditorIndex(index);
  };

  const resizePanel = (
    panel: "chat" | "inspector",
    event: ReactPointerEvent<HTMLDivElement>,
  ) => {
    event.preventDefault();
    resizeCleanupRef.current?.();
    const startX = event.clientX;
    const startWidth = panel === "chat" ? chatWidth : inspectorWidth;
    const workbench = event.currentTarget.parentElement;
    const workbenchRect = workbench?.getBoundingClientRect();
    let nextWidth = startWidth;
    const move = (moveEvent: PointerEvent) => {
      const delta = moveEvent.clientX - startX;
      const next =
        panel === "chat" ? startWidth + delta : startWidth - delta;
      nextWidth = Math.min(
        520,
        Math.max(panel === "chat" ? 280 : 300, next),
      );
      if (workbench && workbenchRect) {
        const guideX =
          panel === "chat"
            ? nextWidth
            : workbenchRect.width - nextWidth - 7;
        workbench.style.setProperty(
          "--workbench-resize-guide-x",
          `${guideX}px`,
        );
      }
    };
    const cleanup = () => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", commit);
      document.removeEventListener("pointercancel", cleanup);
      document.body.classList.remove("is-resizing-workbench");
      workbench?.classList.remove("is-preview-resizing");
      workbench?.style.removeProperty("--workbench-resize-guide-x");
      resizeCleanupRef.current = null;
    };
    const commit = () => {
      if (panel === "chat") setChatWidth(nextWidth);
      else setInspectorWidth(nextWidth);
      cleanup();
    };
    resizeCleanupRef.current = cleanup;
    document.body.classList.add("is-resizing-workbench");
    workbench?.classList.add("is-preview-resizing");
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", commit);
    document.addEventListener("pointercancel", cleanup);
  };

  const resizeWithKeyboard = (
    panel: "chat" | "inspector",
    key: string,
  ) => {
    if (key !== "ArrowLeft" && key !== "ArrowRight") return;
    const direction = key === "ArrowRight" ? 16 : -16;
    if (panel === "chat") {
      setChatWidth((current) => Math.min(520, Math.max(280, current + direction)));
      return;
    }
    setInspectorWidth((current) =>
      Math.min(520, Math.max(300, current - direction)),
    );
  };

  const resetConversation = () => {
    if (!confirmDiscardDraft()) return;
    if (timerRef.current) clearInterval(timerRef.current);
    setScreen("create");
    setPrompt("");
    setFiles([]);
    setMessages([]);
    setGeneratedInputs([]);
    setGeneratedCases([]);
    setSelectedCandidateIds([]);
    setCandidateEditorIndex(null);
    setSelectedCaseId("");
    setActiveStage(-1);
    setIsGenerating(false);
    setSavedNotice("");
  };

  const submitPrompt = (event?: FormEvent) => {
    event?.preventDefault();
    const content = prompt.trim();
    if (!content || isGenerating) return;
    if (
      generatedInputs.length &&
      !window.confirm("生成新候选会替换当前未写入的候选内容，是否继续？")
    ) {
      return;
    }
    const userMessage: ChatMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content,
    };
    setMessages((current) => [...current, userMessage]);
    setPrompt("");
    setScreen("workspace");
    setGeneratedInputs([]);
    setGeneratedCases([]);
    setSavedNotice("");
    setActiveStage(0);
    setIsGenerating(true);

    let stage = 0;
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => {
      stage += 1;
      if (stage < generationStages.length) {
        setActiveStage(stage);
        return;
      }
      if (timerRef.current) clearInterval(timerRef.current);
      const inputs = buildGeneratedInputs(content, selectedModelLabel);
      const previews = inputs.map(toPreviewCase);
      setGeneratedInputs(inputs);
      setGeneratedCases(previews);
      setSelectedCandidateIds(previews.map((item) => item.id));
      setSelectedCaseId(previews[0]?.id ?? "");
      setMessages((current) => [
        ...current,
        {
          id: `assistant-${Date.now()}`,
          role: "assistant",
          content: `已围绕“${normalizeTitle(content)}”整理 ${previews.length} 条候选用例，覆盖主流程、异常、边界与恢复场景。请在右侧逐条评审，确认后再写入用例集。`,
        },
      ]);
      setIsGenerating(false);
      setActiveStage(generationStages.length);
    }, 420);
  };

  const addFiles = (event: ChangeEvent<HTMLInputElement>) => {
    const next = Array.from(event.target.files ?? []);
    setFiles((current) => [...current, ...next].slice(0, 6));
    event.target.value = "";
  };

  const saveCandidates = async () => {
    if (
      !generatedInputs.length ||
      !selectedCollection ||
      !selectedCandidateIds.length
    ) {
      return;
    }
    setSaving(true);
    setSavedNotice("");
    try {
      const selectedInputs = generatedInputs.filter((_, index) =>
        selectedCandidateIds.includes(`candidate-${index}`),
      );
      const created = await onImportCases(selectedInputs);
      setGeneratedInputs([]);
      setGeneratedCases([]);
      setSelectedCandidateIds([]);
      setSelectedCaseId(created[0]?.id ?? "");
      setSavedNotice(`${created.length} 条候选用例已写入“${selectedCollection.name}”`);
      setMessages((current) => [
        ...current,
        {
          id: `saved-${Date.now()}`,
          role: "assistant",
          content: `已保存 ${created.length} 条用例。它们现在是正式用例资产，可继续编辑、评审或创建执行任务。`,
        },
      ]);
    } catch {
      setSavedNotice("写入失败，请根据页面提示处理后重试");
    } finally {
      setSaving(false);
    }
  };

  const openExistingCollection = () => {
    if (!confirmDiscardDraft()) return;
    setScreen("workspace");
    setGeneratedInputs([]);
    setGeneratedCases([]);
    setSelectedCandidateIds([]);
    setSelectedCaseId(cases[0]?.id ?? "");
    setMessages([
      {
        id: "assistant-existing",
        role: "assistant",
        content: `已打开“${selectedCollection?.name ?? "当前用例集"}”。你可以在这里查看脑图、选择用例，或继续输入需求补充候选用例。`,
      },
    ]);
  };

  const saveCandidateEdit = async (input: TestCaseInput) => {
    if (candidateEditorIndex === null) return;
    setGeneratedInputs((current) =>
      current.map((item, index) =>
        index === candidateEditorIndex ? { ...input, case_key: item.case_key } : item,
      ),
    );
    setGeneratedCases((current) =>
      current.map((item, index) =>
        index === candidateEditorIndex
          ? toPreviewCase(
              { ...input, case_key: generatedInputs[index]?.case_key },
              index,
            )
          : item,
      ),
    );
    setCandidateEditorIndex(null);
  };

  const runRewrite = () => {
    const instruction = rewritePrompt.trim();
    if (!instruction || !selectedCase) return;
    setMessages((current) => [
      ...current,
      {
        id: `rewrite-user-${Date.now()}`,
        role: "user",
        content: `改写 ${selectedCase.case_key}：${instruction}`,
      },
      {
        id: `rewrite-assistant-${Date.now()}`,
        role: "assistant",
        content:
          "已记录改写方向。为避免覆盖正式用例，当前先作为评审建议保留；你可以点击详情区的编辑按钮完成结构化修订。",
      },
    ]);
    setRewritePrompt("");
  };

  if (screen === "create") {
    return (
      <div className="workbench-create">
        <section className="workbench-create__hero">
          <span className="workbench-kicker">
            <Sparkles size={15} /> AI TEST DESIGNER
          </span>
          <h1>把需求变成可评审的测试用例</h1>
          <p>
            描述测试目标，或添加需求文档。CasePilot 会先生成候选内容，
            经你确认后再写入正式用例集。
          </p>

          <form className="workbench-create__composer" onSubmit={submitPrompt}>
            <label>
              <span>写给 CasePilot</span>
              <textarea
                autoFocus
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    submitPrompt();
                  }
                }}
                placeholder="例如：根据 Audio Feature 需求补充录音、实时反馈和中断恢复用例…"
              />
            </label>
            {!!files.length && (
              <div className="workbench-file-list">
                {files.map((file, index) => {
                  const Icon = fileIcon(file);
                  return (
                    <span key={`${file.name}-${index}`}>
                      <Icon size={14} />
                      {file.name}
                      <button
                        type="button"
                        aria-label={`移除 ${file.name}`}
                        onClick={() =>
                          setFiles((current) =>
                            current.filter((_, itemIndex) => itemIndex !== index),
                          )
                        }
                      >
                        <X size={13} />
                      </button>
                    </span>
                  );
                })}
              </div>
            )}
            <footer>
              <div className="workbench-create__attachment">
                <button
                  type="button"
                  className="workbench-icon-button"
                  onClick={() => fileInputRef.current?.click()}
                  aria-label="添加需求文件"
                >
                  <Paperclip size={17} />
                </button>
                <span>支持 Word、PDF、Excel · 最多 6 个文件</span>
              </div>
              <div className="workbench-create__submit">
                <label className="workbench-model-select">
                  <Sparkles size={14} />
                  <span className="sr-only">生成模型</span>
                  <select
                    aria-label="生成模型"
                    value={modelId}
                    onChange={(event) => setModelId(event.target.value)}
                  >
                    {modelOptions.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                  <ChevronDown size={13} />
                </label>
                <button
                  type="submit"
                  className="workbench-send-button"
                  disabled={!prompt.trim()}
                >
                  开始设计 <ArrowUp size={17} />
                </button>
              </div>
            </footer>
            <input
              ref={fileInputRef}
              hidden
              multiple
              type="file"
              accept=".doc,.docx,.pdf,.xls,.xlsx,.csv,.txt,.md"
              onChange={addFiles}
            />
          </form>

          <div className="workbench-starters">
            <span>可以这样开始</span>
            <div>
              {starterPrompts.map((item) => (
                <button type="button" key={item} onClick={() => setPrompt(item)}>
                  {item} <Send size={13} />
                </button>
              ))}
            </div>
          </div>
        </section>

        <aside className="workbench-create__context">
          <div className="workbench-create__context-head">
            <span>目标用例集</span>
            <strong>{spaceName}</strong>
          </div>
          <label className="workbench-select">
            <span>用例集合</span>
            <div>
              <select
                value={selectedCollection?.id ?? ""}
                onChange={(event) => onSelectCollection(event.target.value)}
              >
                {collections.map((collection) => (
                  <option key={collection.id} value={collection.id}>
                    {collection.name}
                  </option>
                ))}
              </select>
              <ChevronDown size={15} />
            </div>
          </label>
          <div className="workbench-context-card">
            <ClipboardList size={18} />
            <div>
              <strong>{selectedCollection?.name ?? "请选择用例集合"}</strong>
              <p>{selectedCollection?.description || "候选用例确认后将保存到这里"}</p>
              <span>{loading ? "正在读取…" : `${cases.length} 条正式用例`}</span>
            </div>
          </div>
          <div className="workbench-create__guardrail">
            <CheckCircle2 size={17} />
            <div>
              <strong>生成与正式资产分离</strong>
              <p>聊天输出默认为候选内容；只有主动确认后才会创建正式用例修订。</p>
            </div>
          </div>
          {!!cases.length && (
            <button
              type="button"
              className="workbench-secondary-button"
              onClick={openExistingCollection}
            >
              打开现有用例工作台
            </button>
          )}
        </aside>
      </div>
    );
  }

  return (
    <div
      className="case-workbench"
      style={
        {
          "--workbench-chat-width": `${chatWidth}px`,
          "--workbench-inspector-width": `${inspectorWidth}px`,
        } as CSSProperties
      }
    >
      <aside className="workbench-chat">
        <header>
          <div>
            <span className="workbench-kicker">
              <Bot size={14} /> AI TEST DESIGNER
            </span>
            <strong>与 CasePilot 对话</strong>
          </div>
          <button
            type="button"
            onClick={resetConversation}
            aria-label="新建对话"
            title="新建对话"
          >
            <MessageSquarePlus size={18} />
          </button>
        </header>

        <div className="workbench-chat__context">
          <span>当前上下文</span>
          <strong>{selectedCollection?.name ?? "未选择用例集"}</strong>
          <small>{cases.length} 条正式用例 · {files.length} 个需求文件</small>
        </div>

        <div className="workbench-chat__messages">
          {!messages.length && (
            <div className="workbench-chat__welcome">
              <WandSparkles size={20} />
              <strong>继续补充测试目标</strong>
              <p>你可以要求补充边界条件、改写步骤，或检查覆盖缺口。</p>
            </div>
          )}
          {messages.map((message) => (
            <article
              key={message.id}
              className={`workbench-message workbench-message--${message.role}`}
            >
              <span>{message.role === "assistant" ? <Bot size={14} /> : "你"}</span>
              <p>{message.content}</p>
            </article>
          ))}
          {isGenerating && (
            <section className="workbench-generation">
              <div>
                <LoaderCircle className="auth-spinner" size={17} />
                <strong>正在设计测试场景</strong>
                <span>
                  {Math.round(((activeStage + 0.5) / generationStages.length) * 100)}%
                </span>
              </div>
              <div className="workbench-generation__bar">
                <i
                  style={{
                    width: `${Math.min(
                      100,
                      ((activeStage + 0.5) / generationStages.length) * 100,
                    )}%`,
                  }}
                />
              </div>
              <ol>
                {generationStages.map((stage, index) => (
                  <li
                    key={stage}
                    className={
                      index < activeStage
                        ? "is-complete"
                        : index === activeStage
                          ? "is-active"
                          : ""
                    }
                  >
                    {index < activeStage ? <Check size={13} /> : <span>{index + 1}</span>}
                    {stage}
                  </li>
                ))}
              </ol>
            </section>
          )}
          {!!generatedCases.length && !isGenerating && (
            <section className="workbench-risk">
              <span><CircleAlert size={15} /> 覆盖提醒</span>
              <strong>识别到 2 项建议确认</strong>
              <p>异常恢复后的数据一致性，以及重复操作的幂等规则需要产品确认。</p>
            </section>
          )}
          {savedNotice && (
            <div className="workbench-saved-notice">
              <CheckCircle2 size={15} /> {savedNotice}
            </div>
          )}
        </div>

        <form className="workbench-chat__composer" onSubmit={submitPrompt}>
          <textarea
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                submitPrompt();
              }
            }}
            placeholder="描述测试目标，或继续追问当前需求…"
          />
          <footer>
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              aria-label="添加需求文件"
            >
              <Paperclip size={16} />
            </button>
            <label className="workbench-model-select workbench-model-select--compact">
              <Sparkles size={13} />
              <span className="sr-only">生成模型</span>
              <select
                aria-label="生成模型"
                value={modelId}
                onChange={(event) => setModelId(event.target.value)}
              >
                {modelOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <ChevronDown size={12} />
            </label>
            <button
              type="submit"
              className="is-primary"
              disabled={!prompt.trim() || isGenerating}
              aria-label="发送"
            >
              <ArrowUp size={16} />
            </button>
          </footer>
          <input
            ref={fileInputRef}
            hidden
            multiple
            type="file"
            accept=".doc,.docx,.pdf,.xls,.xlsx,.csv,.txt,.md"
            onChange={addFiles}
          />
        </form>
      </aside>

      <div
        className="workbench-resizer workbench-resizer--chat"
        role="separator"
        aria-label="调整对话区域宽度"
        aria-orientation="vertical"
        aria-valuemin={280}
        aria-valuemax={520}
        aria-valuenow={chatWidth}
        tabIndex={0}
        onPointerDown={(event) => resizePanel("chat", event)}
        onKeyDown={(event) => {
          if (event.key.startsWith("Arrow")) event.preventDefault();
          resizeWithKeyboard("chat", event.key);
        }}
      >
        <i />
      </div>

      <section className="workbench-canvas">
        <header className="workbench-canvas__header">
          <div>
            <span>用例集合 / {selectedCollection?.name ?? "未选择"}</span>
            <h1>{selectedCollection?.name ?? "AI 用例工作台"}</h1>
            <p>
              {generatedCases.length
                ? `${generatedCases.length} 条 AI 候选用例，确认后写入正式资产`
                : `${cases.length} 条正式用例，按模块与共同前置条件组织`}
            </p>
          </div>
          <div>
            <span className="workbench-model">
              <Sparkles size={14} /> {selectedModelLabel}
            </span>
            {generatedCases.length ? (
              <>
                <div className="workbench-candidate-bulk">
                  <span>
                    已选 {selectedCandidateCount} / {generatedCases.length}
                  </span>
                  <button
                    type="button"
                    onClick={() =>
                      setSelectedCandidateIds(
                        generatedCases.map((item) => item.id),
                      )
                    }
                  >
                    全选
                  </button>
                  <button
                    type="button"
                    onClick={() => setSelectedCandidateIds([])}
                  >
                    清空
                  </button>
                </div>
                <button
                  type="button"
                  className="workbench-primary-button"
                  disabled={saving || !selectedCandidateCount}
                  onClick={() => void saveCandidates()}
                >
                  {saving ? (
                    <LoaderCircle className="auth-spinner" size={16} />
                  ) : (
                    <Save size={16} />
                  )}
                  写入 {selectedCandidateCount} 条
                </button>
              </>
            ) : (
              <button
                type="button"
                className="workbench-primary-button"
                onClick={() => onCreateCase()}
              >
                <Plus size={16} /> 新建用例
              </button>
            )}
          </div>
        </header>

        <div className="workbench-canvas__tabs">
          <div>
            <button
              type="button"
              className={viewMode === "mind-map" ? "is-active" : ""}
              onClick={() => setViewMode("mind-map")}
            >
              <GitFork size={15} /> 用例脑图
            </button>
            <button
              type="button"
              className={viewMode === "list" ? "is-active" : ""}
              onClick={() => setViewMode("list")}
            >
              <List size={15} /> 用例列表
            </button>
          </div>
          <span>{visibleCases.length} 条用例 · {modules} 个模块</span>
        </div>

        <div className="workbench-canvas__body">
          {loading && !visibleCases.length ? (
            <div className="workbench-empty">
              <LoaderCircle className="auth-spinner" size={22} /> 正在加载用例…
            </div>
          ) : viewMode === "mind-map" && selectedCollection ? (
            <CaseMindMap
              collection={selectedCollection}
              cases={visibleCases}
              selectedCaseId={selectedCase?.id ?? ""}
              onSelectCase={(caseId) => {
                setSelectedCaseId(caseId);
                if (!caseId.startsWith("candidate-")) onSelectCase(caseId);
              }}
              onCreateCase={onCreateCase}
              onEditCase={(testCase) => {
                if (testCase.id.startsWith("candidate-")) {
                  editCandidate(testCase);
                } else {
                  onEditCase(testCase);
                }
              }}
            />
          ) : (
            <div className="workbench-case-list">
              {visibleCases.map((testCase) => {
                const candidate = testCase.id.startsWith("candidate-");
                const included = selectedCandidateIds.includes(testCase.id);
                return (
                  <div
                    className={`workbench-case-list__row${selectedCase?.id === testCase.id ? " is-active" : ""}${candidate && !included ? " is-excluded" : ""}`}
                    key={testCase.id}
                  >
                    <button
                      type="button"
                      className="workbench-case-list__main"
                      onClick={() => {
                        setSelectedCaseId(testCase.id);
                        if (!candidate) onSelectCase(testCase.id);
                      }}
                    >
                      <span>
                        <code>{testCase.case_key}</code>
                        <strong>{testCase.title}</strong>
                      </span>
                      <span>{testCase.module || "未分类"}</span>
                      <span className={`priority-badge priority-badge--${testCase.priority.toLowerCase()}`}>
                        {testCase.priority}
                      </span>
                      <span>{candidate ? "候选" : `V${testCase.revision_number}`}</span>
                    </button>
                    {candidate && (
                      <div className="workbench-case-list__actions">
                        <button
                          type="button"
                          aria-pressed={included}
                          onClick={() => toggleCandidate(testCase.id)}
                        >
                          {included ? <Check size={13} /> : <X size={13} />}
                          {included ? "已纳入" : "已排除"}
                        </button>
                        <button
                          type="button"
                          onClick={() => editCandidate(testCase)}
                        >
                          <Pencil size={13} /> 编辑
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </section>

      <div
        className="workbench-resizer workbench-resizer--inspector"
        role="separator"
        aria-label="调整详情区域宽度"
        aria-orientation="vertical"
        aria-valuemin={300}
        aria-valuemax={520}
        aria-valuenow={inspectorWidth}
        tabIndex={0}
        onPointerDown={(event) => resizePanel("inspector", event)}
        onKeyDown={(event) => {
          if (event.key.startsWith("Arrow")) event.preventDefault();
          resizeWithKeyboard("inspector", event.key);
        }}
      >
        <i />
      </div>

      <aside className="workbench-inspector">
        {selectedCase ? (
          <>
            <header>
              <div>
                <span>CASE DETAILS</span>
                <code>{selectedCase.case_key} · V{selectedCase.revision_number}</code>
              </div>
              <button
                type="button"
                onClick={() =>
                  selectedCase.id.startsWith("candidate-")
                    ? editCandidate(selectedCase)
                    : onEditCase(selectedCase)
                }
                aria-label={
                  selectedCase.id.startsWith("candidate-")
                    ? "编辑当前候选用例"
                    : "编辑当前用例"
                }
              >
                编辑
              </button>
            </header>
            <div className="workbench-inspector__scroll">
              {selectedCase.id.startsWith("candidate-") && (
                <div className="workbench-candidate-review">
                  <div className="workbench-candidate-label">
                    <Sparkles size={14} /> AI 候选 · 尚未写入正式用例集
                  </div>
                  <button
                    type="button"
                    aria-pressed={selectedCandidateIds.includes(selectedCase.id)}
                    onClick={() => toggleCandidate(selectedCase.id)}
                  >
                    {selectedCandidateIds.includes(selectedCase.id)
                      ? "已纳入本次写入"
                      : "已排除，点击重新纳入"}
                  </button>
                </div>
              )}
              <h2>{selectedCase.title}</h2>
              <div className="workbench-inspector__meta">
                <span>{selectedCase.module || "未分类"}</span>
                <span>{selectedCase.case_type}</span>
                <span>{selectedCase.priority}</span>
              </div>
              <section>
                <h3>前置条件</h3>
                <ol>
                  {selectedCase.preconditions.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ol>
              </section>
              <section>
                <h3>执行步骤与校验点</h3>
                <div className="workbench-inspector__steps">
                  {selectedCase.steps.map((step, index) => (
                    <article key={step.id}>
                      <span>{index + 1}</span>
                      <div>
                        <strong>{step.action}</strong>
                        <p>{step.expected}</p>
                      </div>
                    </article>
                  ))}
                </div>
              </section>
              <section className="workbench-inspector__source">
                <Tags size={14} /> 来源：{selectedCase.source || "未记录"}
              </section>
              <section className="workbench-rewrite">
                <span><WandSparkles size={14} /> AI 改写建议</span>
                <textarea
                  value={rewritePrompt}
                  onChange={(event) => setRewritePrompt(event.target.value)}
                  placeholder="例如：补充弱网恢复后的数据一致性校验"
                />
                <button
                  type="button"
                  disabled={!rewritePrompt.trim()}
                  onClick={runRewrite}
                >
                  生成改写建议
                </button>
              </section>
            </div>
          </>
        ) : (
          <div className="workbench-empty">
            <ClipboardList size={24} />
            <strong>选择一条用例查看详情</strong>
          </div>
        )}
      </aside>
      {candidateEditorIndex !== null && generatedCases[candidateEditorIndex] && (
        <CaseEditorDialog
          key={`candidate-editor-${candidateEditorIndex}`}
          testCase={generatedCases[candidateEditorIndex]}
          saving={false}
          onClose={() => setCandidateEditorIndex(null)}
          onSave={saveCandidateEdit}
        />
      )}
    </div>
  );
}
