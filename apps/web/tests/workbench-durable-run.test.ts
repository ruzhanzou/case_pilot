import assert from "node:assert/strict";
import test from "node:test";
import { acceptsDurableProjection, durableFromConversation, durableIsTerminal, parseDurableRun, watchDurableRun, type DurableRun } from "../lib/workbench-durable-run";
import { parseAgentActivity } from "../lib/workbench-agent-activity";
const base = { id: "durable", status: "waiting_job", epoch: 1, cursor: 0, plan: { steps: [
  {action:"CASE_MODIFY",description:"Prepare selected rewrite",depends_on:[],status:"pending"},
  {action:"CASE_REVIEW",description:"Review resulting cases",depends_on:[0],status:"pending"},
]}, budget:{segments:8,reserved_sdk_requests:64},used:{segments:1,reserved_sdk_requests:4} };
const run = (values: Partial<DurableRun> = {}) => parseDurableRun({...base,...values})!;
const conversation = (projection: unknown, id="conversation") => ({id,context:{workbench_agent:{durable_run:projection}}});
const flush = async () => { await Promise.resolve(); await Promise.resolve(); };
function deferred<T>() {let resolve!: (value:T)=>void;const promise=new Promise<T>(done=>{resolve=done;});return {promise,resolve};}
function fixture(read: (id:string)=>Promise<unknown>, initial=run()) {
  const projected: DurableRun[] = [], connections:string[] = [], timers = new Map<number,()=>void>();let counter=0;
  const close=watchDurableRun({conversationId:"conversation",initial,read,onProjection:value=>projected.push(value),onConnection:value=>connections.push(value),
    schedule: ((callback:()=>void)=>{const id=++counter;timers.set(id,callback);return id;}) as unknown as typeof setTimeout,
    clearSchedule: ((id:number)=>{timers.delete(id);}) as unknown as typeof clearTimeout});
  return {projected,connections,close,timers,tick:()=>{for(const [id,callback] of timers){timers.delete(id);callback();}}};
}
test("projection accepts persisted plan only and strips arbitrary payloads",()=>{
  const parsed=parseDurableRun({...base,secret:"private",budget:{...base.budget,credential:99},plan:{steps:[{...base.plan.steps[0],arguments:{secret:true}}]}})!;
  assert.equal(JSON.stringify(parsed).includes("private"),false);
  assert.equal(JSON.stringify(parsed).includes("credential"),false);
  assert.equal(JSON.stringify(parsed).includes("arguments"),false);
  for(const invalid of [null,{}, {...base,status:"model-says-done"},{...base,cursor:3},{...base,epoch:-1},{...base,plan:{steps:[{}]}}]) assert.equal(parseDurableRun(invalid),null);
  assert.equal(durableFromConversation(conversation(base))?.id,"durable");
});
test("SDK completed does not finish waiting-job or waiting-approval durable plan",()=>{
  for(const status of ["waiting_job","waiting_approval","paused"] as const) {
    const activity=parseAgentActivity({status:"completed",agent_turn_status:"completed",events:[],durable_run:{...base,status}})!;
    assert.equal(activity.durable_run?.status,status);
    assert.equal(durableIsTerminal(activity.durable_run!),false);
  }
  for(const status of ["completed","failed","cancelled","invalidated","budget_exhausted"] as const) assert.equal(durableIsTerminal(run({status})),true);
});
test("old run, epoch and cursor projections cannot replace newer progress",()=>{
  assert.equal(acceptsDurableProjection(run(),run({id:"different"})),false);
  assert.equal(acceptsDurableProjection(run({epoch:2}),run()),false);
  assert.equal(acceptsDurableProjection(run({cursor:1}),run()),false);
  assert.equal(acceptsDurableProjection(run({status:"cancelled"}),run()),false);
  assert.equal(acceptsDurableProjection(run(),run({epoch:2,cursor:1,status:"waiting_approval"})),true);
});
test("GET observer follows worker then approval continuation and stops only at durable terminal",async()=>{
  const received:string[]=[];
  const queue=[run({status:"waiting_job"}),run({status:"waiting_approval",epoch:2}),run({status:"running",epoch:3,cursor:1}),run({status:"completed",epoch:4,cursor:2})];
  const f=fixture(async id=>{received.push(id);return conversation(queue.shift());});await flush();
  assert.equal(f.timers.size,1);
  for(let index=0;index<3;index++){f.tick();await flush();}
  assert.deepEqual(f.projected.map(value=>value.status),["waiting_job","waiting_approval","running","completed"]);
  assert.equal(f.timers.size,0);assert.deepEqual(received,Array(4).fill("conversation"));f.close();
});
test("navigation disposal ignores late GET and cannot schedule a retry",async()=>{
  const pending=deferred<unknown>(),f=fixture(async()=>pending.promise);
  f.close();pending.resolve(conversation(run({status:"completed"})));await flush();
  assert.deepEqual(f.projected,[]);assert.deepEqual(f.connections,[]);assert.equal(f.timers.size,0);
});
test("temporary GET failure reconnects read-only without losing saved progress",async()=>{
  let calls=0;const f=fixture(async()=>{if(++calls===1)throw new Error("offline");return conversation(run({status:"waiting_approval"}));});await flush();
  assert.deepEqual(f.connections,["reconnecting"]);f.tick();await flush();
  assert.equal(f.projected[0].status,"waiting_approval");assert.deepEqual(f.connections,["reconnecting","live"]);f.close();assert.equal(f.timers.size,0);
});
test("wrong conversation and different run cannot leak into the current thread",async()=>{
  for(const value of [conversation(run(),"foreign"),conversation(run({id:"new-run"})),conversation(run({epoch:0}))]) {
    const f=fixture(async()=>value);await flush();assert.deepEqual(f.projected,[]);assert.deepEqual(f.connections,["reconnecting"]);f.close();
  }
});
test("refresh of terminal projection does not issue reads or start any execution",async()=>{
  let reads=0;const f=fixture(async()=>{reads++;return conversation(base);},run({status:"completed",cursor:2}));await flush();
  assert.equal(reads,0);assert.equal(f.timers.size,0);f.close();
});

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { I18nProvider } from "../lib/i18n";
import { DurableAgentProgress } from "../components/durable-agent-progress";
import { LiveAgentProgress } from "../components/live-agent-progress";
import { cancelWorkbenchAgentRun } from "../lib/casepilot-api";
test("rendered progress distinguishes durable approval, worker wait and actual terminal",()=>{
  for(const [status,label] of [["paused","Plan temporarily paused"],["waiting_job","Waiting for draft computation"],["waiting_approval","Waiting for your review"],["completed","Plan completed"],["budget_exhausted","Execution budget exhausted"]] as const) {
    const html=renderToStaticMarkup(createElement(I18nProvider,null,createElement(DurableAgentProgress,{conversationId:"conversation",value:run({status}),onRefresh:async()=>undefined})));
    assert.ok(html.includes(label));assert.ok(html.includes("Plan cursor 0/2"));assert.ok(html.includes("Conservative reservations"));
    assert.equal(html.includes("Stop plan"),!["completed","budget_exhausted"].includes(status));
    if(status!=="completed")assert.equal(html.includes("Plan completed"),false);
  }
});
test("finished SDK segment cannot fabricate an approval prompt while worker is running",()=>{
  const html=renderToStaticMarkup(createElement(I18nProvider,null,createElement(LiveAgentProgress,{run:{conversationId:"conversation",requestId:"request",events:[{sequence:1,type:"run_awaiting_input"}],connection:"terminal",cancellation:"none"},durableRun:run(),onCancel:()=>undefined})));
  assert.ok(html.includes("Agent segment ended"));
  // Event history remains honest about the segment; the primary status describes the durable task.
  assert.match(html,/<strong>Agent segment ended/);
});
test("stop after reload sends durable identifier to existing cancel endpoint only",async()=>{
  const original=globalThis.fetch;const calls:{url:string;method:string}[]=[];
  globalThis.fetch=async(url,init)=>{calls.push({url:String(url),method:init?.method??"GET"});return new Response(JSON.stringify({status:"requested",transport_aborted:false}),{status:200});};
  try {await cancelWorkbenchAgentRun("conversation","durable");assert.equal(calls.length,1);assert.equal(calls[0].method,"POST");assert.ok(calls[0].url.endsWith("/conversations/conversation/agent-runs/durable/cancel"));}
  finally {globalThis.fetch=original;}
});

test("paused run polls saved state without resuming and can restore the prior wait",async()=>{
  const initial=run({status:"paused",epoch:2});let reads=0;
  const f=fixture(async()=>conversation(++reads===1?initial:run({status:"waiting_approval",epoch:3})),initial);
  await flush();assert.equal(f.projected[0].status,"paused");assert.equal(durableIsTerminal(f.projected[0]),false);
  f.tick();await flush();assert.equal(f.projected[1].status,"waiting_approval");f.close();
  const html=renderToStaticMarkup(createElement(I18nProvider,null,createElement(DurableAgentProgress,{conversationId:"conversation",value:initial,onRefresh:async()=>undefined})));
  assert.ok(html.includes("retrying the same request"));assert.ok(html.includes("does not resume execution"));
  assert.equal(html.includes("Plan completed"),false);assert.equal(html.includes("Plan failed"),false);
});

test("persisted paused_question normalizes to a nonterminal pause without inventing completion",()=>{
  const paused=parseDurableRun({...base,status:"paused_question"})!;
  assert.equal(paused.status,"paused");assert.equal(durableIsTerminal(paused),false);
  assert.equal(acceptsDurableProjection(paused,run({status:"waiting_approval"})),true);
});
