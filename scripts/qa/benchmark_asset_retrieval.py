"""Measure the actual conversational retrieval and collection-provenance queries."""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID
from dotenv import dotenv_values
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from casepilot_agent.store import JobStore

root = Path(__file__).resolve().parents[2]
fixture = json.loads((root / 'output/journey-acceptance-20261021/perf-fixture.json').read_text())
url = make_url(dotenv_values(root / '.env')['DATABASE_URL']).set(host='127.0.0.1', database='casepilot_strategy_acceptance_20261021')
engine = create_engine(url, pool_size=5)
store = JobStore.__new__(JobStore)
def run(_):
    rows = []
    for _ in range(30):
        with engine.connect() as connection:
            start = time.perf_counter()
            assets = store.search_reuse_cases(connection, space_id=UUID(fixture['space']), terms=['登录', '账号系统'])
            retrieved = time.perf_counter()
            found = store.attach_reuse_collections(connection, assets, space_id=UUID(fixture['space']))
            end = time.perf_counter()
            assert len(found) == 100 and all(item['collections'] for item in found)
            rows.append({'retrieval_ms': (retrieved-start)*1000, 'provenance_ms': (end-retrieved)*1000, 'total_ms': (end-start)*1000, 'count': len(found)})
    return rows
with ThreadPoolExecutor(max_workers=5) as pool:
    rows = [row for group in pool.map(run, range(5)) for row in group]
result = {'samples': rows, 'p95': {key: sorted(row[key] for row in rows)[142] for key in ('retrieval_ms', 'provenance_ms', 'total_ms')}}
output = Path(os.environ.get('CASEPILOT_RETRIEVAL_OUTPUT', root / 'output/search-acceptance-round2-20261021/retrieval.json'))
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(result, indent=2))
print(result['p95'])
