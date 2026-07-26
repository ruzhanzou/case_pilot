"use client";

import {
  PromptInput,
  PromptInputActionAddAttachments,
  PromptInputActionMenu,
  PromptInputActionMenuContent,
  PromptInputActionMenuTrigger,
  PromptInputBody,
  PromptInputFooter,
  PromptInputProvider,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools,
  usePromptInputController,
} from "@/components/ai-elements/prompt-input";
import { ModelSelector, type ModelId } from "@/components/model-selector";
import type { PromptInputMessage } from "@/components/ai-elements/prompt-input";
import { motion } from "motion/react";
import {
  ArrowRight,
  ChevronDown,
  Clock3,
  FileSearch,
  FolderOpen,
  Layers3,
  ShieldAlert,
  Upload,
  UserRoundCheck,
} from "lucide-react";

export type RecentCollection = {
  id: string;
  name: string;
  description: string;
  count: number;
  updated: string;
};

type GlobalChatHomeProps = {
  accountName: string;
  spaceName: string;
  pendingCollectionName?: string;
  recentCollections: RecentCollection[];
  onOpenSpace: () => void;
  onOpenAccount: () => void;
  onOpenCollections: () => void;
  onOpenCollection: (collection: RecentCollection) => void;
  onSubmit: (message: PromptInputMessage) => void | Promise<void>;
  modelId: ModelId;
  onModelChange: (modelId: ModelId) => void;
};

const promptExamples = [
  {
    icon: FileSearch,
    title: "生成完整功能用例",
    prompt: "根据需求文档生成完整功能测试用例，覆盖主流程、异常流程和边界值。",
  },
  {
    icon: ShieldAlert,
    title: "优先识别风险",
    prompt: "先分析需求中的歧义和高风险点，再生成需要优先评审的测试用例。",
  },
  {
    icon: Layers3,
    title: "生成冒烟用例",
    prompt: "生成一组发布前可执行的 P0 冒烟测试用例，每一步都包含明确校验点。",
  },
];

function GlobalComposer({
  pendingCollectionName,
  onSubmit,
  modelId,
  onModelChange,
}: Pick<
  GlobalChatHomeProps,
  "pendingCollectionName" | "onSubmit" | "modelId" | "onModelChange"
>) {
  const controller = usePromptInputController();

  return (
    <>
      <PromptInput
        className="global-composer"
        accept=".doc,.docx,.pdf,.md,.txt,.xlsx,.xls,.csv,.png,.jpg,.jpeg"
        multiple
        maxFiles={20}
        maxFileSize={20 * 1024 * 1024}
        onSubmit={onSubmit}
      >
        <PromptInputBody>
          <PromptInputTextarea
            className="global-composer__textarea"
            placeholder="描述要测试的功能，或上传 Word、PDF、Excel、图片等需求材料…"
          />
        </PromptInputBody>
        <PromptInputFooter className="global-composer__footer">
          <PromptInputTools>
            <PromptInputActionMenu>
              <PromptInputActionMenuTrigger tooltip="上传需求文件" />
              <PromptInputActionMenuContent>
                <PromptInputActionAddAttachments label="上传 Word、PDF、Excel、图片或文本" />
              </PromptInputActionMenuContent>
            </PromptInputActionMenu>
            <span className="global-composer__target">
              <FolderOpen size={15} />
              保存到：{pendingCollectionName || "自动创建新用例集"}
              <ChevronDown size={14} />
            </span>
            <ModelSelector
              value={modelId}
              onValueChange={onModelChange}
            />
          </PromptInputTools>
          <PromptInputSubmit status="ready" />
        </PromptInputFooter>
      </PromptInput>

      <div className="home-prompt-examples" aria-label="快捷提示">
        {promptExamples.map((example) => (
          <button
            type="button"
            key={example.title}
            onClick={() => controller.textInput.setInput(example.prompt)}
          >
            <example.icon size={17} />
            <span>
              <strong>{example.title}</strong>
              <small>{example.prompt}</small>
            </span>
          </button>
        ))}
      </div>
    </>
  );
}

export function GlobalChatHome({
  accountName,
  spaceName,
  pendingCollectionName,
  recentCollections,
  onOpenSpace,
  onOpenAccount,
  onOpenCollections,
  onOpenCollection,
  onSubmit,
  modelId,
  onModelChange,
}: GlobalChatHomeProps) {
  return (
    <section className="global-home">
      <header className="global-home__header">
        <button className="global-home__space" type="button" onClick={onOpenSpace}>
          空间 / {spaceName}
          <ChevronDown size={16} />
        </button>
        <div>
          <button type="button" onClick={onOpenCollections}>
            <Layers3 size={17} />
            用例集管理
          </button>
          <button type="button" onClick={onOpenAccount}>
            <UserRoundCheck size={17} />
            {accountName}
          </button>
        </div>
      </header>

      <div className="global-home__content">
        <motion.div
          className="global-home__hero"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35 }}
        >
          <h1 className="typewriter-heading" aria-label="想测试什么？">
            <span aria-hidden="true">想测试什么？</span>
          </h1>
          <p>用自然语言描述目标，或直接上传需求材料。CasePilot 会先分析需求与风险，再生成可评审、可编辑的测试用例脑图。</p>

          <PromptInputProvider>
            <GlobalComposer
              pendingCollectionName={pendingCollectionName}
              onSubmit={onSubmit}
              modelId={modelId}
              onModelChange={onModelChange}
            />
          </PromptInputProvider>

          <div className="home-file-support">
            <Upload size={15} />
            支持 DOCX、PDF、Excel、Markdown、TXT、PNG、JPG，单文件最大 20MB
          </div>
        </motion.div>

        <section className="recent-collections">
          <div className="recent-collections__heading">
            <h2>最近用例集</h2>
            <button type="button" onClick={onOpenCollections}>
              查看当前空间全部用例集
              <ArrowRight size={16} />
            </button>
          </div>
          <div className="recent-collections__grid">
            {recentCollections.map((collection) => (
              <button
                type="button"
                key={collection.id}
                onClick={() => onOpenCollection(collection)}
              >
                <span className="recent-collection__icon">
                  <FolderOpen size={20} />
                </span>
                <span>
                  <strong>{collection.name}</strong>
                  <small>{collection.description}</small>
                </span>
                <span className="recent-collection__meta">
                  {collection.count} 条用例
                  <i />
                  <Clock3 size={13} />
                  {collection.updated}
                </span>
              </button>
            ))}
          </div>
        </section>
      </div>
    </section>
  );
}
