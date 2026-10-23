"""Expire one owned synthetic attachment in the configured acceptance database."""
import os
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
configured_url = os.environ.get('CASEPILOT_ACCEPTANCE_DATABASE_URL') or dotenv_values(
    root / '.env'
)['DATABASE_URL']
url = make_url(configured_url).set(host='127.0.0.1')
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
