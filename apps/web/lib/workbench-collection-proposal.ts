import type { CaseCollectionDto } from "./casepilot-api";
export type DeletedCollectionReceipt = { action: "delete"; collection_id: string; name: string; deleted: true; preserved_assets: true };
export type CollectionConfirmationReceipt = CaseCollectionDto | DeletedCollectionReceipt;
export type CollectionProposal = { id: string; status: string; action: "create" | "rename" | "delete"; name: string; collection_id?: string; base_name?: string; selection_version: number; impact?: { member_case_count: number; affected_conversation_count: number } };
export function parseCollectionProposal(value: unknown): CollectionProposal | null {
  if (!value || typeof value !== "object") return null;
  const proposal = value as CollectionProposal;
  if (typeof proposal.id !== "string" || !proposal.id || typeof proposal.name !== "string" || !proposal.name || typeof proposal.status !== "string" || !Number.isSafeInteger(proposal.selection_version)) return null;
  if (!["create", "rename", "delete"].includes(proposal.action)) return null;
  if (proposal.action !== "create" && (typeof proposal.collection_id !== "string" || !proposal.collection_id)) return null;
  if (proposal.action === "delete" && (!proposal.impact || ![proposal.impact.member_case_count, proposal.impact.affected_conversation_count].every(count => Number.isSafeInteger(count) && count >= 0))) return null;
  return proposal;
}
export function collectionReceiptMatches(proposal: CollectionProposal, receipt: CollectionConfirmationReceipt): boolean {
  if (proposal.action === "delete") return "action" in receipt && receipt.action === "delete"
    && receipt.collection_id === proposal.collection_id && receipt.name === proposal.name
    && receipt.deleted === true && receipt.preserved_assets === true;
  return "id" in receipt && !!receipt.id && receipt.name === proposal.name
    && (proposal.action !== "rename" || receipt.id === proposal.collection_id);
}

/** Catalog refresh must not choose another collection when the destination disappears. */
export function collectionDecisionDestination(currentId: string, collections: { id: string }[]): string {
  return collections.some(collection => collection.id === currentId) ? currentId : "";
}

/** Both reads finish before applying any state; navigation invalidates the whole result. */
export async function loadCollectionDecisionSnapshot<C, W>(options: {
  isCurrent: () => boolean; loadCollections: () => Promise<C>; loadConversation: () => Promise<W>;
  apply: (collections: C, conversation: W) => void;
}): Promise<void> {
  if (!options.isCurrent()) return;
  const [collections, conversation] = await Promise.all([options.loadCollections(), options.loadConversation()]);
  if (options.isCurrent()) options.apply(collections, conversation);
}
