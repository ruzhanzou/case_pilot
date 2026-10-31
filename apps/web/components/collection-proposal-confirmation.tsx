"use client";
import { useLayoutEffect, useRef, useState } from "react";
import { confirmWorkbenchCollectionProposal, rejectWorkbenchCollectionProposal } from "@/lib/casepilot-api";
import { useI18n } from "@/lib/i18n";
import { collectionReceiptMatches, parseCollectionProposal } from "@/lib/workbench-collection-proposal";

export function CollectionProposalConfirmation({ value, conversationId, busy, onResolved }: { value: unknown; conversationId: string; busy: boolean; onResolved: () => Promise<void> }) {
  const { pick } = useI18n();
  const proposal = parseCollectionProposal(value);
  const lock = useRef(false);
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<"confirmed" | "rejected" | null>(null);
  const [error, setError] = useState("");
  const identity = useRef({ active: false });
  const proposalId = proposal?.id;
  useLayoutEffect(() => {
    const current = { active: true };
    identity.current = current;
    return () => { current.active = false; };
  }, [conversationId, proposalId]);
  if (!proposal) return null;
  const resolve = async (approve: boolean) => {
    if (lock.current || busy || result || proposal.status !== "pending") return;
    const current = identity.current;
    const isCurrent = () => current.active && identity.current === current;
    lock.current = true; setPending(true); setError("");
    try {
      if (approve) {
        const collection = await confirmWorkbenchCollectionProposal(conversationId, proposal.id, {name: proposal.name, ...(proposal.collection_id ? {collection_id: proposal.collection_id} : {})});
        if (!isCurrent()) return;
        if (!collectionReceiptMatches(proposal, collection)) throw new Error(pick("Unexpected confirmation result. Refresh before continuing.", "确认结果与方案不一致，请刷新后继续。"));
      } else {
        const response = await rejectWorkbenchCollectionProposal(conversationId, proposal.id);
        if (!isCurrent()) return;
        if (response.status !== "rejected") throw new Error(pick("Rejection not confirmed. Refresh before continuing.", "尚未确认拒绝，请刷新后继续。"));
      }
      setResult(approve ? "confirmed" : "rejected");
      try { await onResolved(); } catch { if (isCurrent()) setError(pick("Decision saved, but the latest view could not be loaded. Refresh to continue.", "决定已保存，但最新视图加载失败，请刷新后继续。")); }
    } catch (caught) { if (isCurrent()) setError(caught instanceof Error ? caught.message : pick("Could not confirm. Refresh and review the latest proposal.", "确认未完成，请刷新后检查最新方案。")); }
    finally { if (isCurrent()) { setPending(false); lock.current = false; } }
  };
  return <section className="conversation-plan-approval" aria-label={pick("Collection change confirmation", "集合变更确认")}>
    <strong>{proposal.action === "create" ? pick("Create collection", "创建集合") : proposal.action === "delete" ? pick("Soft-delete collection", "软删除集合") : pick("Rename collection", "重命名集合")}</strong>
    {proposal.action === "delete" ? <>
      <p>{pick("Collection", "集合")}：<strong>{proposal.name}</strong></p>
      <p>{pick("Case assets are preserved. Linked conversations will be detached from this collection.", "保留用例资产；关联会话将与此集合解绑。")}</p>
      <p>{pick("Member cases", "集合用例")}：{proposal.impact?.member_case_count} · {pick("Affected conversations", "受影响会话")}：{proposal.impact?.affected_conversation_count}</p>
      <small>{pick("Confirm soft-deletion of this exact collection. You will stay in this conversation; no other collection is selected.", "仅确认软删除此集合。保留当前对话，不会切换到其他集合。")}</small>
    </> : <>
      {proposal.base_name && <p>{pick("Current name", "原名称")}：{proposal.base_name}</p>}
      <p>{pick("New name", "新名称")}：<strong>{proposal.name}</strong></p>
      <small>{pick("Confirm this exact proposal. It does not switch your current collection.", "确认这份具体方案，不会自动切换当前集合。")}</small>
    </>}
    {result ? <p role="status">{result === "confirmed" ? pick("Collection change confirmed by the server.", "服务器已确认集合变更。") : pick("Proposal rejected. No collection change applied.", "方案已拒绝，未应用集合变更。")}</p> : proposal.status === "pending" && <div>
      <button type="button" disabled={busy || pending} onClick={() => void resolve(false)}>{pick("Reject", "拒绝")}</button>
      <button type="button" disabled={busy || pending} onClick={() => void resolve(true)}>{pending ? pick("Submitting…", "提交中…") : proposal.action === "delete" ? pick("Confirm soft-delete", "确认软删除") : pick("Confirm collection change", "确认集合变更")}</button>
    </div>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
