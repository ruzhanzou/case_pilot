import assert from "node:assert/strict";
import test from "node:test";
import { parseAgentActivity, verifiedAgentEffect } from "../lib/workbench-agent-activity";
test("activity exposes only safe event fields, not arguments or model reasoning", () => {
 const result = parseAgentActivity({status:"completed", events:[{sequence:1,type:"tool_completed",tool:"query_cases",arguments:{secret:true},text:"reasoning"}], receipts:[], final:null});
 assert.deepEqual(result?.events,[{sequence:1,type:"tool_completed",tool:"query_cases"}]);
});
test("model success text cannot create an applied or prepared receipt", () => {
 const result = parseAgentActivity({status:"completed",events:[],final:{kind:"action",effect:"prepare",message:"Everything saved",receipt_ids:["invented"]},receipts:[]})!;
 assert.equal(verifiedAgentEffect(result),null);
});
test("action requires every current receipt id and matching typed effect", () => {
 const data={status:"awaiting_input",events:[],final:{kind:"action",effect:"prepare",message:"Prepared",receipt_ids:["r"]},receipts:[{id:"r",tool:"prepare_rewrite",effect:"prepare"}]};
 assert.equal(verifiedAgentEffect(parseAgentActivity(data)!),"prepare");
 assert.equal(verifiedAgentEffect(parseAgentActivity({...data,receipts:[{id:"r",tool:"query_cases",effect:"read"}]})!),null);
 assert.equal(verifiedAgentEffect(parseAgentActivity({...data,final:{...data.final,kind:"answer"}})!),null);
});
test("malformed/no-action activity does not infer a successful task", () => {
 for(const value of [null,[],{},"completed"]) assert.equal(parseAgentActivity(value),null);
 const noAction=parseAgentActivity({status:"completed",events:[],final:{kind:"answer",effect:"none",message:"No change needed",receipt_ids:[]}})!;
 assert.equal(verifiedAgentEffect(noAction),null);
});
test("agent completion does not overwrite an actual queued or running draft job", () => {
  for(const domain_status of ["queued","running"]) {
    const activity=parseAgentActivity({status:domain_status,domain_status,agent_turn_status:"completed",events:[{sequence:1,type:"run_completed"}],receipts:[{id:"r",tool:"prepare_rewrite",effect:"prepare"}],final:{kind:"action",effect:"prepare",message:"queued",receipt_ids:["r"]}})!;
    assert.equal(activity.domain_status,domain_status);
    assert.equal(activity.agent_turn_status,"completed");
    assert.equal(activity.status,domain_status);
    assert.equal(verifiedAgentEffect(activity),"prepare");
  }
});
