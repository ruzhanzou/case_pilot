"use client";

import { CaseMindMap } from "@/components/case-mind-map";
import {
  CollectionStatusBadge,
} from "@/components/collection-status-badge";
import type {
  CaseCollectionDto,
  TestCaseDto,
  TestCaseInput,
} from "@/lib/casepilot-api";
import { matchesCaseSearch, matchesCollectionSearch } from "@/lib/case-search";
import { useI18n } from "@/lib/i18n";
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
  Upload,
} from "lucide-react";
import { useMemo, useState } from "react";

const CASES_PER_PAGE = 20;

type CaseLibraryProps = {
  collections: CaseCollectionDto[];
  selectedCollection: CaseCollectionDto | null;
  cases: TestCaseDto[];
  selectedCase: TestCaseDto | null;
  loading: boolean;
  importingCollectionId?: string;
  onSelectCollection: (collectionId: string) => void;
  onCreateCollection: () => void;
  onImportExcel: () => void;
  onEditCollection: () => void;
  onDeleteCollection: () => void;
  onCreateCase: (module?: string) => void;
  onCreateCaseInline: (input: TestCaseInput) => Promise<void>;
  onOpenWorkbench: () => void;
  onStartExecution: () => void;
  onSelectCase: (caseId: string) => void;
  onEditCase: (testCase: TestCaseDto) => void;
  onSaveCase: (testCase: TestCaseDto, input: TestCaseInput) => Promise<void>;
  onDeleteCase: (testCase: TestCaseDto) => void;
};

export function CaseLibrary({
  collections,
  selectedCollection,
  cases,
  selectedCase,
  loading,
  importingCollectionId,
  onSelectCollection,
  onCreateCollection,
  onImportExcel,
  onEditCollection,
  onDeleteCollection,
  onCreateCase,
  onCreateCaseInline,
  onOpenWorkbench,
  onStartExecution,
  onSelectCase,
  onEditCase,
  onSaveCase,
  onDeleteCase,
}: CaseLibraryProps) {
  const { pick } = useI18n();
  const [query, setQuery] = useState("");
  const [collectionQuery, setCollectionQuery] = useState("");
  const [viewMode, setViewMode] = useState<"list" | "mind-map">("list");
  const [currentPage, setCurrentPage] = useState(1);
  const filteredCases = useMemo(() => {
    return cases.filter((testCase) => matchesCaseSearch(testCase, query));
  }, [cases, query]);
  const filteredCollections = useMemo(
    () =>
      collections.filter((collection) =>
        matchesCollectionSearch(collection, collectionQuery),
      ),
    [collectionQuery, collections],
  );
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
            <span className="management-kicker">{pick("Current space", "当前空间")}</span>
            <h2>{pick("Collections", "用例集合")}</h2>
          </div>
          <div className="collection-sidebar__actions">
            <button
              className="management-icon-button"
              type="button"
              onClick={onImportExcel}
              disabled={!selectedCollection}
              aria-label={pick("Import cases from Excel", "从 Excel 导入用例")}
              title={pick("Import cases from Excel", "从 Excel 导入用例")}
            >
              <Upload size={18} />
            </button>
            <button
              className="management-icon-button"
              type="button"
              onClick={onCreateCollection}
              aria-label={pick("Create collection", "创建用例集合")}
              title={pick("Create collection", "创建用例集合")}
            >
              <FolderPlus size={18} />
            </button>
          </div>
        </div>
        <label className="collection-search">
          <Search size={15} />
          <input
            value={collectionQuery}
            onChange={(event) => setCollectionQuery(event.target.value)}
            placeholder={pick("Search collections", "搜索集合")}
            aria-label={pick("Search case collections", "搜索用例集合")}
          />
        </label>
        <div className="collection-sidebar__list">
          {filteredCollections.map((collection) => (
            <button
              type="button"
              key={collection.id}
              className={
                collection.id === selectedCollection?.id
                  ? "collection-item is-active"
                  : "collection-item"
              }
              title={collection.name}
              onClick={() => {
                setCurrentPage(1);
                onSelectCollection(collection.id);
              }}
            >
              <span className="collection-item__icon">
                <Archive size={17} />
              </span>
              <span className="collection-item__content">
                <strong>{collection.name}</strong>
                <small>
                  <span className="collection-item__count">
                    {pick(`${collection.case_count} cases`, `${collection.case_count} 条用例`)}
                  </span>
                  <CollectionStatusBadge
                    compact
                    status={
                      collection.id === importingCollectionId
                        ? "importing"
                        : collection.lifecycle_status
                    }
                  />
                </small>
              </span>
              <ChevronRight size={15} />
            </button>
          ))}
          {!filteredCollections.length && (
            <div className="collection-sidebar__empty">
              <Search size={18} />
              <span>{pick("No matching collections", "没有匹配的用例集合")}</span>
            </div>
          )}
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
            <span className="management-kicker">{pick("Test cases", "用例管理")}</span>
            <div className="case-library__title-row">
              <h1>{selectedCollection?.name ?? pick("Choose a collection", "请选择用例集合")}</h1>
              {selectedCollection && (
                <CollectionStatusBadge
                  status={
                    selectedCollection.id === importingCollectionId
                      ? "importing"
                      : selectedCollection.lifecycle_status
                  }
                />
              )}
            </div>
            <p>{selectedCollection?.description || pick("Manage structured test cases in this space", "管理当前空间中的结构化测试用例")}</p>
            {selectedCollection && (
              <div className="case-library__summary" aria-label={pick("Collection summary", "用例集合摘要")}>
                <span><b>{cases.length}</b> {pick("cases", "用例")}</span>
                <span>{pick("Workspace: persistent session · autosaved", "工作区状态：持续 Session · 自动保存")}</span>
                <span>{pick("View results in QA execution runs", "执行结果请在 QA 执行批次中查看")}</span>
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
                  title={pick("Open workspace", "进入/继续工作区")}
                >
                  <Sparkles size={16} /> {pick("Open workspace", "进入/继续工作区")}
                </button>
                <button
                  className="management-button management-button--execution"
                  type="button"
                  onClick={onStartExecution}
                  title={pick("Run a Playlist", "创建 Playlist 执行")}
                >
                  <Play size={16} /> {pick("Run a Playlist", "创建 Playlist 执行")}
                </button>
                <button
                  className="management-button"
                  type="button"
                  onClick={onEditCollection}
                  title={pick("Edit collection", "编辑集合")}
                >
                  <Edit3 size={16} /> {pick("Edit collection", "编辑集合")}
                </button>
                <button
                  className="management-button management-button--danger-quiet"
                  type="button"
                  onClick={onDeleteCollection}
                  title={pick("Delete collection", "删除集合")}
                >
                  <Trash2 size={16} /> {pick("Delete collection", "删除集合")}
                </button>
                <button
                  className="management-button management-button--primary"
                  type="button"
                  onClick={() => onCreateCase()}
                >
                  <Plus size={17} /> {pick("New case", "新建用例")}
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
              placeholder={pick("Search ID, title, target, or creator", "搜索编号、标题、test_target、创建人等")}
              aria-label={pick("Search test cases", "搜索用例资产")}
            />
          </label>
          <div className="case-library__view-controls">
            <span>{loading ? pick("Loading…", "正在读取…") : pick(`${filteredCases.length} cases`, `${filteredCases.length} 条用例`)}</span>
            <div className="view-segment" aria-label={pick("Case view", "用例视图")}>
              <button
                type="button"
                className={viewMode === "list" ? "is-active" : ""}
                onClick={() => setViewMode("list")}
                aria-label={pick("Case list", "用例列表")}
              >
                <List size={15} /> {pick("List", "列表")}
              </button>
              <button
                type="button"
                className={viewMode === "mind-map" ? "is-active" : ""}
                onClick={() => setViewMode("mind-map")}
                aria-label={pick("Case mind map", "用例脑图")}
              >
                <GitFork size={15} /> {pick("Map", "脑图")}
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
                key={selectedCollection.id}
                collection={selectedCollection}
                cases={filteredCases}
                selectedCaseId={selectedCase?.id ?? ""}
                onSelectCase={onSelectCase}
                onCreateCase={onCreateCase}
                onCreateCaseInline={onCreateCaseInline}
                onEditCase={onEditCase}
                onSaveCase={onSaveCase}
              />
            ) : (
              <>
                <table className="case-table">
              <thead>
                <tr>
                  <th>{pick("Case", "用例")}</th>
                  <th>{pick("Module", "模块")}</th>
                  <th>Test target</th>
                  <th>{pick("Creator", "创建人")}</th>
                  <th>{pick("Priority", "优先级")}</th>
                  <th>{pick("Tags", "标签")}</th>
                  <th>{pick("Version", "版本")}</th>
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
                    <td>{testCase.module || pick("Uncategorized", "未分类")}</td>
                    <td>
                      {testCase.test_targets?.length ? (
                        <div className="case-target-list">
                          {testCase.test_targets.slice(0, 2).map((target) => (
                            <span key={`${target.target_type}:${target.target_id}`}>
                              <strong>{target.target_key || target.title}</strong>
                              <small>{target.target_type}:{target.target_id}</small>
                            </span>
                          ))}
                        </div>
                      ) : "—"}
                    </td>
                    <td title={testCase.creator?.email}>
                      {testCase.creator?.display_name ?? "—"}
                    </td>
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
                  <nav className="case-pagination" aria-label={pick("Case list pagination", "用例列表分页")}>
                    <span>
                      {pick(`Page ${effectivePage} of ${pageCount} · ${CASES_PER_PAGE} per page`, `第 ${effectivePage} / ${pageCount} 页 · 每页 ${CASES_PER_PAGE} 条`)}
                    </span>
                    <div>
                      <button
                        type="button"
                        disabled={effectivePage === 1}
                        onClick={() => setCurrentPage(effectivePage - 1)}
                        aria-label={pick("Previous page", "上一页")}
                      >
                        <ChevronLeft size={15} /> {pick("Previous", "上一页")}
                      </button>
                      <button
                        type="button"
                        disabled={effectivePage === pageCount}
                        onClick={() => setCurrentPage(effectivePage + 1)}
                        aria-label={pick("Next page", "下一页")}
                      >
                        {pick("Next", "下一页")} <ChevronRight size={15} />
                      </button>
                    </div>
                  </nav>
                )}
                {!loading && !filteredCases.length && (
                  <div className="management-empty">
                    <ClipboardList size={28} />
                    <strong>{pick("No matching cases in this collection", "当前集合还没有匹配的用例")}</strong>
                    <p>{pick("Create the first structured case or change your search.", "创建第一条结构化测试用例，或调整搜索条件。")}</p>
                    <button
                      type="button"
                      className="management-button management-button--primary"
                      onClick={() => onCreateCase()}
                    >
                      <Plus size={16} /> {pick("New case", "新建用例")}
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
                      aria-label={pick("Edit current case", "编辑当前用例")}
                      title={pick("Edit case", "编辑用例")}
                    >
                      <Edit3 size={17} />
                    </button>
                    <button
                      className="management-icon-button management-icon-button--danger"
                      type="button"
                      onClick={() => onDeleteCase(selectedCase)}
                      aria-label={pick("Delete current case", "删除当前用例")}
                      title={pick("Delete case", "删除用例")}
                    >
                      <Trash2 size={17} />
                    </button>
                  </div>
                </header>

                <div className="case-detail__meta">
                  <span>{selectedCase.module || pick("Uncategorized", "未分类")}</span>
                  <span>{selectedCase.case_type}</span>
                  <span>{selectedCase.priority}</span>
                </div>

                <section className="case-detail__section">
                  <h3>{pick("Preconditions", "前置条件")}</h3>
                  <ol>
                    {selectedCase.preconditions.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ol>
                </section>

                <section className="case-detail__section">
                  <h3>{pick("Steps and validations", "执行步骤与校验点")}</h3>
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
                  <span>{pick("Source", "来源")}：{selectedCase.source || pick("Not recorded", "未记录")}</span>
                </section>
              </>
            ) : (
              <div className="management-empty management-empty--detail">
                <ClipboardList size={26} />
                <strong>{pick("Select a case to view details", "选择一条用例查看详情")}</strong>
              </div>
            )}
          </aside>
        </div>
      </section>
    </div>
  );
}
