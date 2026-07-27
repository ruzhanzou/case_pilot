"use client";

import type { CaseCollectionDto } from "@/lib/casepilot-api";
import { ArrowRight, FolderPlus, LoaderCircle, X } from "lucide-react";
import { useState } from "react";

type CollectionEditorDialogProps = {
  collection: CaseCollectionDto | null;
  saving: boolean;
  onClose: () => void;
  onSave: (
    input: { name: string; description: string },
    startExecution?: boolean,
  ) => Promise<void>;
};

export function CollectionEditorDialog({
  collection,
  saving,
  onClose,
  onSave,
}: CollectionEditorDialogProps) {
  const [name, setName] = useState(collection?.name ?? "");
  const [description, setDescription] = useState(collection?.description ?? "");

  return (
    <div className="management-modal-backdrop" role="presentation">
      <section
        className="management-modal management-modal--small"
        role="dialog"
        aria-modal="true"
        aria-labelledby="collection-editor-title"
      >
        <header className="management-modal__header">
          <div>
            <span className="management-kicker">用例集合</span>
            <h2 id="collection-editor-title">
              {collection ? "编辑用例集合" : "创建用例集合"}
            </h2>
          </div>
          <button
            type="button"
            className="management-icon-button"
            onClick={onClose}
            aria-label="关闭编辑窗口"
          >
            <X size={19} />
          </button>
        </header>
        <form
          className="collection-editor"
          onSubmit={(event) => {
            event.preventDefault();
            if (name.trim()) {
              void onSave({
                name: name.trim(),
                description: description.trim(),
              });
            }
          }}
        >
          <div className="collection-editor__intro">
            <span><FolderPlus size={18} /></span>
            <div>
              <strong>{collection ? "调整集合信息" : "建立独立的用例工作区"}</strong>
              <p>
                {collection
                  ? "修改名称和覆盖范围不会影响集合内已有用例及执行记录。"
                  : "创建后可继续添加用例，也可以直接进入 QA 执行页面。"}
              </p>
            </div>
          </div>
          <label>
            集合名称
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="例如：账号登录回归集"
              autoFocus
              required
            />
          </label>
          <label>
            集合说明
            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="说明覆盖范围与使用方式"
              rows={4}
            />
          </label>
          <footer className="management-modal__footer">
            <button type="button" className="management-button" onClick={onClose}>
              取消
            </button>
            {!collection && (
              <button
                type="button"
                className="management-button"
                disabled={saving || !name.trim()}
                onClick={() =>
                  void onSave(
                    {
                      name: name.trim(),
                      description: description.trim(),
                    },
                    true,
                  )
                }
              >
                创建并进入执行 <ArrowRight size={15} />
              </button>
            )}
            <button
              type="submit"
              className="management-button management-button--primary"
              disabled={saving}
            >
              {saving && <LoaderCircle className="auth-spinner" size={16} />}
              {collection ? "保存修改" : "创建集合"}
            </button>
          </footer>
        </form>
      </section>
    </div>
  );
}
