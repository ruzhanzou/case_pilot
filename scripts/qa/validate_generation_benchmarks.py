"""Check fixed benchmark coverage, endpoint and status assertions; preserve every run."""
import json
import re
from pathlib import Path
root=Path(__file__).resolve().parents[2]/'output/journey-acceptance-20261021'
rows=[]
for name in ['batch-benchmark.json','batch-finalists.json','batch-v4-finalists.json','batch-hundred.json','batch-v5-finalists.json','batch-v5-hundred.json','batch-v6-finalists.json','batch-v6-hundred.json','batch-v7-finalists.json','batch-v7-hundred.json','batch-v7-hundred-verified.json']:
 path=root/name
 if not path.exists():continue
 data=json.loads(path.read_text())
 for run in data['runs']:
  issues=[];cases=run.get('cases',[])
  if len(cases)!=data['case_count']:issues.append('count')
  ids=[]
  for case in cases:
   ids+=case['test_point_ids'];index=int(case['test_point_ids'][0][1:]);body=json.dumps({'title':case['title'],'preconditions':case['preconditions'],'steps':case['steps']},ensure_ascii=False)
   paths=set(re.findall(r'/report/\d+',body))
   expected=' '.join(step['expected'] for step in case['steps'])
   if paths!={f'/report/{index}'} or not re.search(r'(?<!\d)200(?!\d)',expected):issues.append(case['id'])
  if len(set(ids))!=data['case_count']:issues.append('coverage')
  rows.append(dict(file=name,size=run['size'],concurrency=run['concurrency'],count=len(cases),seconds=run['seconds'],first_visible_seconds=run.get('previews',[{}])[0].get('seconds'),content_issues=issues,retries=sum(bool(c.get('retry')) for c in run['calls']),errors=[c['error'] for c in run['calls'] if c.get('error')],input_tokens=sum(c.get('usage',{}).get('token_usage',{}).get('input_tokens',0) for c in run['calls']),output_tokens=sum(c.get('usage',{}).get('token_usage',{}).get('output_tokens',0) for c in run['calls']),requests=len(run['calls'])))
(root/'batch-validation-final.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
print(len(rows),'runs;',sum(bool(r['content_issues']) for r in rows),'with content or coverage issues')
