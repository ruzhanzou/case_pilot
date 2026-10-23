import assert from 'node:assert/strict';
import test from 'node:test';
import {createSubmissionSender} from '../lib/submission-retry';
function fixture() {
  const values=new Map<string,string>();let sequence=0;
  const storage={getItem:(key:string)=>values.get(key)??null,setItem:(key:string,value:string)=>{values.set(key,value);},removeItem:(key:string)=>{values.delete(key);}};
  return {storage,uuid:()=>`request-${++sequence}`};
}
test('transport replay uses one identity; a later intentional identical message gets a new one',async()=>{
 const {storage,uuid}=fixture();const send=createSubmissionSender(()=>storage,uuid);const ids:string[]=[];
 const result=await send('c','same text',async id=>{ids.push(id);if(ids.length===1)throw new TypeError('network lost');return 'accepted';});
 assert.equal(result,'accepted');assert.deepEqual(ids,['request-1','request-1']);
 await send('c','same text',async id=>{ids.push(id);return 'new intent';});
 assert.equal(ids[2],'request-2');
});
test('uncertain response survives sender reload and preserves its key',async()=>{
 const {storage,uuid}=fixture();const first=createSubmissionSender(()=>storage,uuid);
 await assert.rejects(first('c','body',async()=>{throw new TypeError('offline');}));
 const restored=createSubmissionSender(()=>storage,uuid);let received='';
 await restored('c','body',async id=>{received=id;return 'accepted';});
 assert.equal(received,'request-1');assert.equal(storage.getItem('casepilot.submission.v1:c'),null);
});
test('changed content gets a new identity and HTTP errors are not automatically repeated',async()=>{
 const {storage,uuid}=fixture();const send=createSubmissionSender(()=>storage,uuid);let calls=0;
 await assert.rejects(send('c','original',async()=>{calls++;throw new Error('validation error');}));
 assert.equal(calls,1);let received='';
 await send('c','corrected',async id=>{received=id;return 'ok';});assert.equal(received,'request-2');
});
test('unavailable session storage retains in-memory retry identity',async()=>{
 const {uuid}=fixture();const send=createSubmissionSender(()=>{throw new Error('storage disabled');},uuid);const ids:string[]=[];
 await assert.rejects(send('c','body',async id=>{ids.push(id);throw new TypeError('offline');}));
 await send('c','body',async id=>{ids.push(id);return 'ok';});assert.deepEqual(ids,['request-1','request-1','request-1']);
});
