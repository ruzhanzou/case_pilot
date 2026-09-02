"use client";

import {
  listConversationHistory,
  type ConversationSummaryDto,
} from "@/lib/casepilot-api";
import {
  Clock3,
  LoaderCircle,
  MessageSquarePlus,
  Search,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

type ConversationHistoryDrawerProps = {
  spaceId: string;
  open: boolean;
  revision: number;
  currentConversationId?: string;
  onClose: () => void;
  onNewConversation: () => void;
  onOpenConversation: (conversation: ConversationSummaryDto) => Promise<void>;
};

function formatUpdatedAt(value: string): string {
  const updatedAt = new Date(value);
  const now = new Date();
  if (updatedAt.toDateString() === now.toDateString()) {
    return updatedAt.toLocaleTimeString("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
    });
  }
  return updatedAt.toLocaleDateString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
  });
}

export function ConversationHistoryDrawer({
  open,
  spaceId,
  revision,
  currentConversationId,
  onClose,
  onNewConversation,
  onOpenConversation,
}: ConversationHistoryDrawerProps) {
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<ConversationSummaryDto[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    const timer = window.setTimeout(() => searchRef.current?.focus(), 30);
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [onClose, open]);

  useEffect(() => {
    if (!open) return;
    let active = true;
    const timer = window.setTimeout(() => {
      setLoading(true);
      setError("");
      void listConversationHistory({ spaceId, query, limit: 30 })
        .then((result) => {
          if (!active) return;
          setItems(result.items);
          setNextCursor(result.next_cursor);
        })
        .catch((caught) => {
          if (active) {
            setError(
              caught instanceof Error ? caught.message : "历史对话加载失败",
            );
          }
        })
        .finally(() => active && setLoading(false));
    }, query ? 250 : 0);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [open, query, revision, spaceId]);

  const loadMore = async () => {
    if (!nextCursor || loadingMore) return;
    setLoadingMore(true);
    try {
      const result = await listConversationHistory({
        spaceId,
        query,
        cursor: nextCursor,
        limit: 30,
      });
      setItems((current) => [...current, ...result.items]);
      setNextCursor(result.next_cursor);
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "更多历史对话加载失败",
      );
    } finally {
      setLoadingMore(false);
    }
  };

  return (
    <div
      className={`conversation-history-layer ${open ? "is-open" : "is-closed"}`}
      aria-hidden={!open}
    >
      <button
        type="button"
        className="conversation-history-backdrop"
        aria-label="关闭历史对话"
        onClick={onClose}
      />
      <aside
        className="conversation-history-drawer"
        role="dialog"
        aria-modal={open ? "true" : undefined}
        aria-label="我的历史对话"
      >
        <header>
          <div>
            <span>MY CONVERSATIONS</span>
            <h2>历史对话</h2>
          </div>
          <button type="button" onClick={onClose} aria-label="关闭历史对话">
            <X size={18} />
          </button>
        </header>

        <button
          type="button"
          className="conversation-history-new"
          onClick={() => {
            onNewConversation();
            onClose();
          }}
        >
          <MessageSquarePlus size={17} />
          新建对话
        </button>

        <label className="conversation-history-search">
          <Search size={16} />
          <input
            ref={searchRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索对话或用例集合"
          />
        </label>

        <div className="conversation-history-list">
          {loading ? (
            <div className="conversation-history-state">
              <LoaderCircle className="auth-spinner" size={20} />
              正在加载历史对话…
            </div>
          ) : error ? (
            <div className="conversation-history-state is-error">{error}</div>
          ) : items.length ? (
            <>
              {items.map((conversation) => (
                <button
                  type="button"
                  key={conversation.id}
                  className={
                    conversation.id === currentConversationId ? "is-current" : ""
                  }
                  aria-current={
                    conversation.id === currentConversationId ? "page" : undefined
                  }
                  onClick={() => {
                    setError("");
                    void onOpenConversation(conversation)
                      .then(onClose)
                      .catch((caught) => {
                        setError(
                          caught instanceof Error
                            ? caught.message
                            : "历史对话恢复失败",
                        );
                      });
                  }}
                >
                  <strong>{conversation.title}</strong>
                  <span>
                    {conversation.collection_name}
                    <time>
                      <Clock3 size={12} />
                      {formatUpdatedAt(conversation.updated_at)}
                    </time>
                  </span>
                  {conversation.last_message_preview && (
                    <small>{conversation.last_message_preview}</small>
                  )}
                </button>
              ))}
              {nextCursor && (
                <button
                  type="button"
                  className="conversation-history-more"
                  disabled={loadingMore}
                  onClick={() => void loadMore()}
                >
                  {loadingMore ? "正在加载…" : "加载更多"}
                </button>
              )}
            </>
          ) : (
            <div className="conversation-history-state">
              <MessageSquarePlus size={22} />
              <strong>{query ? "没有匹配的对话" : "还没有历史对话"}</strong>
              <span>创建新对话后会自动显示在这里。</span>
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}
