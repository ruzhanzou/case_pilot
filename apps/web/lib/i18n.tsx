"use client";

import { Languages } from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from "react";

export type Locale = "en" | "zh-CN";

const STORAGE_KEY = "casepilot.locale.v1";
const localeListeners = new Set<() => void>();
let inMemoryLocale: Locale = "en";

function readLocale(): Locale {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    inMemoryLocale = saved === "zh-CN" ? "zh-CN" : "en";
    return inMemoryLocale;
  } catch {
    return inMemoryLocale;
  }
}

function subscribeToLocale(listener: () => void) {
  localeListeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    localeListeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

const zhCN = {
  "language.label": "显示语言",
  "language.english": "English",
  "language.chinese": "中文",
  "auth.loading": "正在连接本地工作区…",
  "auth.eyebrow": "测试用例管理工作区",
  "auth.title.line1": "管理、评审并执行",
  "auth.title.line2": "结构化测试用例。",
  "auth.description": "登录后进入本地质量空间，维护用例集合、修订结构化用例，并记录每一次 QA 执行结果。",
  "auth.step.login": "登录本地账号",
  "auth.step.manage": "管理用例资产",
  "auth.step.execute": "执行并留痕",
  "auth.welcome": "欢迎回来",
  "auth.createAccount": "创建本地账号",
  "auth.loginHint": "登录后继续用例管理与执行",
  "auth.registerHint": "账号与数据仅保存在本地环境",
  "auth.displayName": "显示名称",
  "auth.email": "邮箱",
  "auth.password": "密码",
  "auth.loginSubmit": "登录并进入工作台",
  "auth.registerSubmit": "创建账号并进入",
  "auth.createPrompt": "第一次使用？创建本地账号",
  "auth.loginPrompt": "已有账号？返回登录",
  "auth.demo": "验收示例账号",
  "auth.error.invalid": "邮箱或密码不正确",
  "auth.error.exists": "该邮箱已注册，请直接登录",
  "auth.error.offline": "本地数据服务尚未就绪，请确认 PostgreSQL 和 API 已启动",
  "nav.main": "主导航",
  "nav.knowledge": "知识库",
  "nav.workbench": "AI 工作台",
  "nav.cases": "用例管理",
  "nav.execute": "执行用例",
  "nav.logout": "退出登录",
  "page.newConversation": "AI 新对话",
  "page.workbench": "AI 用例工作台",
  "page.knowledge": "空间知识库",
  "page.library": "用例资产管理",
  "page.execution": "QA 用例执行",
  "common.localSpace": "本地质量空间",
  "common.owner": "所有者",
  "common.member": "成员",
  "common.close": "关闭提示",
  "common.loadingWorkspace": "正在准备工作区…",
  "common.unsaved": "当前页面有尚未保存的修改，离开将丢失这些内容。是否继续？",
  "conversation.placeholder": "描述你的测试需求，或直接向 CasePilot 提问",
  "conversation.write": "写给 CasePilot",
  "conversation.addKnowledge": "添加知识资料",
  "conversation.uploadHint": "上传 PDF 或 TXT",
  "conversation.processing": "正在识别并处理…",
  "conversation.autoIntent": "自动识别意图",
  "conversation.model": "生成模型",
  "conversation.sending": "正在处理",
  "conversation.send": "发送",
  "conversation.knowledgeEnabled": "空间知识已启用",
  "conversation.history": "历史对话",
  "conversation.confirmCollection": "确认本对话维护的用例集合",
  "conversation.collectionLocked": "确认后本对话只能维护这一集合，不能在当前对话中切换。",
  "conversation.chooseCollection": "请选择集合",
  "conversation.newCollection": "或输入新集合名称",
  "conversation.enterWorkbench": "确认并进入工作台",
  "conversation.thinking": "正在思考…",
  "conversation.intentUnknown": "我还不能确定你的意图，请选择本次希望我执行的操作：",
  "conversation.crossCollection": "当前对话不会执行这条跨集合指令。",
  "conversation.openCollection": "新建对话并打开该集合",
  "conversation.cancel": "取消本次操作",
  "conversation.preparing": "正在识别意图并准备响应…",
  "conversation.hero": "今天想测试什么？",
  "conversation.heroHint": "直接描述需求或提问，CasePilot 会先理解你的意图。",
  "conversation.routing": "仅在确认生成、修改、删除或查询用例时进入绑定集合工作台",
  "conversation.examples": "你可以这样开始",
  "example.generate.title": "生成登录用例",
  "example.generate.description": "覆盖正常流程、频控、过期和弱网场景",
  "example.generate.prompt": "为手机号验证码登录生成测试用例，覆盖正常流程、频控、验证码过期和弱网场景。",
  "example.scope.title": "梳理测试范围",
  "example.scope.description": "先问答，不创建用例集合",
  "example.scope.prompt": "一个完整的支付退款功能通常需要覆盖哪些测试维度？",
  "example.modify.title": "局部修改用例",
  "example.modify.description": "进入工作台后选择节点再改写",
  "example.modify.prompt": "把选中的登录用例补充弱网恢复检查，并保持其他字段不变。",
  "intent.generate": "生成用例",
  "intent.modify": "修改用例",
  "intent.delete": "删除用例",
  "intent.query": "查询用例",
  "intent.knowledge": "知识问答",
  "intent.chat": "日常对话",
  "intent.clarify": "补充说明",
  "model.auto": "自动选择模型",
} as const;

export type TranslationKey = keyof typeof zhCN;

const en: Record<TranslationKey, string> = {
  "language.label": "Display language",
  "language.english": "English",
  "language.chinese": "中文",
  "auth.loading": "Connecting to your local workspace…",
  "auth.eyebrow": "TEST CASE MANAGEMENT WORKSPACE",
  "auth.title.line1": "Manage, review, and run",
  "auth.title.line2": "structured test cases.",
  "auth.description": "Sign in to manage case collections, revise structured test cases, and record every QA execution result.",
  "auth.step.login": "Sign in locally",
  "auth.step.manage": "Manage case assets",
  "auth.step.execute": "Run and track",
  "auth.welcome": "Welcome back",
  "auth.createAccount": "Create a local account",
  "auth.loginHint": "Sign in to continue managing and running cases",
  "auth.registerHint": "Your account and data stay in your local environment",
  "auth.displayName": "Display name",
  "auth.email": "Email",
  "auth.password": "Password",
  "auth.loginSubmit": "Sign in to workspace",
  "auth.registerSubmit": "Create account and continue",
  "auth.createPrompt": "New to CasePilot? Create a local account",
  "auth.loginPrompt": "Already have an account? Sign in",
  "auth.demo": "Demo credentials",
  "auth.error.invalid": "Incorrect email or password",
  "auth.error.exists": "This email is already registered. Please sign in.",
  "auth.error.offline": "The local data service is unavailable. Check that PostgreSQL and the API are running.",
  "nav.main": "Main navigation",
  "nav.knowledge": "Knowledge",
  "nav.workbench": "AI Workspace",
  "nav.cases": "Test Cases",
  "nav.execute": "Executions",
  "nav.logout": "Sign out",
  "page.newConversation": "New AI conversation",
  "page.workbench": "AI Test Workspace",
  "page.knowledge": "Space Knowledge",
  "page.library": "Test Case Management",
  "page.execution": "QA Execution",
  "common.localSpace": "Local quality space",
  "common.owner": "Owner",
  "common.member": "Member",
  "common.close": "Close message",
  "common.loadingWorkspace": "Preparing your workspace…",
  "common.unsaved": "This page has unsaved changes. Leaving will discard them. Continue?",
  "conversation.placeholder": "Describe what you want to test, or ask CasePilot a question",
  "conversation.write": "Message CasePilot",
  "conversation.addKnowledge": "Add knowledge files",
  "conversation.uploadHint": "Upload PDF or TXT",
  "conversation.processing": "Understanding and processing…",
  "conversation.autoIntent": "Automatic intent detection",
  "conversation.model": "Generation model",
  "conversation.sending": "Processing",
  "conversation.send": "Send",
  "conversation.knowledgeEnabled": "Space knowledge enabled",
  "conversation.history": "Conversation history",
  "conversation.confirmCollection": "Confirm the case collection for this conversation",
  "conversation.collectionLocked": "Once confirmed, this conversation can only manage this collection.",
  "conversation.chooseCollection": "Choose a collection",
  "conversation.newCollection": "Or enter a new collection name",
  "conversation.enterWorkbench": "Confirm and open workspace",
  "conversation.thinking": "Thinking…",
  "conversation.intentUnknown": "I’m not certain what you want yet. Choose an action:",
  "conversation.crossCollection": "This cross-collection request cannot run in the current conversation.",
  "conversation.openCollection": "Start a conversation with that collection",
  "conversation.cancel": "Cancel operation",
  "conversation.preparing": "Understanding your request and preparing a response…",
  "conversation.hero": "What would you like to test?",
  "conversation.heroHint": "Describe a requirement or ask a question. CasePilot will identify your intent first.",
  "conversation.routing": "The collection workspace opens only for confirmed case generation, modification, deletion, or queries.",
  "conversation.examples": "Try one of these",
  "example.generate.title": "Generate login test cases",
  "example.generate.description": "Cover success, rate limits, expiry, and poor networks",
  "example.generate.prompt": "Generate test cases for phone verification-code login, covering the happy path, rate limits, code expiry, and poor networks.",
  "example.scope.title": "Outline the test scope",
  "example.scope.description": "Explore the scope before creating a collection",
  "example.scope.prompt": "What test dimensions should a complete payment refund feature cover?",
  "example.modify.title": "Modify selected cases",
  "example.modify.description": "Select nodes in the workspace, then rewrite them",
  "example.modify.prompt": "Add poor-network recovery checks to the selected login cases without changing other fields.",
  "intent.generate": "Generate cases",
  "intent.modify": "Modify cases",
  "intent.delete": "Delete cases",
  "intent.query": "Query cases",
  "intent.knowledge": "Knowledge Q&A",
  "intent.chat": "General chat",
  "intent.clarify": "Clarify request",
  "model.auto": "Auto-select model",
};

type I18nContextValue = {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: TranslationKey) => string;
  pick: (english: string, chinese: string) => string;
};

const I18nContext = createContext<I18nContextValue | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const locale = useSyncExternalStore<Locale>(
    subscribeToLocale,
    readLocale,
    () => "en",
  );

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const setLocale = useCallback((nextLocale: Locale) => {
    inMemoryLocale = nextLocale;
    try {
      window.localStorage.setItem(STORAGE_KEY, nextLocale);
    } catch {
      // The active session still changes language if storage is unavailable.
    }
    localeListeners.forEach((listener) => listener());
  }, []);
  const t = useCallback(
    (key: TranslationKey) => (locale === "zh-CN" ? zhCN[key] : en[key]),
    [locale],
  );
  const pick = useCallback(
    (english: string, chinese: string) =>
      locale === "zh-CN" ? chinese : english,
    [locale],
  );
  const value = useMemo(
    () => ({ locale, setLocale, t, pick }),
    [locale, setLocale, t, pick],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const context = useContext(I18nContext);
  if (!context) throw new Error("useI18n must be used inside I18nProvider");
  return context;
}

export function LanguageSwitcher({ compact = false }: { compact?: boolean }) {
  const { locale, setLocale, t } = useI18n();
  const nextLocale = locale === "en" ? "zh-CN" : "en";
  return (
    <button
      type="button"
      className={`language-switcher${compact ? " language-switcher--compact" : ""}`}
      onClick={() => setLocale(nextLocale)}
      aria-label={`${t("language.label")}: ${locale === "en" ? t("language.english") : t("language.chinese")}`}
      title={t("language.label")}
    >
      <Languages size={compact ? 17 : 16} />
      <span>{nextLocale === "zh-CN" ? "中文" : "EN"}</span>
    </button>
  );
}
