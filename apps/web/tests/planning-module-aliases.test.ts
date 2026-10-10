import assert from 'node:assert/strict';
import test from 'node:test';
import { planningModuleAliases } from '../lib/case-module-tree';
test('legacy scenario paths collapse without truncating custom paths', () => {
 const aliases = planningModuleAliases({feature_points:[{id:'f',module:'登录',name:'Apple ID'}],test_points:[{feature_point_ids:['f'],scenario:'拒绝授权',title:'拒绝后保持未登录'}]});
 assert.equal(aliases['登录/Apple ID/拒绝授权/拒绝后保持未登录'], '登录/Apple ID');
 assert.equal(aliases['登录/Apple ID/自定义分类'], undefined);
 assert.deepEqual(planningModuleAliases(), {});
});
