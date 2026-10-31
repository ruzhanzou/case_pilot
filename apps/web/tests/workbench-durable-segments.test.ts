import assert from "node:assert/strict";
import test from "node:test";
import { watchDurableSegments, type DurableSegmentActivity } from "../lib/workbench-durable-segments";
import { parseDurableRun, acceptsDurableProjection } from "../lib/workbench-durable-run";
import { watchAgentStream } from "../lib/workbench-agent-stream";
const root="11111111-1111-4111-8111-111111111111";
const projection=(base:number,status="running")=>parseDurableRun({id:"durable",request_id:root,segment_sequence_base:base,status,epoch:1,cursor:0,plan:{steps:[{action:"rewrite",description:"Prepare",depends_on:[],status:"pending"}]},budget:{},used:{}})!;
type Subscription=Parameters<typeof watchAgentStream>[0];
function fixture() {
 const subscriptions:Subscription[]=[],closed:boolean[]=[],observed:DurableSegmentActivity[]=[];
 const manager=watchDurableSegments({conversationId:"a",eventsUrl:(id,request)=>`/${id}/${request}/events`,onActivity:value=>observed.push(value),subscribe:input=>{const index=subscriptions.length;subscriptions.push(input);closed.push(false);return()=>{closed[index]=true;};}});
 return {manager,subscriptions,closed,observed};
}
test("two actual segments reuse root request and reset old terminal events",()=>{
 const f=fixture();f.manager.update(projection(0));assert.equal(f.subscriptions[0].initialCursor,0);
 const first=f.subscriptions[0];first.onEvent({sequence:1,type:"run_started"});first.onEvent({sequence:2,type:"tool_completed",tool:"prepare_rewrite"});first.onEvent({sequence:3,type:"run_completed"});first.onState("terminal");first.onTerminal();
 assert.equal(f.observed.at(-1)?.connection,"terminal");
 f.manager.update(projection(0,"waiting_job"));assert.equal(f.subscriptions.length,1);
 f.manager.update(projection(104));assert.equal(f.closed[0],true);assert.equal(f.subscriptions.length,2);
 const next=f.subscriptions[1];assert.equal(next.url,`/a/${root}/events`);assert.equal(next.initialCursor,104);
 assert.deepEqual(f.observed.at(-1)?.events,[]);assert.equal(f.observed.at(-1)?.connection,"connecting");
 next.onEvent({sequence:105,type:"run_started"});next.onEvent({sequence:106,type:"tool_started",tool:"query_assets"});
 assert.deepEqual(f.observed.at(-1)?.events.map(event=>event.sequence),[105,106]);f.manager.close();
});
test("late prior-segment terminals cannot close or repaint a newer segment",()=>{
 const f=fixture();f.manager.update(projection(0));const old=f.subscriptions[0];f.manager.update(projection(104));const next=f.subscriptions[1];next.onEvent({sequence:105,type:"run_started"});
 const count=f.observed.length;old.onEvent({sequence:999,type:"run_completed"});old.onState("terminal");old.onTerminal();assert.equal(f.observed.length,count);
 next.onEvent({sequence:106,type:"tool_completed"});assert.equal(f.observed.at(-1)?.events.at(-1)?.sequence,106);f.manager.close();
});
test("same segment repeated projection never duplicates streams; SDK end is not durable end",()=>{
 const f=fixture();f.manager.update(projection(0));f.manager.update(projection(0));assert.equal(f.subscriptions.length,1);
 f.subscriptions[0].onTerminal();f.manager.update(projection(0));assert.equal(f.subscriptions.length,1);
 f.manager.update(projection(104,"waiting_approval"));assert.equal(f.subscriptions.length,1);
 f.manager.update(projection(104));assert.equal(f.subscriptions.length,2);f.manager.close();
});
test("A to B to A navigation fences old A callbacks despite same run identity",()=>{
 const old=fixture();old.manager.update(projection(0));old.manager.close();const next=fixture();next.manager.update(projection(104));
 const count=old.observed.length;old.subscriptions[0].onEvent({sequence:3,type:"run_completed"});old.subscriptions[0].onTerminal();assert.equal(old.observed.length,count);assert.equal(next.observed.at(-1)?.connection,"connecting");next.manager.close();
});
test("SSE reconnect resumes actual cursor at monotonic segment offset",()=>{
 class Source extends EventTarget {closed=false;close(){this.closed=true;}event(sequence:number,type:string){this.dispatchEvent(new MessageEvent("workbench.activity",{data:JSON.stringify({sequence,type,text:"never-display"})}));}}
 const sources:Source[]=[],urls:string[]=[],events:number[]=[],scheduled:(()=>void)[]=[];
 const close=watchAgentStream({url:"/events",initialCursor:104,onEvent:event=>events.push(event.sequence),onState:()=>undefined,onTerminal:()=>undefined,createSource:url=>{urls.push(url);const source=new Source();sources.push(source);return source;},schedule:fn=>{scheduled.push(fn);return 1 as unknown as ReturnType<typeof setTimeout>;},clearSchedule:()=>undefined});
 sources[0].event(3,"run_completed");sources[0].event(105,"run_started");sources[0].event(106,"tool_started");sources[0].dispatchEvent(new Event("error"));scheduled.shift()!();
 assert.deepEqual(urls,["/events?cursor=104","/events?cursor=106"]);sources[1].event(106,"tool_started");sources[1].event(107,"tool_completed");assert.deepEqual(events,[105,106,107]);close();
});
test("projection strips malformed stream metadata and rejects monotonic base regression",()=>{
 assert.equal(projection(104).request_id,root);assert.equal(projection(104).segment_sequence_base,104);
 for(const raw of [{...projection(104),request_id:"/arbitrary?url"},{...projection(104),segment_sequence_base:1001},{...projection(104),segment_sequence_base:-1}]) assert.equal(parseDurableRun(raw)?.request_id,undefined);
 assert.equal(acceptsDurableProjection(projection(104),projection(0)),false);
 assert.equal(acceptsDurableProjection(projection(0),projection(104)),true);
});
