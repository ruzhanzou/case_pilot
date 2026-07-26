"use client";

import {
  Activity,
  ClipboardCheck,
  FolderKanban,
  LayoutList,
  MessageSquareText,
  TestTube2,
} from "lucide-react";

export type ProductPage = "home" | "collections" | "cases" | "execution" | "insights" | "studio";

type AppNavigationProps = {
  activePage: ProductPage;
  accountName: string;
  onNavigate: (page: ProductPage) => void;
  onOpenAccount: () => void;
};

export function AppNavigation({
  activePage,
  accountName,
  onNavigate,
  onOpenAccount,
}: AppNavigationProps) {
  return (
    <nav className="nav-rail" aria-label="主导航">
      <div className="brand-mark" aria-label="CasePilot">
        <TestTube2 size={21} />
      </div>
      <div className="nav-rail__items">
        <button
          className={activePage === "home" ? "is-active" : ""}
          type="button"
          aria-label="开始设计"
          title="开始设计"
          onClick={() => onNavigate("home")}
        >
          <MessageSquareText size={21} />
        </button>
        <button
          className={activePage === "collections" ? "is-active" : ""}
          type="button"
          aria-label="用例集管理"
          title="用例集管理"
          onClick={() => onNavigate("collections")}
        >
          <FolderKanban size={21} />
        </button>
        <button
          className={activePage === "cases" ? "is-active" : ""}
          type="button"
          aria-label="全部用例"
          title="全部用例"
          onClick={() => onNavigate("cases")}
        >
          <LayoutList size={21} />
        </button>
        <button
          className={activePage === "execution" ? "is-active" : ""}
          type="button"
          aria-label="测试执行"
          title="测试执行"
          onClick={() => onNavigate("execution")}
        >
          <ClipboardCheck size={21} />
        </button>
        <button className={activePage === "insights" ? "is-active" : ""} type="button" aria-label="质量洞察" title="质量洞察" onClick={() => onNavigate("insights")}>
          <Activity size={21} />
        </button>
      </div>
      <div className="nav-rail__bottom">
        <button
          className="avatar"
          type="button"
          aria-label="账号信息"
          title="账号信息"
          onClick={onOpenAccount}
        >
          {accountName.slice(0, 1)}
        </button>
      </div>
    </nav>
  );
}
