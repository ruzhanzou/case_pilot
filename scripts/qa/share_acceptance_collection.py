"""Add a synthetic member to an owned synthetic space in the acceptance DB."""
import sys
from pathlib import Path
from uuid import UUID
from dotenv import dotenv_values
from sqlalchemy import create_engine,select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'apps/api/src'))
from casepilot_api.models import Account,SpaceMembership
owner,member,space=sys.argv[1],sys.argv[2],UUID(sys.argv[3])
assert all(email.startswith('shared-') and email.endswith('@casepilot.test') for email in (owner,member))
url=make_url(dotenv_values(root/'.env')['DATABASE_URL']).set(host='127.0.0.1',database='casepilot_maturity_acceptance_20261023')
with Session(create_engine(url)) as db:
 assert db.scalar(select(Account.id).join(SpaceMembership,SpaceMembership.account_id==Account.id).where(Account.email==owner,SpaceMembership.space_id==space))
 member_id=db.scalar(select(Account.id).where(Account.email==member));assert member_id
 db.add(SpaceMembership(space_id=space,account_id=member_id,role='member'));db.commit()
print('Synthetic membership created')
