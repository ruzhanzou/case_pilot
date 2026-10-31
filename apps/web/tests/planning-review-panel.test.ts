import assert from "node:assert/strict";
import {createElement} from "react";
import {renderToStaticMarkup} from "react-dom/server";
import test from "node:test";
import {PlanningReviewCard} from "../components/planning-review-panel";
import type {PlanningReviewRecord, TestPlanningDto} from "../lib/casepilot-api";

const planning = {feature_points: [], test_points: []} as TestPlanningDto;
const record: PlanningReviewRecord = {id:"r",base_version:1,status:"proposed",requests_used:2,request_limit:2,
  error_code:null,proposal_hash:"hash",applied_brief_id:null,selected:["issue-1"],sources:[{excerpt:"Original rule"}],
  review:{findings:[],unresolved:["Unknown rule"]},proposal:{points:[{point_id:"new:1",action:"upsert",title:"New proposal",
  scenario:"Proposed scenario",objective:"Proposed outcome",feature_ids:["f"],primary_feature_id:"f",sources:[0],issue_ids:["issue-1"]}],
  obligations:[],unresolved:["Still unknown"]}};
function render(value: PlanningReviewRecord|null, countConfirmed=false) {
  return renderToStaticMarkup(createElement(PlanningReviewCard,{version:1,planning,record:value,
    selected:[],setSelected:()=>{},busy:false,error:"",countConfirmed,setCountConfirmed:()=>{},act:async()=>{}}));
}
test("proposal is a sourced preview and count changes require an explicit extra confirmation",()=>{
  const html=render(record);
  assert.match(html,/Original rule/); assert.match(html,/Still unknown/);
  assert.match(html,/不生成或采纳正式用例/); assert.match(html,/disabled="">确认接受此修订提案/);
  assert.doesNotMatch(render(record,true),/disabled="">确认接受此修订提案/);
});
test("stale cancelled and applied states cannot offer apply or restart a model budget",()=>{
  for(const status of ["invalidated","cancelled","applied","failed"]) {
    const html=render({...record,status});
    assert.doesNotMatch(html,/确认接受此修订提案|审核完整规划/);
    assert.match(html,/已用 2\/2/);
  }
});
test("a fresh card states the fixed budget and independent review boundary",()=>{
  assert.match(render(null),/最多 2 次请求/);
  assert.match(render(null),/不是独立质量证明/);
});
