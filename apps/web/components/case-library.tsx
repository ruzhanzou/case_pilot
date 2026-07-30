"use client";

import { CaseMindMap } from "@/components/case-mind-map";
import type { CaseCollectionDto, TestCaseDto } from "@/lib/casepilot-api";
import {
  Archive,
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  Edit3,
  FolderPlus,
  GitFork,
  List,
  Plus,
  Play,
  Search,
  Sparkles,
  Tags,
  Trash2,
} from "lucide-react";
import { useMemo, useState } from "react";

const CASES_PER_PAGE = 20;

type CaseLibraryProps = {
  collections: CaseCollectionDto[];
  selectedCollection: CaseCollectionDto | null;
  cases: TestCaseDto[];
  selectedCase: TestCaseDto | null;
  loading: boolean;
  onSelectCollection: (collectionId: string) => void;
  onCreateCollection: () => void;
  onEditCollection: () => void;
  onDeleteCollection: () => void;
  onCreateCase: (module?: string) => void;
  onOpenWorkbench: () => void;
  onStartExecution: () => void;
  onSelectCase: (caseId: string) => void;
  onEditCase: (testCase: TestCaseDto) => void;
  onDeleteCase: (testCase: TestCaseDto) => void;
};

export function CaseLibrary({
  collections,
  selectedCollection,
  cases,
  selectedCase,
  loading,
  onSelectCollection,
  onCreateCollection,
  onEditCollection,
  onDeleteCollection,
  onCreateCase,
  onOpenWorkbench,
  onStartExecution,
  onSelectCase,
  onEditCase,
  onDeleteCase,
}: CaseLibraryProps) {
  const [query, setQuery] = useState("");
  const [viewMode, setViewMode] = useState<"list" | "mind-map">("list");
  const [currentPage, setCurrentPage] = useState(1);
  const filteredCases = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return cases;
    return cases.filter((testCase) =>
      [
        testCase.case_key,
        testCase.title,
        testCase.module,
        testCase.tags.join(" "),
      ]
        .join(" ")
        .toLowerCase()
        .includes(normalized),
    );
  }, [cases, query]);
  const pageCount = Math.max(
    1,
    Math.ceil(filteredCases.length / CASES_PER_PAGE),
  );
  const effectivePage = Math.min(currentPage, pageCount);
  const paginatedCases = useMemo(
    () =>
      filteredCases.slice(
        (effectivePage - 1) * CASES_PER_PAGE,
        effectivePage * CASES_PER_PAGE,
      ),
    [effectivePage, filteredCases],
  );

  return (
    <div className="case-library">
      <aside className="collection-sidebar">
        <div className="collection-sidebar__head">
          <div>
            <span className="management-kicker">当前空间</span>
            <h2>用例集合</h2>
          </div>
          <button
            className="management-icon-button"
            type="button"
            onClick={onCreateCollection}
            aria-label="创建用例集合"
          >
            <FolderPlus size={18} />
          </button>
        </div>
        <div className="collection-sidebar__list">
          {collections.map((collection) => (
            <button
              type="button"
              key={collection.id}
              className={
                collection.id === selectedCollection?.id
                  ? "collection-item is-active"
                  : "collection-item"
              }
              onClick={() => {
                setCurrentPage(1);
                onSelectCollection(collection.id);
              }}
            >
              <span className="collection-item__icon">
                <Archive size={17} />
              </span>
              <span>
                <strong>{collection.name}</strong>
                <small>{collection.case_count} 条用例</small>
              </span>
              <ChevronRight size={15} />
            </button>
          ))}
        </div>
      </aside>

      <section
        className={
          viewMode === "list"
            ? "case-library__main case-library__main--list"
            : "case-library__main"
        }
      >
        <header className="case-library__header">
          <div>
            <span className="management-kicker">用例管理</span>
            <h1>{selectedCollection?.name ?? "请选择用例集合"}</h1>
            <p>{selectedCollection?.description || "管理当前空间中的结构化测试用例"}</p>
            {selectedCollection && (
              <div className="case-library__summary" aria-label="用例集合摘要">
                <span><b>{cases.length}</b> 用例</span>
                <span>工作区状态：持续 Session · 自动保存</span>
                <span>执行结果请在 QA 执行批次中查看</span>
              </div>
            )}
          </div>
          <div className="case-library__header-actions">
            {selectedCollection && (
              <>
                <button
                  className="management-button management-button--ai"
                  type="button"
                  onClick={onOpenWorkbench}
                >
                  <Sparkles size={16} /> 进入/继续工作区
                </button>
                <button
                  className="management-button management-button--execution"
                  type="button"
                  onClick={onStartExecution}
                >
                  <Play size={16} /> 开始执行
                </button>
                <button
                  className="management-button"
                  type="button"
                  onClick={onEditCollection}
                >
                  <Edit3 size={16} /> 编辑集合
                </button>
                <button
                  className="management-button management-button--danger-quiet"
                  type="button"
                  onClick={onDeleteCollection}
                >
                  <Trash2 size={16} /> 删除集合
                </button>
                <button
                  className="management-button management-button--primary"
                  type="button"
                  onClick={() => onCreateCase()}
                >
                  <Plus size={17} /> 新建用例
                </button>
              </>
            )}
          </div>
        </header>

        <div className="case-library__toolbar">
          <label className="case-search">
            <Search size={17} />
            <input
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                setCurrentPage(1);
              }}
              placeholder="搜索用例名称、编号、模块或标签"
            />
          </label>
          <div className="case-library__view-controls">
            <span>{loading ? "正在读取…" : `${filteredCases.length} 条用例`}</span>
            <div className="view-segment" aria-label="用例视图">
              <button
                type="button"
                className={viewMode === "list" ? "is-active" : ""}
                onClick={() => setViewMode("list")}
                aria-label="用例列表"
              >
                <List size={15} /> 列表
              </button>
              <button
                type="button"
                className={viewMode === "mind-map" ? "is-active" : ""}
                onClick={() => setViewMode("mind-map")}
                aria-label="用例脑图"
              >
                <GitFork size={15} /> 脑图
              </button>
            </div>
          </div>
        </div>

        <div
          className={
            viewMode === "mind-map"
              ? "case-library__body case-library__body--mind-map"
              : "case-library__body case-library__body--list"
          }
        >
          <div className={viewMode === "mind-map" ? "case-map-wrap" : "case-table-wrap"}>
            {viewMode === "mind-map" && selectedCollection ? (
              <CaseMindMap
                collection={selectedCollection}
                cases={filteredCases}
                selectedCaseId={selectedCase?.id ?? ""}
                onSelectCase={onSelectCase}
                onCreateCase={onCreateCase}
                onEditCase={onEditCase}
              />
            ) : (
              <>
                <table className="case-table">
              <thead>
                <tr>
                  <th>用例</th>
                  <th>模块</th>
                  <th>优先级</th>
                  <th>标签</th>
                  <th>版本</th>
                </tr>
              </thead>
              <tbody>
                {paginatedCases.map((testCase) => (
                  <tr
                    key={testCase.id}
                    className={selectedCase?.id === testCase.id ? "is-selected" : ""}
                  >
                    <td>
                      <button
                        type="button"
                        className="case-table__title"
                        onClick={() => onSelectCase(testCase.id)}
                      >
                        <code>{testCase.case_key}</code>
                        <strong>{testCase.title}</strong>
                      </button>
                    </td>
                    <td>{testCase.module || "未分类"}</td>
                    <td>
                      <span className={`priority-badge priority-badge--${testCase.priority.toLowerCase()}`}>
                        {testCase.priority}
                      </span>
                    </td>
                    <td>
                      <div className="case-tag-list">
                        {testCase.tags.slice(0, 3).map((tag) => (
                          <span key={tag}>{tag}</span>
                        ))}
                      </div>
                    </td>
                    <td>V{testCase.revision_number}</td>
                  </tr>
                ))}
              </tbody>
                </table>
                {!!filteredCases.length && (
                  <nav className="case-pagination" aria-label="用例列表分页">
                    <span>
                      第 {effectivePage} / {pageCount} 页 · 每页 {CASES_PER_PAGE} 条
                    </span>
                    <div>
                      <button
                        type="button"
                        disabled={effectivePage === 1}
                        onClick={() => setCurrentPage(effectivePage - 1)}
                        aria-label="上一页"
                      >
                        <ChevronLeft size={15} /> 上一页
                      </button>
                      <button
                        type="button"
                        disabled={effectivePage === pageCount}
                        onClick={() => setCurrentPage(effectivePage + 1)}
                        aria-label="下一页"
                      >
                        下一页 <ChevronRight size={15} />
                      </button>
                    </div>
                  </nav>
                )}
                {!loading && !filteredCases.length && (
                  <div className="management-empty">
                    <ClipboardList size={28} />
                    <strong>当前集合还没有匹配的用例</strong>
                    <p>创建第一条结构化测试用例，或调整搜索条件。</p>
                    <button
                      type="button"
                      className="management-button management-button--primary"
                      onClick={() => onCreateCase()}
                    >
                      <Plus size={16} /> 新建用例
                    </button>
                  </div>
                )}
              </>
            )}
          </div>

          <aside className="case-detail">
            {selectedCase ? (
              <>
                <header className="case-detail__header">
                  <div>
                    <span className="management-kicker">
                      {selectedCase.case_key} · V{selectedCase.revision_number}
                    </span>
                    <h2>{selectedCase.title}</h2>
                  </div>
                  <div>
                    <button
                      className="management-icon-button"
                      type="button"
                      onClick={() => onEditCase(selectedCase)}
                      aria-label="编辑当前用例"
                    >
                      <Edit3 size={17} />
                    </button>
                    <button
                      className="management-icon-button management-icon-button--danger"
                      type="button"
                      onClick={() => onDeleteCase(selectedCase)}
                      aria-label="删除当前用例"
                    >
                      <Trash2 size={17} />
                    </button>
                  </div>
                </header>

                <div className="case-detail__meta">
                  <span>{selectedCase.module || "未分类"}</span>
                  <span>{selectedCase.case_type}</span>
                  <span>{selectedCase.priority}</span>
                </div>

                <section className="case-detail__section">
                  <h3>前置条件</h3>
                  <ol>
                    {selectedCase.preconditions.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ol>
                </section>

                <section className="case-detail__section">
                  <h3>执行步骤与校验点</h3>
                  <div className="case-detail__steps">
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

                <section className="case-detail__source">
                  <Tags size={15} />
                  <span>来源：{selectedCase.source || "未记录"}</span>
                </section>
              </>
            ) : (
              <div className="management-empty management-empty--detail">
                <ClipboardList size={26} />
                <strong>选择一条用例查看详情</strong>
              </div>
            )}
          </aside>
        </div>
      </section>
    </div>
  );
}
