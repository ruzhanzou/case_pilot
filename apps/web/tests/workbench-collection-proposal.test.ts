import assert from "node:assert/strict";
import test from "node:test";
import { parseCollectionProposal } from "../lib/workbench-collection-proposal";
test("only structured exact collection proposals offer approval", () => {
 const base={id:"p",status:"pending",action:"create",name:"Login",selection_version:0};
 assert.equal(parseCollectionProposal(base)?.action,"create");
 assert.equal(parseCollectionProposal({...base,action:"rename"}),null);
 assert.equal(parseCollectionProposal({...base,action:"rename",collection_id:"c"})?.collection_id,"c");
 for(const value of [null,"create collection",{...base,selection_version:undefined},{...base,action:"delete"}]) assert.equal(parseCollectionProposal(value),null);
});

import { collectionReceiptMatches, collectionDecisionDestination, loadCollectionDecisionSnapshot, type CollectionConfirmationReceipt } from "../lib/workbench-collection-proposal";
const deletion = {id:"delete-p",status:"pending",action:"delete",name:"Historical login",collection_id:"c",selection_version:3,impact:{member_case_count:8,affected_conversation_count:2}};
test("delete approval requires exact collection and nonnegative aggregate impact", () => {
  assert.equal(parseCollectionProposal(deletion)?.action,"delete");
  for (const invalid of [ {...deletion,collection_id:""}, {...deletion,impact:undefined}, {...deletion,impact:{member_case_count:-1,affected_conversation_count:2}}, {...deletion,impact:{member_case_count:2,affected_conversation_count:1.5}} ]) assert.equal(parseCollectionProposal(invalid),null);
});
test("delete success requires matching typed server receipt, never a collection DTO", () => {
  const proposal=parseCollectionProposal(deletion)!;
  const receipt={action:"delete",collection_id:"c",name:deletion.name,deleted:true,preserved_assets:true} as const;
  assert.equal(collectionReceiptMatches(proposal,receipt),true);
  for(const invalid of [{...receipt,collection_id:"other"},{...receipt,name:"Other"},{...receipt,deleted:false},{...receipt,preserved_assets:false},{id:"c",name:deletion.name}]) assert.equal(collectionReceiptMatches(proposal,invalid as CollectionConfirmationReceipt),false);
  const rename=parseCollectionProposal({...deletion,action:"rename"})!;
  assert.equal(collectionReceiptMatches(rename,receipt),false);
  assert.equal(collectionReceiptMatches(rename,{id:"other",name:deletion.name} as CollectionConfirmationReceipt),false);
});
test("deleted destination clears without choosing a different collection", () => {
  assert.equal(collectionDecisionDestination("deleted",[{id:"other"}]),"");
  assert.equal(collectionDecisionDestination("other",[{id:"other"}]),"other");
});
function deferred<T>() { let resolve!: (value:T)=>void; const promise=new Promise<T>(done=>{resolve=done;});return {promise,resolve}; }
for (const first of ["catalog","conversation"]) test(`collection confirmation refresh ignores navigation while ${first} resolves first`,async()=>{
  const catalog=deferred<string[]>(), conversation=deferred<{id:string;collection_id:null}>();
  let epoch=1;const captured=epoch; const applied:unknown[]=[];
  const pending=loadCollectionDecisionSnapshot({isCurrent:()=>epoch===captured,loadCollections:()=>catalog.promise,loadConversation:()=>conversation.promise,apply:(...values)=>applied.push(values)});
  if(first==="catalog") catalog.resolve(["other"]); else conversation.resolve({id:"same-thread",collection_id:null});
  await Promise.resolve(); epoch++;
  catalog.resolve(["other"]);conversation.resolve({id:"same-thread",collection_id:null});
  await pending;assert.deepEqual(applied,[]);
});
test("collection confirmation keeps same conversation even with null destination",async()=>{
  const applied:unknown[]=[];
  await loadCollectionDecisionSnapshot({isCurrent:()=>true,loadCollections:async()=>[{id:"other"}],loadConversation:async()=>({id:"same-thread",collection_id:null}),apply:(...values)=>applied.push(values)});
  assert.deepEqual(applied,[[[{id:"other"}],{id:"same-thread",collection_id:null}]]);
});
