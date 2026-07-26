"use client";

import { ArrowRight, Check, FolderKanban, Pencil, Plus, Trash2, Users, X } from "lucide-react";
import { motion } from "motion/react";
import { useState } from "react";

export type Space = {
  id: string;
  name: string;
  description: string;
  members: number;
  collections: number;
};

export function SpaceManager({ spaces, activeSpaceId, onSelect, onChange, onClose }: {
  spaces: Space[];
  activeSpaceId: string;
  onSelect: (id: string) => void;
  onChange: (spaces: Space[]) => void;
  onClose: () => void;
}) {
  const [editing, setEditing] = useState<Space | "new" | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const saveSpace = (formData: FormData) => {
    const name = String(formData.get("name") || "").trim();
    const description = String(formData.get("description") || "").trim();
    if (!name) return;
    if (editing === "new") {
      const next = { id: crypto.randomUUID(), name, description, members: 1, collections: 0 };
      onChange([...spaces, next]);
      onSelect(next.id);
    } else if (editing) {
      onChange(spaces.map((space) => space.id === editing.id ? { ...space, name, description } : space));
    }
    setEditing(null);
  };

  const deleteSpace = (id: string) => {
    const remaining = spaces.filter((space) => space.id !== id);
    onChange(remaining);
    if (id === activeSpaceId && remaining[0]) onSelect(remaining[0].id);
    setDeleteTarget(null);
  };

  return (
    <motion.div className="account-overlay" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <motion.section className="space-manager" initial={{ opacity: 0, scale: .98, y: 12 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: .98, y: 8 }} role="dialog" aria-modal="true" aria-labelledby="space-title">
        <header>
          <div><span className="eyebrow">WORKSPACE DIRECTORY</span><h2 id="space-title">空间管理</h2><p>空间是成员、需求、用例集合与 AI 会话的统一管理边界。</p></div>
          <button type="button" aria-label="关闭空间管理" onClick={onClose}><X size={17} /></button>
        </header>

        <div className="space-manager__toolbar">
          <span>{spaces.length} 个空间</span>
          <button type="button" onClick={() => setEditing("new")}><Plus size={14} />新建空间</button>
        </div>

        <div className="space-list">
          {spaces.map((space) => (
            <div className={`space-row ${space.id === activeSpaceId ? "is-active" : ""}`} key={space.id}>
              <button className="space-row__main" type="button" onClick={() => { onSelect(space.id); onClose(); }}>
                <span className="space-row__icon"><FolderKanban size={18} /></span>
                <span><strong>{space.name}</strong><small>{space.description}</small><i><Users size={12} />{space.members} 位成员 · {space.collections} 个用例集合</i></span>
                {space.id === activeSpaceId ? <b><Check size={12} />当前空间</b> : <ArrowRight size={15} />}
              </button>
              <div className="space-row__actions">
                <button type="button" aria-label={`编辑 ${space.name}`} onClick={() => setEditing(space)}><Pencil size={14} /></button>
                <button type="button" aria-label={`删除 ${space.name}`} disabled={spaces.length === 1} onClick={() => setDeleteTarget(space.id)}><Trash2 size={14} /></button>
              </div>
              {deleteTarget === space.id && <div className="space-delete"><span>删除后该空间将进入回收站 30 天。</span><button type="button" onClick={() => setDeleteTarget(null)}>取消</button><button type="button" onClick={() => deleteSpace(space.id)}>确认删除</button></div>}
            </div>
          ))}
        </div>

        {editing && (
          <form className="space-editor" action={saveSpace}>
            <div><span>{editing === "new" ? "新建空间" : "编辑空间"}</span><button type="button" onClick={() => setEditing(null)}><X size={15} /></button></div>
            <label>空间名称<input name="name" defaultValue={editing === "new" ? "" : editing.name} placeholder="例如：移动端质量空间" autoFocus /></label>
            <label>空间说明<textarea name="description" defaultValue={editing === "new" ? "" : editing.description} placeholder="说明团队、产品线或测试范围" /></label>
            <button className="space-editor__save" type="submit">{editing === "new" ? "创建空间" : "保存修改"}</button>
          </form>
        )}
      </motion.section>
    </motion.div>
  );
}
