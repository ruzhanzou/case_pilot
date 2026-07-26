"use client";

import {
  PromptInput,
  PromptInputActionAddAttachments,
  PromptInputActionMenu,
  PromptInputActionMenuContent,
  PromptInputActionMenuTrigger,
  PromptInputBody,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools,
  type PromptInputMessage,
} from "@/components/ai-elements/prompt-input";
import { Conversation, ConversationContent, ConversationScrollButton } from "@/components/ai-elements/conversation";
import { Message, MessageContent, MessageResponse } from "@/components/ai-elements/message";
import { AllCases } from "@/components/all-cases";
import { AppNavigation, type ProductPage } from "@/components/app-navigation";
import {
  CaseCollections,
  initialCaseCollections,
  type CaseCollection,
} from "@/components/case-collections";
import { CaseInspector } from "@/components/case-inspector";
import { CaseStatusBadge } from "@/components/case-status";
import { GlobalChatHome, type RecentCollection } from "@/components/global-chat-home";
import { MindMap } from "@/components/mind-map";
import { ModelSelector, type ModelId } from "@/components/model-selector";
import { QualityInsights } from "@/components/quality-insights";
import { SpaceManager, type Space } from "@/components/space-manager";
import { TestDocument } from "@/components/test-document";
import { TestExecution } from "@/components/test-execution";
import {
  startMockGeneration,
  watchMockGeneration,
  type Account,
  type GenerationCompleted,
} from "@/lib/casepilot-api";
import {
  analysisMarkdown,
  generationStages,
  testCases as exampleTestCases,
  type TestCase,
} from "@/lib/mock-data";
import { AnimatePresence, motion } from "motion/react";
import {
  ArrowUpRight,
  Bell,
  Bot,
  BrainCircuit,
  Check,
  ChevronDown,
  CircleDot,
  FileText,
  LayoutList,
  Link2,
  Map,
  Menu,
  MoreHorizontal,
  PanelLeftClose,
  PanelRightOpen,
  Plus,
  Search,
  ShieldCheck,
  Sparkles,
  UserRoundCheck,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent } from "react";

type WorkspaceView = "map" | "list" | "document";
type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  files?: string[];
};

const assistantGreeting: ChatMessage = {
  id: "assistant-welcome",
  role: "assistant",
  content: "当前对话只作用于这个用例集。你可以继续上传材料，或要求我补充风险、展开分支和改写用例。",
};

const exampleMessages: ChatMessage[] = [
  assistantGreeting,
  {
    id: "example-user",
    role: "user",
    content: "分析这份支付结算需求，重点覆盖金额边界、优惠叠加和支付回调幂等。",
    files: ["支付结算需求说明_v1.8.docx"],
  },
  { id: "example-assistant", role: "assistant", content: analysisMarkdown },
];

const workspaceTabs: { id: WorkspaceView; label: string; icon: typeof Map }[] = [
  { id: "map", label: "用例脑图", icon: Map },
  { id: "list", label: "用例列表", icon: LayoutList },
  { id: "document", label: "测试说明", icon: FileText },
];

const initialSpaces: Space[] = [
  { id: "space-commerce", name: "电商质量空间", description: "Web 商城、结算支付与会员体系", members: 12, collections: 6 },
  { id: "space-mobile", name: "移动端质量空间", description: "iOS、Android 与小程序测试资产", members: 8, collections: 4 },
  { id: "space-platform", name: "开放平台空间", description: "API、Webhook 与开发者工具", members: 5, collections: 3 },
];

const initialRecentCollections: RecentCollection[] = [
  { id: "col-payment", name: "支付结算回归集", description: "结算、优惠、支付回调与退款链路", count: 24, updated: "刚刚" },
  { id: "col-smoke", name: "商城 P0 冒烟用例", description: "生产发布前执行的关键路径", count: 36, updated: "昨天" },
  { id: "col-history", name: "历史功能用例 2024", description: "从历史测试资产 Excel 导入", count: 862, updated: "3 天前" },
];

function formatGenerationResult(result: GenerationCompleted): string {
  const riskLines = result.risks
    .map((risk) => `- **${risk.id} · ${risk.severity.toUpperCase()}**：${risk.title}（${risk.source}）`)
    .join("\n");
  const caseSections = result.test_cases
    .map((testCase) => {
      const preconditions = testCase.preconditions.map((item) => `  - ${item}`).join("\n");
      const steps = testCase.steps
        .map((step, index) => `  ${index + 1}. **执行**：${step.action}\n     **校验**：${step.expected}`)
        .join("\n");
      return `### ${testCase.id} · ${testCase.title}\n\n- 状态：Pending\n- 前置条件：\n${preconditions}\n- 执行步骤与校验点：\n${steps}`;
    })
    .join("\n\n");
  return `已完成需求分析，并生成 ${result.test_cases.length} 条结构化候选用例。\n\n## 风险识别\n\n${riskLines}\n\n## 生成用例\n\n${caseSections}`;
}

function generatedCasesToWorkspace(
  result: GenerationCompleted,
  collectionName: string,
): TestCase[] {
  const modules = ["核心流程", "异常与边界", "风险控制"];
  const types: TestCase["type"][] = ["功能", "异常", "边界", "安全"];
  return result.test_cases.map((testCase, index) => ({
    id: testCase.id,
    title: testCase.title,
    module: modules[index % modules.length],
    priority: index === 0 ? "P0" : index < 3 ? "P1" : "P2",
    type: types[index % types.length],
    status: "Pending",
    tags: [modules[index % modules.length], types[index % types.length]],
    automated: index === 0,
    source: `${collectionName} / AI 生成批次`,
    preconditions: testCase.preconditions,
    steps: testCase.steps.map((step, stepIndex) => ({
      id: `${testCase.id}-step-${stepIndex + 1}`,
      action: step.action,
      expected: step.expected,
    })),
  }));
}

function deriveCollectionName(message: PromptInputMessage): string {
  const firstFile = message.files[0]?.filename?.replace(/\.[^.]+$/, "").trim();
  if (firstFile) return firstFile.slice(0, 28);
  const concisePrompt = message.text
    .replace(/[，。！？,.!?]/g, " ")
    .trim()
    .split(/\s+/)
    .slice(0, 4)
    .join(" ");
  return `${concisePrompt.slice(0, 20) || "新测试设计"}用例集`;
}

function CaseTable({
  testCases,
  onSelect,
}: {
  testCases: TestCase[];
  onSelect: (id: string) => void;
}) {
  return (
    <div className="case-table-wrap">
      <div className="table-filterbar">
        <div className="filter-search"><Search size={17} /><span>搜索用例名称、编号或标签</span></div>
        <button type="button">全部模块<ChevronDown size={15} /></button>
        <button type="button">全部状态<ChevronDown size={15} /></button>
        <button className="button-primary" type="button"><Plus size={16} />新建用例</button>
      </div>
      <table className="case-table">
        <thead><tr><th>用例</th><th>模块</th><th>类型</th><th>优先级</th><th>状态</th><th>标签</th><th>自动化</th><th>来源</th><th /></tr></thead>
        <tbody>
          {testCases.map((item) => (
            <tr key={item.id} onClick={() => onSelect(item.id)}>
              <td><span>{item.id}</span><strong>{item.title}</strong></td>
              <td>{item.module}</td>
              <td>{item.type}</td>
              <td><b className={`priority priority--${item.priority.toLowerCase()}`}>{item.priority}</b></td>
              <td><CaseStatusBadge status={item.status} /></td>
              <td><div className="case-tag-list">{item.tags.map((tag) => <span className="case-tag" key={tag}>{tag}</span>)}</div></td>
              <td>{item.automated ? <span className="automation-badge">已绑定</span> : <span className="automation-empty">未绑定</span>}</td>
              <td><Link2 size={14} />{item.source.split(" /")[0]}</td>
              <td><MoreHorizontal size={18} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function GenerationProgress({ stage }: { stage: number }) {
  return (
    <motion.div className="generation-progress" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
      <div className="generation-progress__head"><BrainCircuit size={18} /><strong>正在构建测试设计</strong><span>{Math.min(100, (stage + 1) * 20)}%</span></div>
      <div className="generation-track"><motion.span animate={{ width: `${Math.min(100, (stage + 1) * 20)}%` }} /></div>
      <div className="generation-stages">
        {generationStages.map((item, index) => (
          <div className={index < stage ? "is-done" : index === stage ? "is-active" : ""} key={item.label}>
            <span>{index < stage ? <Check size={12} /> : index + 1}</span>
            <p><strong>{item.label}</strong><small>{item.detail}</small></p>
          </div>
        ))}
      </div>
    </motion.div>
  );
}

export function PrototypeApp({
  account,
  onLogout,
}: {
  account: Account;
  onLogout: () => void;
}) {
  const [page, setPage] = useState<ProductPage>("home");
  const [activeView, setActiveView] = useState<WorkspaceView>("map");
  const [modelId, setModelId] = useState<ModelId>("auto");
  const [currentCollectionName, setCurrentCollectionName] = useState("支付结算回归集");
  const [currentCollectionId, setCurrentCollectionId] = useState("col-payment");
  const [currentCollectionSummary, setCurrentCollectionSummary] = useState("覆盖结算、优惠计算、支付回调与退款链路");
  const [pendingCollectionName, setPendingCollectionName] = useState<string>();
  const [workspaceCases, setWorkspaceCases] = useState<TestCase[]>(exampleTestCases);
  const [selectedCaseId, setSelectedCaseId] = useState(exampleTestCases[0].id);
  const [messages, setMessages] = useState<ChatMessage[]>(exampleMessages);
  const [recentCollections, setRecentCollections] = useState(initialRecentCollections);
  const [caseCollections, setCaseCollections] = useState<CaseCollection[]>(initialCaseCollections);
  const [generating, setGenerating] = useState(false);
  const [stage, setStage] = useState(0);
  const [chatWidth, setChatWidth] = useState(390);
  const [mapLayoutRevision, setMapLayoutRevision] = useState(0);
  const [inspectorCollapsed, setInspectorCollapsed] = useState(false);
  const [accountPanel, setAccountPanel] = useState(false);
  const [spacePanel, setSpacePanel] = useState(false);
  const [spaces, setSpaces] = useState<Space[]>(() =>
    account.spaces.length > 0
      ? account.spaces.map((space) => ({
          id: space.id,
          name: space.name,
          description: space.description,
          members: 1,
          collections: 1,
        }))
      : initialSpaces,
  );
  const [activeSpaceId, setActiveSpaceId] = useState(account.spaces[0]?.id ?? initialSpaces[0].id);
  const generationRun = useRef(0);
  const appShellRef = useRef<HTMLElement>(null);
  const chatResize = useRef<{ startX: number; startWidth: number } | null>(null);
  const pendingChatWidth = useRef(chatWidth);
  const resizeFrame = useRef<number | null>(null);
  const selectedCase = useMemo(
    () => workspaceCases.find((item) => item.id === selectedCaseId) ?? workspaceCases[0],
    [selectedCaseId, workspaceCases],
  );
  const activeSpace = spaces.find((space) => space.id === activeSpaceId) ?? spaces[0];

  useEffect(() => {
    const suppressResizeObserverWarning = (event: ErrorEvent) => {
      if (
        event.message.includes("ResizeObserver loop completed with undelivered notifications") ||
        event.message.includes("ResizeObserver loop limit exceeded")
      ) {
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    };
    window.addEventListener("error", suppressResizeObserverWarning, true);
    return () => {
      window.removeEventListener("error", suppressResizeObserverWarning, true);
      if (resizeFrame.current !== null) window.cancelAnimationFrame(resizeFrame.current);
    };
  }, []);

  const rememberCollection = (collection: RecentCollection) => {
    setRecentCollections((current) => [
      collection,
      ...current.filter((item) => item.id !== collection.id),
    ].slice(0, 3));
    setCaseCollections((current) => {
      if (current.some((item) => item.id === collection.id)) {
        return current.map((item) =>
          item.id === collection.id
            ? { ...item, count: collection.count, updated: collection.updated }
            : item,
        );
      }
      return [
        {
          id: collection.id,
          name: collection.name,
          description: collection.description,
          count: collection.count,
          source: "AI 生成",
          updated: collection.updated,
        },
        ...current,
      ];
    });
  };

  const openCollection = (collection: RecentCollection | CaseCollection) => {
    const isBlankCollection = collection.count === 0;
    setCurrentCollectionId(collection.id);
    setCurrentCollectionName(collection.name);
    setCurrentCollectionSummary(collection.description);
    setWorkspaceCases(isBlankCollection ? [] : exampleTestCases);
    setSelectedCaseId(isBlankCollection ? "" : exampleTestCases[0].id);
    setMessages(isBlankCollection ? [assistantGreeting] : exampleMessages);
    setPendingCollectionName(undefined);
    setInspectorCollapsed(false);
    setActiveView("map");
    setPage("studio");
    rememberCollection({
      id: collection.id,
      name: collection.name,
      description: collection.description,
      count: collection.count,
      updated: "刚刚",
    });
  };

  const loadCollectionForExecution = (collection: RecentCollection | CaseCollection) => {
    const isBlankCollection = collection.count === 0;
    setCurrentCollectionId(collection.id);
    setCurrentCollectionName(collection.name);
    setCurrentCollectionSummary(collection.description);
    setWorkspaceCases(isBlankCollection ? [] : exampleTestCases);
    setSelectedCaseId(isBlankCollection ? "" : exampleTestCases[0].id);
    setPage("execution");
  };

  const runGeneration = async (message: PromptInputMessage, fromHome = false) => {
    if ((!message.text.trim() && message.files.length === 0) || generating) return;

    const collectionName = fromHome
      ? pendingCollectionName && pendingCollectionName !== "新用例集"
        ? pendingCollectionName
        : deriveCollectionName(message)
      : currentCollectionName;
    const fileNames = message.files.map((file) => file.filename || "需求附件");
    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: message.text || "请分析附件并生成测试用例。",
      files: fileNames,
    };
    const run = ++generationRun.current;

    if (fromHome) {
      const generatedCollectionId = crypto.randomUUID();
      setCurrentCollectionId(generatedCollectionId);
      setCurrentCollectionName(collectionName);
      setCurrentCollectionSummary(message.text.slice(0, 72) || "根据上传材料生成的测试范围、风险与候选用例");
      setMessages([assistantGreeting, userMessage]);
      setPendingCollectionName(undefined);
      setPage("studio");
      rememberCollection({
        id: generatedCollectionId,
        name: collectionName,
        description: message.text.slice(0, 48) || "根据上传材料创建的 AI 测试设计",
        count: 0,
        updated: "刚刚",
      });
    } else {
      setMessages((current) => [...current, userMessage]);
    }

    setGenerating(true);
    setStage(0);
    setActiveView("map");

    const finishGeneration = (result?: GenerationCompleted) => {
      if (generationRun.current !== run) return;
      if (result) {
        const generatedCases = generatedCasesToWorkspace(result, collectionName);
        setWorkspaceCases(generatedCases);
        setSelectedCaseId(generatedCases[0]?.id ?? "");
        setCaseCollections((current) => current.map((collection) =>
          collection.name === collectionName
            ? { ...collection, count: generatedCases.length, updated: "刚刚" }
            : collection,
        ));
        setRecentCollections((current) => current.map((collection) =>
          collection.name === collectionName
            ? { ...collection, count: generatedCases.length, updated: "刚刚" }
            : collection,
        ));
      }
      setGenerating(false);
      setStage(0);
      setMessages((current) => [...current, {
        id: crypto.randomUUID(),
        role: "assistant",
        content: result
          ? `${formatGenerationResult(result)}\n\n这些用例均为 Pending，需人工评审后生效。`
          : `${analysisMarkdown}\n\n当前使用浏览器回退 Mock；本地 Worker 恢复后会自动使用队列生成。`,
      }]);
    };

    const runFallback = async () => {
      for (let next = 0; next < generationStages.length; next += 1) {
        if (generationRun.current !== run) return;
        setStage(next);
        await new Promise((resolve) => window.setTimeout(resolve, 620));
      }
      finishGeneration();
    };

    try {
      const job = await startMockGeneration({
        prompt: message.text || "请分析附件并生成测试用例。",
        fileNames,
        spaceId: activeSpaceId,
        modelId,
      });
      const result = await watchMockGeneration(job.id, (progress) => {
        if (generationRun.current !== run) return;
        setStage(Math.min(generationStages.length - 1, Math.max(0, Math.ceil(progress / 20) - 1)));
      });
      finishGeneration(result);
    } catch {
      await runFallback();
    }
  };

  const chooseCase = (id: string) => {
    setSelectedCaseId(id);
    setInspectorCollapsed(false);
    if (activeView === "list") setActiveView("map");
  };

  const resizeChatWithKeyboard = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    setChatWidth((current) => {
      const next = Math.min(520, Math.max(320, current + (event.key === "ArrowRight" ? 16 : -16)));
      pendingChatWidth.current = next;
      return next;
    });
  };

  const startChatResize = (event: PointerEvent<HTMLButtonElement>) => {
    chatResize.current = { startX: event.clientX, startWidth: chatWidth };
    pendingChatWidth.current = chatWidth;
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const continueChatResize = (event: PointerEvent<HTMLButtonElement>) => {
    if (!chatResize.current) return;
    const nextWidth = chatResize.current.startWidth + event.clientX - chatResize.current.startX;
    pendingChatWidth.current = Math.min(520, Math.max(320, nextWidth));
    if (resizeFrame.current !== null) return;
    resizeFrame.current = window.requestAnimationFrame(() => {
      appShellRef.current?.style.setProperty("--chat-width", `${pendingChatWidth.current}px`);
      resizeFrame.current = null;
    });
  };

  const finishChatResize = (event: PointerEvent<HTMLButtonElement>) => {
    if (resizeFrame.current !== null) {
      window.cancelAnimationFrame(resizeFrame.current);
      resizeFrame.current = null;
    }
    appShellRef.current?.style.setProperty("--chat-width", `${pendingChatWidth.current}px`);
    setChatWidth(pendingChatWidth.current);
    setMapLayoutRevision((current) => current + 1);
    chatResize.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  const navigate = (nextPage: ProductPage) => {
    if (nextPage === "home") setPendingCollectionName(undefined);
    setPage(nextPage);
  };

  const sharedOverlays = (
    <>
      <AnimatePresence>
        {spacePanel && (
          <SpaceManager
            spaces={spaces}
            activeSpaceId={activeSpaceId}
            onSelect={setActiveSpaceId}
            onChange={setSpaces}
            onClose={() => setSpacePanel(false)}
          />
        )}
      </AnimatePresence>

      <AnimatePresence>
        {accountPanel && (
          <motion.div className="account-overlay" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={(event) => event.target === event.currentTarget && setAccountPanel(false)}>
            <motion.section className="account-panel" initial={{ opacity: 0, scale: .97, y: 12 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: .98, y: 8 }} role="dialog" aria-modal="true" aria-labelledby="account-title">
              <header>
                <div><span className="eyebrow">LOCAL ACCOUNT</span><h2 id="account-title">账号与本地会话</h2></div>
                <button type="button" onClick={() => setAccountPanel(false)} aria-label="关闭账号面板">×</button>
              </header>
              <div className="account-intro">
                <UserRoundCheck size={20} />
                <div><strong>已登录本地账号</strong><p>账号、空间和生成记录保存在本机 PostgreSQL 中。</p></div>
              </div>
              <div className="account-method account-method--custom">
                <div className="account-provider-mark">{account.display_name.slice(0, 1)}</div>
                <h3>{account.display_name}</h3>
                <p>{account.email}</p>
                <div className="account-scope">{spaces.length} 个本地空间 · 当前角色 {account.spaces[0]?.role ?? "owner"}</div>
                <button className="account-primary" type="button" onClick={onLogout}>退出登录<ArrowUpRight size={16} /></button>
              </div>
              <footer>会话使用 HttpOnly Cookie；退出后本地业务数据不会被删除。</footer>
            </motion.section>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );

  if (page === "home") {
    return (
      <>
        <main className="app-page-shell">
          <AppNavigation activePage={page} accountName={account.display_name} onNavigate={navigate} onOpenAccount={() => setAccountPanel(true)} />
          <GlobalChatHome
            accountName={account.display_name}
            spaceName={activeSpace?.name ?? "默认空间"}
            pendingCollectionName={pendingCollectionName}
            recentCollections={recentCollections}
            onOpenSpace={() => setSpacePanel(true)}
            onOpenAccount={() => setAccountPanel(true)}
            onOpenCollections={() => setPage("collections")}
            onOpenCollection={openCollection}
            onSubmit={(message) => runGeneration(message, true)}
            modelId={modelId}
            onModelChange={setModelId}
          />
        </main>
        {sharedOverlays}
      </>
    );
  }

  if (page === "collections") {
    return (
      <>
        <main className="app-page-shell">
          <AppNavigation activePage={page} accountName={account.display_name} onNavigate={navigate} onOpenAccount={() => setAccountPanel(true)} />
          <section className="collections-page">
            <header className="collections-page__header">
              <button type="button" onClick={() => setSpacePanel(true)}>空间 / {activeSpace?.name}<ChevronDown size={15} /></button>
              <div><button type="button" onClick={() => setAccountPanel(true)}><UserRoundCheck size={17} />{account.display_name}</button></div>
            </header>
            <CaseCollections
              collections={caseCollections}
              setCollections={setCaseCollections}
              onBack={() => setPage("home")}
              onCreateWithAI={() => {
                setPendingCollectionName("新用例集");
                setPage("home");
              }}
              onOpenCollection={openCollection}
              onExecuteCollection={loadCollectionForExecution}
            />
          </section>
        </main>
        {sharedOverlays}
      </>
    );
  }

  if (page === "cases" || page === "execution" || page === "insights") {
    return (
      <>
        <main className="app-page-shell">
          <AppNavigation activePage={page} accountName={account.display_name} onNavigate={navigate} onOpenAccount={() => setAccountPanel(true)} />
          <section className="collections-page">
            <header className="collections-page__header">
              <button type="button" onClick={() => setSpacePanel(true)}>空间 / {activeSpace?.name}<ChevronDown size={15} /></button>
              <div><button type="button" onClick={() => setAccountPanel(true)}><UserRoundCheck size={17} />{account.display_name}</button></div>
            </header>
            {page === "cases" ? (
              <AllCases
                testCases={workspaceCases}
                onOpenCase={(id) => {
                  setSelectedCaseId(id);
                  setInspectorCollapsed(false);
                  setActiveView("map");
                  setPage("studio");
                }}
              />
            ) : page === "execution" ? (
              <TestExecution
                key={currentCollectionId}
                collectionId={currentCollectionId}
                collectionName={currentCollectionName}
                collections={caseCollections}
                testCases={workspaceCases}
                onSelectCollection={(collectionId) => {
                  const collection = caseCollections.find((item) => item.id === collectionId);
                  if (collection) loadCollectionForExecution(collection);
                }}
              />
            ) : (
              <QualityInsights testCases={workspaceCases} />
            )}
          </section>
        </main>
        {sharedOverlays}
      </>
    );
  }

  return (
    <>
      <main
        ref={appShellRef}
        className={`app-shell ${inspectorCollapsed ? "is-inspector-collapsed" : ""}`}
        style={{ "--chat-width": `${chatWidth}px` } as CSSProperties}
      >
        <AppNavigation activePage={page} accountName={account.display_name} onNavigate={navigate} onOpenAccount={() => setAccountPanel(true)} />

        <aside className="assistant-panel">
          <header className="assistant-panel__header">
            <h1>CasePilot</h1>
            <button type="button" aria-label="返回全局对话" title="返回全局对话" onClick={() => setPage("home")}><PanelLeftClose size={19} /></button>
          </header>
          <button className="context-card" type="button" onClick={() => setPage("collections")}>
            <span className="context-card__icon"><FileText size={19} /></span>
            <span><strong>{currentCollectionName}</strong><small>{workspaceCases.length} 条用例 · 当前对话已绑定</small></span>
            <ChevronDown size={17} />
          </button>

          <Conversation className="chat-conversation">
            <ConversationContent className="chat-content">
              {messages.map((message) => (
                <Message from={message.role} key={message.id}>
                  <div className="message-meta">{message.role === "assistant" ? <><Bot size={15} />CasePilot</> : "你"}</div>
                  {message.files?.map((file) => <div className="chat-file" key={file}><FileText size={16} /><span>{file}</span><small>附件</small></div>)}
                  <MessageContent className={message.role === "assistant" ? "assistant-message" : "user-message"}>
                    {message.role === "assistant" ? <MessageResponse>{message.content}</MessageResponse> : <p>{message.content}</p>}
                  </MessageContent>
                </Message>
              ))}
              <AnimatePresence>{generating && <GenerationProgress stage={stage} />}</AnimatePresence>
            </ConversationContent>
            <ConversationScrollButton />
          </Conversation>

          <div className="prompt-wrap">
            <PromptInput
              accept=".doc,.docx,.pdf,.md,.txt,.xlsx,.xls,.csv,.png,.jpg,.jpeg"
              multiple
              maxFiles={20}
              maxFileSize={20 * 1024 * 1024}
              onSubmit={(message) => runGeneration(message)}
            >
              <PromptInputBody>
                <PromptInputTextarea placeholder="继续补充需求，或要求改写当前用例集…" disabled={generating} />
              </PromptInputBody>
              <PromptInputFooter>
                <PromptInputTools>
                  <PromptInputActionMenu>
                    <PromptInputActionMenuTrigger tooltip="添加需求材料" />
                    <PromptInputActionMenuContent><PromptInputActionAddAttachments label="上传 Word、PDF、Excel、图片或文本" /></PromptInputActionMenuContent>
                  </PromptInputActionMenu>
                  <ModelSelector
                    value={modelId}
                    onValueChange={setModelId}
                    placement="studio"
                  />
                </PromptInputTools>
                <PromptInputSubmit status={generating ? "submitted" : "ready"} />
              </PromptInputFooter>
            </PromptInput>
            <small>AI 内容先形成 Pending 候选，经人工确认后生效</small>
          </div>
          <button
            className="chat-resize-handle"
            type="button"
            aria-label="调整对话区域宽度"
            title="拖动调整对话区域宽度"
            onPointerDown={startChatResize}
            onPointerMove={continueChatResize}
            onPointerUp={finishChatResize}
            onPointerCancel={finishChatResize}
            onKeyDown={resizeChatWithKeyboard}
          />
        </aside>

        <section className={`workspace ${activeView === "document" ? "workspace--wide" : ""}`}>
          <header className="workspace-header">
            <div className="workspace-title">
              <button className="mobile-menu" type="button"><Menu size={20} /></button>
              <div>
                <button className="space-trigger" type="button" onClick={() => setSpacePanel(true)}>空间 / {activeSpace?.name}<ChevronDown size={14} /></button>
                <h2><span className="workspace-collection-name">{currentCollectionName}</span><i>V1</i></h2>
                <p className="workspace-collection-summary">{currentCollectionSummary}</p>
              </div>
            </div>
            <div className="workspace-actions">
              <button className="identity-chip" type="button" onClick={() => setAccountPanel(true)}><UserRoundCheck size={16} />{account.display_name}</button>
              <button type="button" aria-label="通知"><Bell size={19} /></button>
              <button type="button" onClick={() => setAccountPanel(true)}><ShieldCheck size={17} />发起评审</button>
            </div>
          </header>

          <div className="viewbar">
            <div className="view-tabs">
              {workspaceTabs.map((tab) => (
                <button className={activeView === tab.id ? "is-active" : ""} type="button" key={tab.id} onClick={() => setActiveView(tab.id)}>
                  <tab.icon size={17} />
                  {tab.label}
                  {tab.id === "list" && <span>{workspaceCases.length}</span>}
                </button>
              ))}
            </div>
            <div className="view-metrics">
              <span><CircleDot size={15} />{workspaceCases.length} 条用例</span>
              <span className="risk-text">{workspaceCases.filter((item) => item.status === "不通过" || item.status === "堵塞").length} 条需关注</span>
              {inspectorCollapsed && activeView !== "document" && (
                <button className="detail-toggle" type="button" onClick={() => { setInspectorCollapsed(false); setMapLayoutRevision((current) => current + 1); }}>
                  <PanelRightOpen size={16} />
                  用例详情
                </button>
              )}
            </div>
          </div>

          <div className={`workspace-content workspace-content--${activeView}`}>
            {activeView === "map" && workspaceCases.length > 0 && (
              <MindMap
                rootLabel={currentCollectionName}
                testCases={workspaceCases}
                selectedCaseId={selectedCaseId}
                layoutRevision={mapLayoutRevision}
                onSelectCase={(id) => {
                  setSelectedCaseId(id);
                  setInspectorCollapsed(false);
                }}
              />
            )}
            {activeView === "map" && workspaceCases.length === 0 && (
              <div className="studio-empty">
                <span><Sparkles size={25} /></span>
                <h3>这个用例集还是空的</h3>
                <p>在左侧对话框描述测试目标，或上传 Word、PDF、Excel、图片等材料。发送后会在这里生成用例脑图。</p>
                <button type="button" onClick={() => document.querySelector<HTMLTextAreaElement>(".prompt-wrap textarea")?.focus()}>
                  开始描述测试需求
                </button>
              </div>
            )}
            {activeView === "list" && <CaseTable testCases={workspaceCases} onSelect={chooseCase} />}
            {activeView === "document" && <TestDocument collectionName={currentCollectionName} testCases={workspaceCases} />}
          </div>

          {activeView === "map" && workspaceCases.length > 0 && (
            <div className="map-legend" aria-label="用例状态统计">
              <span><i className="legend-dot legend-dot--pending" />Pending {workspaceCases.filter((item) => item.status === "Pending").length}</span>
              <span><i className="legend-dot legend-dot--passed" />通过 {workspaceCases.filter((item) => item.status === "通过").length}</span>
              <span><i className="legend-dot legend-dot--failed" />不通过 {workspaceCases.filter((item) => item.status === "不通过").length}</span>
              <span><i className="legend-dot legend-dot--skipped" />跳过 {workspaceCases.filter((item) => item.status === "跳过").length}</span>
              <span><i className="legend-dot legend-dot--blocked" />堵塞 {workspaceCases.filter((item) => item.status === "堵塞").length}</span>
            </div>
          )}
        </section>

        {activeView !== "document" && selectedCase && !inspectorCollapsed && (
          <CaseInspector
            key={selectedCase.id}
            testCase={selectedCase}
            onRequestReview={() => setAccountPanel(true)}
            onCollapse={() => { setInspectorCollapsed(true); setMapLayoutRevision((current) => current + 1); }}
            onStatusChange={(status) => {
              setWorkspaceCases((current) =>
                current.map((testCase) =>
                  testCase.id === selectedCase.id
                    ? { ...testCase, status }
                    : testCase,
                ),
              );
            }}
          />
        )}
      </main>
      {sharedOverlays}
    </>
  );
}
