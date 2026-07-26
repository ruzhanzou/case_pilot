"use client";

import { Archive, ArrowLeft, ArrowRight, Check, FileSpreadsheet, FolderOpen, History, Pencil, Play, Plus, Search, Sparkles, Tag, Trash2, Upload, Workflow, X } from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useMemo, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { CaseStatusBadge } from "@/components/case-status";
import type { TestCase } from "@/lib/mock-data";

export type CaseCollection = {
  id: string;
  name: string;
  description: string;
  count: number;
  source: "AI 生成" | "Excel 导入" | "人工维护";
  updated: string;
};

export const initialCaseCollections: CaseCollection[] = [
  { id: "col-payment", name: "支付结算回归集", description: "覆盖结算、优惠计算、支付回调与退款链路", count: 24, source: "AI 生成", updated: "刚刚" },
  { id: "col-smoke", name: "商城 P0 冒烟用例", description: "每次生产发布前执行的关键路径集合", count: 36, source: "人工维护", updated: "昨天" },
  { id: "col-history", name: "历史功能用例 2024", description: "从原测试资产 Excel 整理导入", count: 862, source: "Excel 导入", updated: "3 天前" },
];

type CollectionPreviewCase = {
  id: string;
  title: string;
  priority: "P0" | "P1" | "P2";
  module: string;
  status: TestCase["status"];
  tags: string[];
  automated: boolean;
};

const initialCollectionPreviewCases: CollectionPreviewCase[] = [
  { id: "PAY-008", title: "支付成功后重复回调的幂等处理", priority: "P0", module: "支付回调", status: "Pending", tags: ["支付", "幂等"], automated: true },
  { id: "ORD-014", title: "优惠券与会员折扣叠加上限校验", priority: "P1", module: "订单结算", status: "不通过", tags: ["优惠", "边界"], automated: false },
  { id: "PAY-003", title: "银行卡支付成功并刷新订单状态", priority: "P0", module: "支付回调", status: "通过", tags: ["主流程"], automated: true },
];

function ExcelImportDialog({ onClose, onImported }: { onClose: () => void; onImported: (collection: CaseCollection) => void }) {
  const [step, setStep] = useState<0 | 1 | 2>(0);
  const [fileName, setFileName] = useState("");
  const [importing, setImporting] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const importTimerRef = useRef<number | null>(null);

  useEffect(() => () => {
    if (importTimerRef.current !== null) window.clearTimeout(importTimerRef.current);
  }, []);

  const prepareExample = () => {
    setFileName("历史测试用例汇总_2024.xlsx");
    setStep(1);
  };

  const runImport = () => {
    setImporting(true);
    importTimerRef.current = window.setTimeout(() => {
      setImporting(false);
      setStep(2);
      onImported({ id: crypto.randomUUID(), name: "历史用例导入批次", description: `来自 ${fileName}`, count: 1214, source: "Excel 导入", updated: "刚刚" });
    }, 900);
  };

  return (
    <motion.div className="account-overlay" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <motion.section className="excel-import" initial={{ opacity: 0, scale: .98, y: 12 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: .98, y: 8 }} role="dialog" aria-modal="true" aria-labelledby="excel-title">
        <header><div><span className="eyebrow">HISTORICAL CASE MIGRATION</span><h2 id="excel-title">导入 Excel 历史用例</h2></div><button type="button" onClick={onClose} aria-label="关闭 Excel 导入"><X size={17} /></button></header>
        <div className="import-steps"><span className={step >= 0 ? "is-active" : ""}>1 上传文件</span><i /><span className={step >= 1 ? "is-active" : ""}>2 字段映射</span><i /><span className={step >= 2 ? "is-active" : ""}>3 导入结果</span></div>

        {step === 0 && (
          <div className="excel-upload">
            <input ref={inputRef} type="file" accept=".xlsx,.xls,.csv" onChange={(event) => { const file = event.target.files?.[0]; if (file) { setFileName(file.name); setStep(1); } }} />
            <div className="excel-upload__icon"><FileSpreadsheet size={28} /></div>
            <h3>选择历史用例文件</h3>
            <p>支持 .xlsx、.xls、.csv，单文件最多 50,000 行；原文件会作为导入凭证保留。</p>
            <button type="button" onClick={() => inputRef.current?.click()}><Upload size={15} />选择 Excel 文件</button>
            <button className="text-button" type="button" onClick={prepareExample}>使用示例文件体验</button>
          </div>
        )}

        {step === 1 && (
          <div className="mapping-view">
            <div className="mapping-file"><FileSpreadsheet size={18} /><span><strong>{fileName}</strong><small>工作表：功能用例 · 1,286 行</small></span><button type="button" onClick={() => setStep(0)}>更换文件</button></div>
            <div className="mapping-summary"><span><b>1,214</b> 可导入</span><span><b>42</b> 疑似重复</span><span><b>30</b> 待修复</span></div>
            <div className="mapping-title"><strong>字段映射</strong><span>已自动识别 7 / 8 个字段</span></div>
            <div className="mapping-table">
              {[['用例标题','用例名称','必填'],['前置条件','前置步骤','必填'],['操作步骤','执行步骤','必填'],['预期结果','校验点','必填'],['模块','所属模块',''],['优先级','优先级',''],['需求编号','需求追踪','']].map(([excel, field, required]) => (
                <div key={excel}><span>{excel}</span><ArrowRight size={13} /><select defaultValue={field} aria-label={`${excel} 映射字段`}><option>{field}</option><option>不导入</option></select>{required && <b>{required}</b>}</div>
              ))}
            </div>
            <label className="mapping-option"><input type="checkbox" defaultChecked />按“用例编号 + 名称”识别重复项，重复内容导入为新修订</label>
            <footer><button type="button" onClick={() => setStep(0)}>上一步</button><button className="button-primary" type="button" disabled={importing} onClick={runImport}>{importing ? "正在导入…" : "确认导入 1,214 条"}</button></footer>
          </div>
        )}

        {step === 2 && (
          <div className="import-complete">
            <span><Check size={25} /></span><h3>历史用例导入完成</h3><p>已创建“历史用例导入批次”，原始文件、映射配置和问题行均已保存。</p>
            <div><strong>1,214<small>成功导入</small></strong><strong>42<small>生成新修订</small></strong><strong>30<small>进入待修复</small></strong></div>
            <button type="button" onClick={onClose}>查看用例集合</button>
          </div>
        )}
      </motion.section>
    </motion.div>
  );
}

type CaseCollectionsProps = {
  collections: CaseCollection[];
  setCollections: Dispatch<SetStateAction<CaseCollection[]>>;
  onBack: () => void;
  onCreateWithAI: () => void;
  onOpenCollection: (collection: CaseCollection) => void;
  onExecuteCollection: (collection: CaseCollection) => void;
};

export function CaseCollections({
  collections,
  setCollections,
  onBack,
  onCreateWithAI,
  onOpenCollection,
  onExecuteCollection,
}: CaseCollectionsProps) {
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState(collections[0]?.id ?? "");
  const [editor, setEditor] = useState<CaseCollection | "new" | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [previewCases, setPreviewCases] = useState(initialCollectionPreviewCases);
  const [selectedCaseIds, setSelectedCaseIds] = useState<Set<string>>(() => new Set());
  const [tagEditorId, setTagEditorId] = useState<string | null>(null);
  const [tagDraft, setTagDraft] = useState("");
  const [bulkTagging, setBulkTagging] = useState(false);
  const [bulkDeleteArmed, setBulkDeleteArmed] = useState(false);
  const visibleCollections = useMemo(() => collections.filter((item) => `${item.name}${item.description}`.toLowerCase().includes(query.toLowerCase())), [collections, query]);
  const selected = collections.find((item) => item.id === selectedId) ?? collections[0];
  const allPreviewCasesSelected = previewCases.length > 0 && selectedCaseIds.size === previewCases.length;

  const toggleCaseSelection = (id: string) => {
    setSelectedCaseIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
    setBulkDeleteArmed(false);
  };

  const applyTag = (ids: Set<string>, tag: string) => {
    const normalized = tag.trim().slice(0, 12);
    if (!normalized) return;
    setPreviewCases((current) => current.map((item) =>
      ids.has(item.id) && !item.tags.includes(normalized)
        ? { ...item, tags: [...item.tags, normalized] }
        : item,
    ));
    setTagDraft("");
    setTagEditorId(null);
    setBulkTagging(false);
  };

  const deleteSelectedCases = () => {
    setPreviewCases((current) => current.filter((item) => !selectedCaseIds.has(item.id)));
    setSelectedCaseIds(new Set());
    setBulkDeleteArmed(false);
  };

  const saveCollection = (formData: FormData) => {
    const name = String(formData.get("name") || "").trim();
    const description = String(formData.get("description") || "").trim();
    if (!name) return;
    if (editor === "new") {
      const next = { id: crypto.randomUUID(), name, description, count: 0, source: "人工维护" as const, updated: "刚刚" };
      setCollections((current) => [...current, next]);
      setSelectedId(next.id);
      onOpenCollection(next);
    } else if (editor) {
      setCollections((current) => current.map((item) => item.id === editor.id ? { ...item, name, description, updated: "刚刚" } : item));
    }
    setEditor(null);
  };

  return (
    <div className="collection-view">
      <div className="collection-toolbar">
        <div className="collection-toolbar__title">
          <button className="collection-back" type="button" onClick={onBack} aria-label="返回开始设计"><ArrowLeft size={18} /></button>
          <div><h3>用例集管理</h3><p>查看和管理当前空间中的全部用例集合。</p></div>
        </div>
        <div>
          <button type="button" onClick={onCreateWithAI}><Sparkles size={15} />AI 创建</button>
          <button type="button" onClick={() => setImportOpen(true)}><Upload size={15} />导入 Excel</button>
          <button className="button-primary" type="button" onClick={() => setEditor("new")}><Plus size={15} />空白创建</button>
        </div>
      </div>
      <div className="collection-layout">
        <aside>
          <label className="collection-search"><Search size={14} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索用例集合" /></label>
          <div className="collection-list">
            {visibleCollections.map((item) => (
              <button className={selectedId === item.id ? "is-active" : ""} type="button" key={item.id} onClick={() => setSelectedId(item.id)}>
                <span><FolderOpen size={16} /></span><span><strong>{item.name}</strong><small>{item.count.toLocaleString()} 条用例 · {item.source}</small></span>
              </button>
            ))}
          </div>
        </aside>

        {selected && <section className="collection-detail">
          <header>
            <div className="collection-detail__icon"><Archive size={20} /></div>
            <div><span>用例集合</span><h4>{selected.name}</h4><p>{selected.description}</p></div>
            <div>
              <button className="collection-execute" type="button" onClick={() => onExecuteCollection(selected)}><Play size={14} />开始执行</button>
              <button className="collection-open" type="button" onClick={() => onOpenCollection(selected)}>进入工作台<ArrowRight size={15} /></button>
              <button type="button" onClick={() => setEditor(selected)}><Pencil size={14} />编辑</button>
              <button type="button" onClick={() => setDeleteTarget(selected.id)}><Trash2 size={14} />删除</button>
            </div>
          </header>
          {deleteTarget === selected.id && <div className="collection-delete"><span>确认删除该集合？集合内用例将移入“未归类”，不会直接删除。</span><button type="button" onClick={() => setDeleteTarget(null)}>取消</button><button type="button" onClick={() => { const remaining = collections.filter((item) => item.id !== selected.id); setCollections(remaining); setSelectedId(remaining[0]?.id || ""); setDeleteTarget(null); }}>确认删除</button></div>}
          <div className="collection-stats"><div><strong>{selected.count.toLocaleString()}</strong><span>用例总数</span></div><div><strong>{selected.source}</strong><span>主要来源</span></div><div><strong>{selected.updated}</strong><span>最后更新</span></div><div><strong>87%</strong><span>字段完整度</span></div></div>
          <div className="collection-section-title"><strong>最近用例</strong><button type="button">查看全部<ArrowRight size={13} /></button></div>
          {selectedCaseIds.size > 0 && (
            <div className="case-bulk-actions">
              <strong>已选择 {selectedCaseIds.size} 条</strong>
              {bulkTagging ? (
                <form onSubmit={(event) => { event.preventDefault(); applyTag(selectedCaseIds, tagDraft); }}>
                  <input value={tagDraft} onChange={(event) => setTagDraft(event.target.value)} placeholder="输入标签" autoFocus />
                  <button type="submit">应用</button>
                  <button type="button" onClick={() => setBulkTagging(false)}>取消</button>
                </form>
              ) : (
                <button type="button" onClick={() => setBulkTagging(true)}><Tag size={13} />添加标签</button>
              )}
              <button className={bulkDeleteArmed ? "is-danger" : ""} type="button" onClick={() => bulkDeleteArmed ? deleteSelectedCases() : setBulkDeleteArmed(true)}>
                <Trash2 size={13} />{bulkDeleteArmed ? "确认删除" : "删除用例"}
              </button>
              {bulkDeleteArmed && <button type="button" onClick={() => setBulkDeleteArmed(false)}>取消</button>}
            </div>
          )}
          <div className="collection-cases-wrap">
            <table className="collection-cases">
              <thead><tr>
                <th><input type="checkbox" aria-label="选择全部最近用例" checked={allPreviewCasesSelected} onChange={() => setSelectedCaseIds(allPreviewCasesSelected ? new Set() : new Set(previewCases.map((item) => item.id)))} /></th>
                <th>编号</th><th>用例名称</th><th>优先级</th><th>模块</th><th>状态</th><th>标签与自动化</th>
              </tr></thead>
              <tbody>
                {previewCases.map((item) => (
                  <tr className={selectedCaseIds.has(item.id) ? "is-selected" : ""} key={item.id}>
                    <td><input type="checkbox" aria-label={`选择 ${item.id}`} checked={selectedCaseIds.has(item.id)} onChange={() => toggleCaseSelection(item.id)} /></td>
                    <td>{item.id}</td>
                    <td>{item.title}</td>
                    <td><span className={`priority priority--${item.priority.toLowerCase()}`}>{item.priority}</span></td>
                    <td>{item.module}</td>
                    <td><CaseStatusBadge status={item.status} compact /></td>
                    <td>
                      <div className="editable-tags">
                        {item.tags.map((tag) => (
                          <button
                            className="case-tag"
                            type="button"
                            title={`移除标签 ${tag}`}
                            key={tag}
                            onClick={() => setPreviewCases((current) => current.map((candidate) => candidate.id === item.id ? { ...candidate, tags: candidate.tags.filter((value) => value !== tag) } : candidate))}
                          >
                            {tag}<X size={10} />
                          </button>
                        ))}
                        {item.automated ? <span className="automation-badge"><Workflow size={11} />已绑定</span> : <span className="automation-empty">未绑定</span>}
                        <button className="add-case-tag" type="button" onClick={() => { setTagEditorId(item.id); setTagDraft(""); }}><Plus size={11} />标签</button>
                        {tagEditorId === item.id && (
                          <form className="inline-tag-editor" onSubmit={(event) => { event.preventDefault(); applyTag(new Set([item.id]), tagDraft); }}>
                            <input value={tagDraft} onChange={(event) => setTagDraft(event.target.value)} placeholder="标签名称" autoFocus />
                            <button type="submit">添加</button>
                          </form>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="collection-history"><History size={14} /><span>所有新增、编辑、删除和 Excel 导入操作都会记录在集合历史中。</span></div>
        </section>}
      </div>

      {editor && <div className="collection-editor-backdrop" onMouseDown={(event) => event.target === event.currentTarget && setEditor(null)}><form className="collection-editor" action={saveCollection}><div><strong>{editor === "new" ? "新建用例集合" : "编辑用例集合"}</strong><button type="button" onClick={() => setEditor(null)}><X size={16} /></button></div><label>集合名称<input name="name" defaultValue={editor === "new" ? "" : editor.name} autoFocus /></label><label>集合说明<textarea name="description" defaultValue={editor === "new" ? "" : editor.description} /></label><button className="button-primary" type="submit">{editor === "new" ? "创建集合" : "保存修改"}</button></form></div>}
      {importOpen && <ExcelImportDialog onClose={() => setImportOpen(false)} onImported={(collection) => { setCollections((current) => [...current, collection]); setSelectedId(collection.id); }} />}
    </div>
  );
}
