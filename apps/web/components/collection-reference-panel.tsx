"use client";

import { useEffect, useRef, useState } from "react";
import {
  getCollectionReferences, getWorkspaceReferenceContext, getCollectionReferenceOptions,
  updateCollectionReferences,
  type CollectionReferencesDto, type KnowledgeSourceDto, type WorkspaceReferenceContextDto,
} from "@/lib/casepilot-api";

export function CollectionReferencePanel({ spaceId, collectionId, conversationId, revision }: {
  spaceId: string; collectionId: string; conversationId: string; revision: string;
}) {
  const [stored, setStored] = useState<CollectionReferencesDto | null>(null);
  const [catalog, setCatalog] = useState<KnowledgeSourceDto[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [context, setContext] = useState<WorkspaceReferenceContextDto | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [reload, setReload] = useState(0);
  const dirty = useRef(false);
  useEffect(() => {
    let active = true;
    Promise.all([
      getCollectionReferences(collectionId), getCollectionReferenceOptions(collectionId),
      getWorkspaceReferenceContext(conversationId).catch(() => null),
    ]).then(([references, sources, value]) => {
      if (!active) return;
      setCatalog(sources); setContext(value);
      if (!dirty.current) {
        setStored(references); setSelected(references.sources.map(source => source.source_id));
        setError("");
      }
    }).catch(() => { if (active) setError("资料上下文暂不可用，请重新加载。"); });
    return () => { active = false; };
  }, [collectionId, conversationId, spaceId, revision, reload]);

  async function save() {
    if (!stored || stored.collection_id !== collectionId) return;
    setSaving(true); setError("");
    try {
      const result = await updateCollectionReferences(collectionId, stored.version, selected);
      dirty.current = false; setStored(result);
      setContext(await getWorkspaceReferenceContext(conversationId).catch(() => null));
    } catch {
      setError("保存未完成：资料或版本可能已变化。请重新加载后核对，不会自动覆盖新版本。");
    } finally { setSaving(false); }
  }
  return <details className="workbench-reference-files">
    <summary>集合资料与当前上下文 · {stored?.sources.length ?? 0} 份长期资料</summary>
    <p>勾选并保存后，资料会供本集合后续对话使用。对话临时附件不会自动长期绑定。</p>
    <p>当前选择 {context?.selected_cases.length ?? 0} 条；改写将带入完整选中内容。
      {!context && " 上下文尚不可用，不代表没有参考资料。"}</p>
    {context?.sources.map(source => <div key={source.source_id}>
      {source.origin === "collection" ? "集合资料" : "对话附件"}：{source.name}
      {source.documents.map(document => <small key={document.id}>
        {" "}{document.name} · v{document.version}
      </small>)}
    </div>)}
    <p>资料没有按上传时间自动排序的权威性；冲突应列明来源后澄清。</p>
    {context?.warnings.includes("source_consistency_unverified") &&
      <p role="status">多份资料的一致性尚未核验。</p>}
    {stored?.sources.filter(source => !source.available).map(source =>
      <p role="status" key={source.source_id}>{source.name}：不可用，请核对或解除绑定。</p>)}
    {catalog.map(source => <label key={source.id} style={{ display: "block" }}>
      <input type="checkbox" checked={selected.includes(source.id)}
        disabled={saving || (source.status !== "ready" && !selected.includes(source.id))}
        onChange={event => { dirty.current = true; setSelected(current => event.target.checked
          ? [...current, source.id] : current.filter(id => id !== source.id)); }} />
      {source.name}{source.persistence === "temporary" ? "（临时；保存后长期保留）" : ""}
    </label>)}
    {stored?.sources.filter(source => !catalog.some(row => row.id === source.source_id)).map(source =>
      <label key={source.source_id} style={{ display: "block" }}>
        <input type="checkbox" checked={selected.includes(source.source_id)} disabled={saving}
          onChange={event => { dirty.current = true; setSelected(current => event.target.checked
            ? [...current, source.source_id] : current.filter(id => id !== source.source_id)); }} />
        {source.name}（不可用，可解除绑定）
      </label>)}
    <button type="button" disabled={saving} onClick={() => {
      dirty.current = false; setReload(value => value + 1);
    }}>重新读取（放弃未保存选择）</button>
    <button type="button" disabled={saving || !stored} onClick={() => { void save(); }}>
      {saving ? "正在保存…" : "保存集合资料（跨对话）"}
    </button>
    {error && <p role="alert">{error}</p>}
  </details>;
}
