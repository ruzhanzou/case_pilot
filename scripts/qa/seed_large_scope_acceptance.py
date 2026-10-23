"""Seed an owned synthetic collection only in the isolated maturity database."""
import json
import sys
from pathlib import Path
from uuid import UUID, uuid4
from dotenv import dotenv_values
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root/'apps/api/src'))
from casepilot_api.models import Account, SpaceMembership, CaseCollection, TestCase, TestCaseRevision, CollectionCaseMembership
email,collection_id=sys.argv[1],UUID(sys.argv[2])
assert email.startswith('large-scope-') and email.endswith('@casepilot.test')
url=make_url(dotenv_values(root/'.env')['DATABASE_URL']).set(host='127.0.0.1',database='casepilot_maturity_acceptance_20261023')
with Session(create_engine(url)) as db:
 collection=db.get(CaseCollection,collection_id)
 assert collection and db.scalar(select(Account.id).join(SpaceMembership,SpaceMembership.account_id==Account.id).where(Account.email==email,SpaceMembership.space_id==collection.space_id))
 assert not db.scalar(select(CollectionCaseMembership.id).where(CollectionCaseMembership.collection_id==collection_id).limit(1))
 cases=[];revisions=[];members=[];expected=[]
 for i in range(5001):
  case_id,revision_id=uuid4(),uuid4()
  cases.append(TestCase(id=case_id,space_id=collection.space_id,case_key=f'BIG-{i:05d}'))
  revisions.append(TestCaseRevision(id=revision_id,test_case_id=case_id,revision_number=1,title=f'业务场景{i:05d}',module='支付/退款' if i%2 else '账号',priority='P0' if i%3==0 else 'P1',steps=[{'action':'提交请求','expected':'超时后回滚'}]))
  members.append(CollectionCaseMembership(collection_id=collection_id,test_case_id=case_id,position=i))
  if i%2 and i%3:expected.append(str(case_id))
 db.add_all(cases);db.flush();db.add_all(revisions);db.flush()
 for case,revision in zip(cases,revisions):case.current_revision_id=revision.id
 db.add_all(members);db.commit()
 print(json.dumps({'count':5001,'expected_ids':expected}))
