"""Expire only a synthetic attachment in the isolated maturity acceptance database."""
import sys
from pathlib import Path
from uuid import UUID
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

root = Path(__file__).resolve().parents[2]
email, document = sys.argv[1], str(UUID(sys.argv[2]))
if not email.startswith('expiry-') or not email.endswith('@casepilot.test'):
    raise SystemExit('Synthetic expiry account required')
url = make_url(dotenv_values(root / '.env')['DATABASE_URL']).set(
    host='127.0.0.1', database='casepilot_maturity_acceptance_20261023')
with create_engine(url).begin() as connection:
    result = connection.execute(text('''UPDATE knowledge_documents d
        SET expires_at = now() - interval '1 second'
        FROM knowledge_sources s, accounts a
        WHERE d.id = :document AND d.source_id = s.id
          AND s.account_id = a.id AND a.email = :email
        RETURNING d.id'''), {'document': document, 'email': email}).all()
    if len(result) != 1:
        raise RuntimeError('Expected exactly one owned synthetic attachment')
print('Synthetic attachment expired')
