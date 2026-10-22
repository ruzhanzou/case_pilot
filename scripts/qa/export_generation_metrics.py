"""Export stage timings for this isolated acceptance database; no prompts or credentials."""
import json
from pathlib import Path
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
root=Path(__file__).resolve().parents[2]
values=dotenv_values(root/'.env')
engine=create_engine(make_url(values['DATABASE_URL']).set(host='127.0.0.1',database='casepilot_strategy_acceptance_20261021'))
with engine.connect() as c:
 rows=[dict(r) for r in c.execute(text('''
 select s.stage, s.status, s.model, count(*) as requests,
 count(nullif(s.latency_ms,0)) as timed_samples,
 round(avg(nullif(s.latency_ms,0))) as average_ms,
 percentile_cont(0.95) within group(order by nullif(s.latency_ms,0)) as p95_ms,
 sum(coalesce((s.token_usage->>'input_tokens')::bigint,0)) as input_tokens,
 sum(coalesce((s.token_usage->>'output_tokens')::bigint,0)) as output_tokens
 from generation_job_stages s join generation_jobs j on j.id=s.generation_job_id
 join accounts a on a.id=j.account_id
 where a.email like 'strategy-real-%' or a.email like 'transition-%'
 group by s.stage,s.status,s.model order by s.stage,s.status
 ''')).mappings()]
 persistence=[dict(r) for r in c.execute(text("""
 select j.id::text as job_id,j.output_payload->'performance_metrics' as metrics
 from generation_jobs j join accounts a on a.id=j.account_id
 where a.email like 'transition-%' and j.output_payload ? 'performance_metrics'
 """)).mappings()]
(root/'output/journey-acceptance-20261021/stage-metrics.json').write_text(json.dumps({'scope':'isolated acceptance accounts, all attempts retained including earlier failed runs; zero legacy timings excluded; requirement.analyzed is an aggregate of requirement.batch stages, do not sum both as unique calls; model latency excludes queue wait; persistence timers exclude transaction commit','stages':rows,'persistence':persistence},ensure_ascii=False,indent=2,default=float))
print('Exported',len(rows),'stage groups')
