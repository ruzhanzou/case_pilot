"use client";

import type { CaseCollectionDto } from "@/lib/casepilot-api";
import { useI18n } from "@/lib/i18n";
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
  const { pick } = useI18n();
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
            <span className="management-kicker">{pick("Case collection", "用例集合")}</span>
            <h2 id="collection-editor-title">
              {collection ? pick("Edit collection", "编辑用例集合") : pick("Create collection", "创建用例集合")}
            </h2>
          </div>
          <button
            type="button"
            className="management-icon-button"
            onClick={onClose}
            aria-label={pick("Close editor", "关闭编辑窗口")}
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
              <strong>{collection ? pick("Update collection details", "调整集合信息") : pick("Create an independent case workspace", "建立独立的用例工作区")}</strong>
              <p>
                {collection
                  ? pick("Changing the name or scope does not affect existing cases or execution records.", "修改名称和覆盖范围不会影响集合内已有用例及执行记录。")
                  : pick("After creation, add cases or go directly to QA execution.", "创建后可继续添加用例，也可以直接进入 QA 执行页面。")}
              </p>
            </div>
          </div>
          <label>
            {pick("Collection name", "集合名称")}
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={pick("e.g. Account login regression", "例如：账号登录回归集")}
              autoFocus
              required
            />
          </label>
          <label>
            {pick("Description", "集合说明")}
            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder={pick("Describe scope and intended use", "说明覆盖范围与使用方式")}
              rows={4}
            />
          </label>
          <footer className="management-modal__footer">
            <button type="button" className="management-button" onClick={onClose}>
              {pick("Cancel", "取消")}
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
                {pick("Create and execute", "创建并进入执行")} <ArrowRight size={15} />
              </button>
            )}
            <button
              type="submit"
              className="management-button management-button--primary"
              disabled={saving}
            >
              {saving && <LoaderCircle className="auth-spinner" size={16} />}
              {collection ? pick("Save changes", "保存修改") : pick("Create collection", "创建集合")}
            </button>
          </footer>
        </form>
      </section>
    </div>
  );
}
