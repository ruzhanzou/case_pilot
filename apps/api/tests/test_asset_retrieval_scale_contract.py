from uuid import UUID,uuid4
import pytest
from httpx import ASGITransport,AsyncClient
from casepilot_api.main import app
from casepilot_api.database import get_session_factory
from casepilot_agent.store import JobStore

@pytest.mark.asyncio
async def test_collection_name_recall_is_scoped_deduplicated_and_reports_truncation():
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        async def post(path,data):
            r=await client.post('/api/v1'+path,json=data);assert r.status_code in (200,201,202),r.text;return r.json()
        user=await post('/auth/register',{'email':f'recall-{uuid4().hex}@casepilot.test','password':'CasePilot123!','display_name':'Recall'})
        space=user['spaces'][0]['id'];token='集合锚点'+uuid4().hex
        collection=await post(f'/spaces/{space}/collections',{'name':token})
        cases=[await post(f"/collections/{collection['id']}/test-cases",{'title':f'登录场景{i}','module':'认证','priority':'P1','case_type':'functional','preconditions':['账号启用'],'steps':[{'action':'提交登录','expected':'成功'}]}) for i in range(3)]
        store=JobStore.__new__(JobStore)
        with get_session_factory()() as db:
            connection=db.connection()
            settings_before=[connection.exec_driver_sql('SHOW '+name).scalar_one() for name in ['work_mem','max_parallel_workers_per_gather']]
            metrics={};found=store.search_reuse_cases(db.connection(),space_id=UUID(space),terms=[token],limit=2,metrics=metrics)
            assert len(found)==2 and len({x['ref'] for x in found})==2
            assert {x['ref'] for x in found}.issubset({x['id'] for x in cases})
            assert metrics['matched_case_count']==3 and metrics['truncated']
            assert metrics['returned_case_count']==2 and metrics['scope_collection_count']>=1
            exact=store.search_reuse_cases(db.connection(),space_id=UUID(space),terms=[cases[2]['case_key']])
            assert [x['ref'] for x in exact]==[cases[2]['id']]
            assert not store.search_reuse_cases(db.connection(),space_id=uuid4(),terms=[token])
            assert not store.search_reuse_cases(db.connection(),space_id=UUID(space),terms=['%_'+token])
            # A full maximum-score bucket must retain the original UUID tie
            # order, while exact totals remain independent from page size.
            stats={}
            body=store.search_reuse_cases(db.connection(),space_id=UUID(space),terms=['登录','场景'],limit=2,metrics=stats)
            assert [x['ref'] for x in body] == sorted(x['id'] for x in cases)[:2]
            assert stats['matched_case_count']==3 and stats['truncated']
            stats={}
            assert not store.search_reuse_cases(db.connection(),space_id=UUID(space),terms=['登录'],limit=0,metrics=stats)
            assert stats['matched_case_count']==3 and stats['returned_case_count']==0
            # Only one perfect hit: fall back to ranked partial matches.
            partial=store.search_reuse_cases(db.connection(),space_id=UUID(space),terms=['登录','场景2'],limit=2)
            assert partial[0]['ref']==cases[2]['id'] and len(partial)==2
            assert [connection.exec_driver_sql('SHOW '+name).scalar_one() for name in ['work_mem','max_parallel_workers_per_gather']] == settings_before
            original_search=store._search_reuse_cases
            def broken_search(*args, **kwargs):
                connection.exec_driver_sql('SELECT 1/0')
            store._search_reuse_cases=broken_search
            from sqlalchemy.exc import DBAPIError
            with pytest.raises(DBAPIError):
                store.search_reuse_cases(connection,space_id=UUID(space),terms=['登录'])
            store._search_reuse_cases=original_search
            # The caller's transaction remains usable after the failed read;
            # query-local resource limits never leak into unrelated operations.
            assert [connection.exec_driver_sql('SHOW '+name).scalar_one() for name in ['work_mem','max_parallel_workers_per_gather']] == settings_before
