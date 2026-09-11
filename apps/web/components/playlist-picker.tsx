"use client";

import {
  completePlaylistCreation,
  createPlaylist,
  deletePlaylist,
  getPlaylistCreationSession,
  listPlaylists,
  listTestCases,
  publicErrorMessage,
  searchSpaceTestCases,
  updatePlaylist,
  type CaseCollectionDto,
  type PlaylistDto,
  type TestCaseDto,
} from "@/lib/casepilot-api";
import {
  Check,
  ChevronDown,
  ChevronRight,
  Layers3,
  ListPlus,
  LoaderCircle,
  PencilLine,
  Search,
  Trash2,
} from "lucide-react";
import {
  useEffect,
  useMemo,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";

type PlaylistPickerProps = {
  spaceId: string;
  collections: CaseCollectionDto[];
  seedCollectionId: string;
  requestId: number;
  creationSessionId?: string;
  selectedPlaylistId: string;
  onSelect: (playlist: PlaylistDto | null) => void;
  onError: (message: string) => void;
};

function messageFromError(caught: unknown, fallback: string) {
  return caught instanceof Error ? publicErrorMessage(caught.message) : fallback;
}

type CaseSelectionRowsProps = {
  cases: TestCaseDto[];
  selectedCaseIds: Set<string>;
  onToggle: (testCase: TestCaseDto) => void;
};

type CaseGroup = {
  collectionId: string;
  collectionName: string;
  cases: TestCaseDto[];
};

function groupCasesByCollection(
  cases: TestCaseDto[],
  collectionMap: Map<string, CaseCollectionDto>,
): CaseGroup[] {
  const groups = new Map<string, TestCaseDto[]>();
  for (const testCase of cases) {
    const collectionId =
      testCase.collection_ids.find((id) => collectionMap.has(id)) ?? "unassigned";
    const items = groups.get(collectionId) ?? [];
    items.push(testCase);
    groups.set(collectionId, items);
  }
  return [...groups.entries()].map(([collectionId, groupedCases]) => ({
    collectionId,
    collectionName: collectionMap.get(collectionId)?.name ?? "未归属集合",
    cases: groupedCases,
  }));
}

function CaseSelectionRows({
  cases,
  selectedCaseIds,
  onToggle,
}: CaseSelectionRowsProps) {
  return (
    <div className="playlist-tree__cases">
      {cases.map((testCase) => (
        <label key={testCase.id}>
          <input
            type="checkbox"
            checked={selectedCaseIds.has(testCase.id)}
            onChange={() => onToggle(testCase)}
          />
          <span>
            <code>{testCase.case_key}</code>
            <strong>{testCase.title}</strong>
            <small>
              {testCase.module || "未分类"} · {testCase.tags.join("、") || "无标签"}
            </small>
          </span>
        </label>
      ))}
      {!cases.length && <p>该集合暂无可执行用例</p>}
    </div>
  );
}

export function PlaylistPicker({
  spaceId,
  collections,
  seedCollectionId,
  requestId,
  creationSessionId,
  selectedPlaylistId,
  onSelect,
  onError,
}: PlaylistPickerProps) {
  const [playlists, setPlaylists] = useState<PlaylistDto[]>([]);
  const [allCases, setAllCases] = useState<TestCaseDto[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [awaitingSeedChoice, setAwaitingSeedChoice] = useState(false);
  const [name, setName] = useState("");
  const [selectedCaseIds, setSelectedCaseIds] = useState<string[]>([]);
  const [sourceCollectionIds, setSourceCollectionIds] = useState<string[]>([]);
  const [collapsedSelectedCollectionIds, setCollapsedSelectedCollectionIds] = useState<string[]>([]);
  const [collapsedSearchCollectionIds, setCollapsedSearchCollectionIds] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [deduplicatedCount, setDeduplicatedCount] = useState(0);
  const [creationDraft, setCreationDraft] = useState<{
    description: string;
    executionNotes: string;
  }>({ description: "", executionNotes: "" });

  const matchingPlaylists = useMemo(
    () =>
      seedCollectionId
        ? playlists.filter((item) =>
            item.source_collection_ids.includes(seedCollectionId),
          )
        : [],
    [playlists, seedCollectionId],
  );

  const collectionMap = useMemo(
    () => new Map(collections.map((collection) => [collection.id, collection])),
    [collections],
  );
  const allCaseMap = useMemo(
    () => new Map(allCases.map((testCase) => [testCase.id, testCase])),
    [allCases],
  );
  const casesByCollectionId = useMemo(() => {
    const result = new Map<string, TestCaseDto[]>();
    for (const testCase of allCases) {
      for (const collectionId of testCase.collection_ids) {
        if (!collectionMap.has(collectionId)) continue;
        const items = result.get(collectionId) ?? [];
        items.push(testCase);
        result.set(collectionId, items);
      }
    }
    return result;
  }, [allCases, collectionMap]);
  const selectedCaseIdSet = useMemo(() => new Set(selectedCaseIds), [selectedCaseIds]);
  const selectedCases = useMemo(
    () => selectedCaseIds.flatMap((id) => {
      const testCase = allCaseMap.get(id);
      return testCase ? [testCase] : [];
    }),
    [allCaseMap, selectedCaseIds],
  );
  const selectedCaseGroups = useMemo(
    () => groupCasesByCollection(selectedCases, collectionMap),
    [collectionMap, selectedCases],
  );
  const visibleCases = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return allCases.filter((testCase) => {
      if (!normalized) return true;
      const collectionNames = testCase.collection_ids
        .map((id) => collectionMap.get(id)?.name ?? "")
        .join(" ");
      return [
        testCase.case_key,
        testCase.title,
        testCase.module,
        testCase.tags.join(" "),
        collectionNames,
      ]
        .join(" ")
        .toLowerCase()
        .includes(normalized);
    });
  }, [allCases, collectionMap, query]);
  const caseGroups = useMemo(
    () => groupCasesByCollection(visibleCases, collectionMap),
    [collectionMap, visibleCases],
  );
  const unavailableSelectedCaseIds = useMemo(() => {
    const availableIds = new Set(allCases.map((item) => item.id));
    return selectedCaseIds.filter((id) => !availableIds.has(id));
  }, [allCases, selectedCaseIds]);

  const resetDraft = () => {
    setEditing(false);
    setEditingId(null);
    setName("");
    setSelectedCaseIds([]);
    setSourceCollectionIds([]);
    setCollapsedSelectedCollectionIds([]);
    setCollapsedSearchCollectionIds([]);
    setQuery("");
    setDeduplicatedCount(0);
  };

  const beginNewFromCollection = async (collectionId: string) => {
    const collection = collections.find((item) => item.id === collectionId);
    if (!collection) return;
    setSaving(true);
    onError("");
    try {
      const collectionCases = await listTestCases(collectionId);
      setEditing(true);
      setEditingId(null);
      setName(collection.name);
      setSelectedCaseIds(collectionCases.map((item) => item.id));
      setSourceCollectionIds([collectionId]);
      setAwaitingSeedChoice(false);
      onSelect(null);
    } catch (caught) {
      onError(messageFromError(caught, "用例集合加载失败"));
    } finally {
      setSaving(false);
    }
  };

  useEffect(() => {
    let ignored = false;
    Promise.all([
      listPlaylists(spaceId),
      searchSpaceTestCases(spaceId),
      creationSessionId
        ? getPlaylistCreationSession(creationSessionId)
        : Promise.resolve(null),
    ])
      .then(([playlistItems, caseItems, creationSession]) => {
        if (ignored) return;
        setPlaylists(playlistItems);
        setAllCases(caseItems);
        resetDraft();
        if (creationSession) {
          if (creationSession.space_id !== spaceId) {
            onError("Playlist 创建会话不属于当前空间。");
            return;
          }
          const requestedCaseIds = new Set(creationSession.playlist.case_ids ?? []);
          setName(creationSession.playlist.name ?? "");
          setSelectedCaseIds(
            caseItems
              .filter(
                (item) => requestedCaseIds.has(item.id) || requestedCaseIds.has(item.case_key),
              )
              .map((item) => item.id),
          );
          setSourceCollectionIds(
            creationSession.case_collections.map((item) => item.collection_id),
          );
          setCreationDraft({
            description: creationSession.playlist.description ?? "",
            executionNotes: creationSession.playlist.execution_notes ?? "",
          });
          setEditing(true);
          setEditingId(null);
          setAwaitingSeedChoice(false);
          onSelect(null);
          return;
        }
        const matching = seedCollectionId
          ? playlistItems.filter((item) =>
              item.source_collection_ids.includes(seedCollectionId),
            )
          : [];
        if (matching.length) {
          setAwaitingSeedChoice(true);
          onSelect(null);
        } else if (seedCollectionId) {
          void beginNewFromCollection(seedCollectionId);
        } else {
          setAwaitingSeedChoice(false);
          onSelect(playlistItems[0] ?? null);
        }
      })
      .catch((caught) => {
        if (!ignored) onError(messageFromError(caught, "Playlist 加载失败"));
      })
      .finally(() => {
        if (!ignored) setLoading(false);
      });
    return () => {
      ignored = true;
    };
    // requestId intentionally resets the picker for each navigation request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [creationSessionId, requestId, spaceId]);

  const editPlaylist = (playlist: PlaylistDto) => {
    setEditing(true);
    setEditingId(playlist.id);
    setName(playlist.name);
    setSelectedCaseIds(playlist.cases.map((item) => item.case_id));
    setSourceCollectionIds(playlist.source_collection_ids);
    setAwaitingSeedChoice(false);
    setDeduplicatedCount(0);
    onSelect(playlist);
  };

  const addCollection = async (collectionId: string) => {
    setSaving(true);
    onError("");
    try {
      const collectionCases = await listTestCases(collectionId);
      const existing = new Set(selectedCaseIds);
      const duplicates = collectionCases.filter((item) => existing.has(item.id)).length;
      setDeduplicatedCount((count) => count + duplicates);
      setSelectedCaseIds([
        ...selectedCaseIds,
        ...collectionCases.map((item) => item.id).filter((id) => !existing.has(id)),
      ]);
      setSourceCollectionIds((current) =>
        current.includes(collectionId) ? current : [...current, collectionId],
      );
    } catch (caught) {
      onError(messageFromError(caught, "用例集合加载失败"));
    } finally {
      setSaving(false);
    }
  };

  const toggleCase = (testCase: TestCaseDto) => {
    if (selectedCaseIds.includes(testCase.id)) {
      setSelectedCaseIds((current) => current.filter((id) => id !== testCase.id));
    } else {
      setSourceCollectionIds((sourceIds) => [
        ...sourceIds,
        ...testCase.collection_ids.filter((id) => !sourceIds.includes(id)),
      ]);
      setSelectedCaseIds((current) => [...current, testCase.id]);
    }
  };

  const toggleCollapsed = (
    collectionId: string,
    setCollapsedIds: Dispatch<SetStateAction<string[]>>,
  ) => {
    setCollapsedIds((current) =>
      current.includes(collectionId)
        ? current.filter((id) => id !== collectionId)
        : [...current, collectionId],
    );
  };

  const save = async () => {
    if (!name.trim()) {
      onError("请填写 Playlist 名称。");
      return;
    }
    if (!selectedCaseIds.length) {
      onError("请至少选择一条可执行用例。");
      return;
    }
    setSaving(true);
    onError("");
    try {
      const selectedCases = allCases.filter((item) => selectedCaseIds.includes(item.id));
      const resolvedSourceCollectionIds = [
        ...new Set([
          ...sourceCollectionIds.filter((id) =>
            collections.some((collection) => collection.id === id),
          ),
          ...selectedCases.flatMap((item) => item.collection_ids),
        ]),
      ];
      const payload = {
        name: name.trim(),
        case_ids: selectedCaseIds,
        source_collection_ids: resolvedSourceCollectionIds,
      };
      let saved: PlaylistDto;
      if (creationSessionId && !editingId) {
        const completed = await completePlaylistCreation(creationSessionId, {
          name: name.trim(),
          description: creationDraft.description,
          execution_notes: creationDraft.executionNotes,
          case_ids: selectedCaseIds,
        });
        const refreshed = await listPlaylists(spaceId);
        const created = refreshed.find(
          (item) => item.id === completed.playlist.playlist_id,
        );
        if (!created) throw new Error("playlist_not_found");
        saved = created;
      } else {
        saved = editingId
          ? await updatePlaylist(editingId, payload)
          : await createPlaylist(spaceId, payload);
      }
      const next = editingId
        ? playlists.map((item) => (item.id === saved.id ? saved : item))
        : [saved, ...playlists];
      setPlaylists(next);
      setEditing(false);
      setEditingId(null);
      onSelect(saved);
    } catch (caught) {
      onError(messageFromError(caught, "Playlist 保存失败"));
    } finally {
      setSaving(false);
    }
  };

  const remove = async (playlist: PlaylistDto) => {
    if (!window.confirm(`确定删除 Playlist“${playlist.name}”吗？历史任务不会受影响。`)) {
      return;
    }
    setSaving(true);
    onError("");
    try {
      await deletePlaylist(playlist.id);
      const next = playlists.filter((item) => item.id !== playlist.id);
      setPlaylists(next);
      if (selectedPlaylistId === playlist.id) onSelect(next[0] ?? null);
      if (editingId === playlist.id) resetDraft();
    } catch (caught) {
      onError(messageFromError(caught, "Playlist 删除失败"));
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div className="playlist-loading"><LoaderCircle className="auth-spinner" size={18} />正在加载 Playlist…</div>;
  }

  if (awaitingSeedChoice) {
    return (
      <section className="playlist-seed-choice">
        <strong>当前集合已有可复用 Playlist</strong>
        <p>选择已有 Playlist，或按集合当前内容重新创建。</p>
        <div>
          {matchingPlaylists.map((playlist) => (
            <button key={playlist.id} type="button" onClick={() => { setAwaitingSeedChoice(false); onSelect(playlist); }}>
              <Check size={15} /> 复用 {playlist.name} · {playlist.case_count} 条
            </button>
          ))}
          <button type="button" onClick={() => void beginNewFromCollection(seedCollectionId)}>
            <ListPlus size={15} /> 按当前集合重新创建
          </button>
        </div>
      </section>
    );
  }

  return (
    <div className="playlist-picker">
      <div className="playlist-picker__saved">
        <div className="playlist-picker__title">
          <div><strong>执行 Playlist *</strong><span>保存明确用例清单，可反复创建任务</span></div>
          <button type="button" onClick={() => { resetDraft(); setEditing(true); onSelect(null); }}>
            <ListPlus size={15} /> 新建 Playlist
          </button>
        </div>
        {!playlists.length ? (
          <p className="playlist-empty">暂无 Playlist，请先创建。</p>
        ) : (
          <div className="playlist-saved-list">
            {playlists.map((playlist) => (
              <div key={playlist.id} className={playlist.id === selectedPlaylistId ? "is-active" : ""}>
                <button type="button" onClick={() => { setEditing(false); onSelect(playlist); }}>
                  <strong>{playlist.name}</strong>
                  <span>来自 {playlist.source_collection_ids.length} 个集合 · {playlist.case_count} 条用例</span>
                  {playlist.unavailable_case_ids.length > 0 && <em>{playlist.unavailable_case_ids.length} 条不可用</em>}
                </button>
                <button type="button" aria-label={`编辑 ${playlist.name}`} onClick={() => editPlaylist(playlist)}><PencilLine size={15} /></button>
                <button type="button" aria-label={`删除 ${playlist.name}`} onClick={() => void remove(playlist)}><Trash2 size={15} /></button>
              </div>
            ))}
          </div>
        )}
      </div>

      {editing && (
        <section className="playlist-editor">
          <label>
            Playlist 名称 *
            <input value={name} maxLength={160} onChange={(event) => setName(event.target.value)} placeholder="例如：账号登录回归" />
          </label>
          <section className="playlist-selected-picker">
            <header>
              <div>
                <strong>已选择的用例</strong>
                <span>按一级用例集合、二级用例展示</span>
              </div>
              <span>{selectedCaseIds.length} 条已选</span>
            </header>
            <div className="playlist-selected-tree">
              {unavailableSelectedCaseIds.length > 0 && (
                <article className="is-unavailable">
                  <div className="playlist-tree__collection playlist-tree__collection--static">
                    <span><Layers3 size={16} /><strong>不可用用例</strong></span>
                  </div>
                  <div className="playlist-tree__cases">
                    {unavailableSelectedCaseIds.map((caseId) => (
                      <label key={caseId}>
                        <input
                          type="checkbox"
                          checked
                          onChange={() =>
                            setSelectedCaseIds((current) => current.filter((id) => id !== caseId))
                          }
                        />
                        <span><code>{caseId}</code><strong>用例已删除或不可执行</strong><small>取消选择后才能保存 Playlist</small></span>
                      </label>
                    ))}
                  </div>
                </article>
              )}
              {selectedCaseGroups.map((group) => {
                const expanded = !collapsedSelectedCollectionIds.includes(group.collectionId);
                return (
                  <article key={group.collectionId}>
                    <div className="playlist-tree__collection playlist-tree__collection--selected">
                      <button
                        className="playlist-tree__toggle"
                        type="button"
                        aria-expanded={expanded}
                        onClick={() => toggleCollapsed(group.collectionId, setCollapsedSelectedCollectionIds)}
                      >
                        {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                        <Layers3 size={16} />
                        <span><strong>{group.collectionName}</strong><small>{group.cases.length} 条已选</small></span>
                      </button>
                    </div>
                    {expanded ? (
                      <CaseSelectionRows
                        cases={group.cases}
                        selectedCaseIds={selectedCaseIdSet}
                        onToggle={toggleCase}
                      />
                    ) : null}
                  </article>
                );
              })}
              {!selectedCaseGroups.length && !unavailableSelectedCaseIds.length ? (
                <p>尚未选择用例，请从下方搜索结果中加入</p>
              ) : null}
            </div>
          </section>

          <section className="playlist-case-picker">
            <header>
              <div>
                <strong>搜索并选择用例</strong>
                <span>按一级用例集合、二级用例展示</span>
              </div>
              <label>
                <Search size={16} />
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="搜索用例集合、名称、编号、模块或标签"
                />
              </label>
            </header>
            <div className="playlist-case-tree">
              {caseGroups.map((group) => {
                const expanded = !collapsedSearchCollectionIds.includes(group.collectionId);
                const collectionCases = casesByCollectionId.get(group.collectionId) ?? [];
                const selectedCount = collectionCases.filter((testCase) =>
                  selectedCaseIdSet.has(testCase.id),
                ).length;
                return (
                  <article key={group.collectionId}>
                    <div className="playlist-tree__collection">
                      <button
                        className="playlist-tree__toggle"
                        type="button"
                        aria-expanded={expanded}
                        onClick={() => toggleCollapsed(group.collectionId, setCollapsedSearchCollectionIds)}
                      >
                        {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                        <Layers3 size={16} />
                        <span>
                          <strong>{group.collectionName}</strong>
                          <small>{group.cases.length} 条匹配{collectionCases.length ? ` · ${selectedCount} / ${collectionCases.length} 条已选` : ""}</small>
                        </span>
                      </button>
                      {group.collectionId !== "unassigned" ? (
                        <button
                          className="playlist-tree__add"
                          type="button"
                          disabled={saving || !collectionCases.length}
                          onClick={() => void addCollection(group.collectionId)}
                        >
                          <ListPlus size={14} /> 完整加入
                        </button>
                      ) : null}
                    </div>
                    {expanded ? (
                      <CaseSelectionRows
                        cases={group.cases}
                        selectedCaseIds={selectedCaseIdSet}
                        onToggle={toggleCase}
                      />
                    ) : null}
                  </article>
                );
              })}
              {!caseGroups.length && <p>没有匹配的用例</p>}
            </div>
          </section>
          <footer>
            <span>已选 {selectedCaseIds.length} 条{deduplicatedCount ? ` · 已自动去重 ${deduplicatedCount} 条` : ""}</span>
            <div>
              <button type="button" onClick={resetDraft}>取消</button>
              <button type="button" className="management-button management-button--primary" disabled={saving} onClick={() => void save()}>
                {saving && <LoaderCircle className="auth-spinner" size={15} />} 保存 Playlist
              </button>
            </div>
          </footer>
        </section>
      )}
    </div>
  );
}
