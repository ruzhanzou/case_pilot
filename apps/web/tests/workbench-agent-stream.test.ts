import assert from "node:assert/strict";
import test from "node:test";
import { parseAgentStreamEvent, watchAgentStream, scopedAgentObserver, releaseAgentRun, type AgentStreamState } from "../lib/workbench-agent-stream";
import type { AgentEvent } from "../lib/workbench-agent-activity";
import { sendConversationMessage } from "../lib/casepilot-api";

class FakeSource extends EventTarget {
  closed = false;
  callbacks: EventListenerOrEventListenerObject[] = [];
  override addEventListener(type: string, callback: EventListenerOrEventListenerObject | null) { if (callback && type === "workbench.activity") this.callbacks.push(callback); super.addEventListener(type, callback); }
  close() { this.closed = true; }
  activity(sequence: number, type: string) { this.dispatchEvent(new MessageEvent("workbench.activity", {data:JSON.stringify({sequence,type})})); }
}
function fixture() {
  const sources: FakeSource[] = [], urls: string[] = [], events: AgentEvent[] = [], states: AgentStreamState[] = [];
  const scheduled = new Map<ReturnType<typeof setTimeout>, () => void>();
  let nextTimer = 0, terminals = 0;
  const close = watchAgentStream({ url:"/conversation/a/agent-runs/r/events", onEvent:event=>events.push(event), onState:state=>states.push(state), onTerminal:()=>{terminals++;},
    createSource: url=>{urls.push(url);const source=new FakeSource();sources.push(source);return source;},
    schedule: fn=>{const id=++nextTimer as unknown as ReturnType<typeof setTimeout>;scheduled.set(id,fn);return id;},clearSchedule:id=>{scheduled.delete(id);},
  });
  const tick=()=>{for(const [id,fn] of [...scheduled]) {scheduled.delete(id);fn();}};
  return {sources,urls,events,states,close,tick,scheduled,terminals:()=>terminals};
}
test("live event parser discards arbitrary content and unsupported event types",()=>{
 assert.deepEqual(parseAgentStreamEvent(JSON.stringify({sequence:1,type:"tool_completed",tool:"query_cases",arguments:{secret:1},text:"Saved everything"})),{sequence:1,type:"tool_completed",tool:"query_cases"});
 for(const data of ["invalid", "null", JSON.stringify({sequence:1,type:"applied"}),JSON.stringify({sequence:1001,type:"run_completed"})]) assert.equal(parseAgentStreamEvent(data),null);
});
test("reconnect resumes cursor, deduplicates replay and refreshes only on actual terminal",()=>{
 const f=fixture();f.sources[0].activity(1,"run_started");f.sources[0].activity(2,"tool_completed");
 assert.equal(f.terminals(),0); f.sources[0].dispatchEvent(new Event("error")); assert.equal(f.sources[0].closed,true); f.tick();
 assert.equal(f.urls[1],"/conversation/a/agent-runs/r/events?cursor=2");
 f.sources[1].activity(2,"tool_completed");f.sources[1].activity(3,"run_awaiting_input");f.sources[1].activity(4,"run_completed");
 assert.deepEqual(f.events.map(e=>e.sequence),[1,2,3]);assert.equal(f.terminals(),1);assert.equal(f.sources[1].closed,true);
});
test("connection retries are bounded; unavailable stream is not a failed task",()=>{
 const f=fixture(); for(let i=0;i<3;i++){f.sources[i].dispatchEvent(new Event("error"));f.tick();}
 assert.equal(f.sources.length,3);assert.equal(f.states.at(-1),"unavailable");assert.equal(f.terminals(),0);assert.equal(f.scheduled.size,0);
});
test("thread switch/unmount closes subscription and ignores captured late callbacks",()=>{
 const old=fixture();const callback=old.sources[0].callbacks[0] as EventListener;old.sources[0].dispatchEvent(new Event("error"));old.close();old.tick();
 callback(new MessageEvent("workbench.activity",{data:JSON.stringify({sequence:9,type:"run_completed"})}));
 const next=fixture();next.sources[0].activity(1,"run_started");
 assert.equal(old.sources.length,1);assert.equal(old.events.length,0);assert.equal(old.terminals(),0);assert.equal(next.events.length,1);next.close();
});
test("late callbacks from disconnected source do not disrupt its replacement",()=>{
 const f=fixture();const callback=f.sources[0].callbacks[0] as EventListener;f.sources[0].dispatchEvent(new Event("error"));f.tick();
 callback(new MessageEvent("workbench.activity",{data:JSON.stringify({sequence:99,type:"run_cancelled"})}));
 f.sources[1].activity(1,"run_started"); assert.equal(f.events.length,1);assert.equal(f.terminals(),0);f.close();
});
test("Redis degradation closes stream without inferring job cancellation",()=>{
 const f=fixture();f.sources[0].dispatchEvent(new MessageEvent("workbench.unavailable",{data:'{"code":"activity_unavailable"}'}));
 assert.equal(f.states.at(-1),"unavailable");assert.equal(f.sources[0].closed,true);assert.equal(f.terminals(),0);
});
test("submission observer starts before POST, shares retry request identity and always cleans up",async()=>{
 const original=globalThis.fetch;const order:string[]=[];const ids:string[]=[];let seenId="";
 globalThis.fetch=async(_url,init)=>{order.push("post");ids.push(JSON.parse(String(init?.body)).client_request_id);if(ids.length===1)throw new TypeError("lost response");return new Response(JSON.stringify({conversation_id:"stream-test"}),{status:200});};
 try{
   await sendConversationMessage("stream-test",{content:"query",modelId:"auto",scope:"current"},{onRequest:(conversationId,id)=>{assert.equal(conversationId,"stream-test");seenId=id;order.push("subscribe");return()=>order.push("close");}});
   assert.deepEqual(order,["subscribe","post","post","close"]);assert.deepEqual(ids,[seenId,seenId]);
 }finally{globalThis.fetch=original;}
});
test("HTTP failure also closes observer, without cancelling or replaying the job",async()=>{
 const original=globalThis.fetch;let calls=0,closed=0;
 globalThis.fetch=async()=>{calls++;return new Response(JSON.stringify({detail:"conflict"}),{status:409});};
 try{await assert.rejects(sendConversationMessage("stream-failed",{content:"query",modelId:"auto",scope:"current"},{onRequest:()=>()=>{closed++;}}));assert.equal(calls,1);assert.equal(closed,1);}finally{globalThis.fetch=original;}
});

test("request ownership survives terminal stream cleanup but not thread switch or a newer request",()=>{
 let current: object | null = null, mounted=true, closed=0;
 const observer=()=>scopedAgentObserver({beforeStartIsCurrent:()=>mounted,ownerIsCurrent:token=>mounted&&current===token,start:()=>{const owner={};current=owner;return{owner,cleanup:()=>{closed++;}};}});
 const old=observer();const cleanup=old.onRequest("a","old");assert.equal(old.isCurrent(),true);cleanup();assert.equal(old.isCurrent(),true);
 const next=observer();next.onRequest("b","new");assert.equal(old.isCurrent(),false);assert.equal(next.isCurrent(),true);
 mounted=false;assert.equal(next.isCurrent(),false);assert.equal(closed,1);
});

test("503 before run_started clears connecting view; old cleanup cannot clear a newer run",async()=>{
 const original=globalThis.fetch;const active:{current:object|null}={current:null};let view:string|null=null;
 const observer=()=>scopedAgentObserver({beforeStartIsCurrent:()=>true,ownerIsCurrent:token=>active.current===token,start:(_cid,id)=>{const run={};active.current=run;view=id;return{owner:run,cleanup:()=>{releaseAgentRun(active,run,()=>{view=null;});}};}});
 globalThis.fetch=async()=>new Response(JSON.stringify({detail:"agent_configuration_missing"}),{status:503});
 try{await assert.rejects(sendConversationMessage("setup-failure",{content:"query",modelId:"auto",scope:"current"},observer()));assert.equal(view,null);assert.equal(active.current,null);}finally{globalThis.fetch=original;}
 const first=observer();const oldCleanup=first.onRequest("a","old");observer().onRequest("b","new");oldCleanup();assert.equal(view,"new");
});
