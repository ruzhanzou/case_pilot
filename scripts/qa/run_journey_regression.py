import os, subprocess
from pathlib import Path
from dotenv import dotenv_values
from sqlalchemy.engine import make_url
root=Path.cwd()
v={**dotenv_values('.env'),**os.environ}
v['DATABASE_URL']=make_url(v['DATABASE_URL']).set(host='127.0.0.1',database='casepilot_strategy_acceptance_20261021').render_as_string(hide_password=False)
v.update(CASEPILOT_AGENT_PROVIDER='mock', CASEPILOT_AI_MODE='mock', REDIS_URL='redis://127.0.0.1:6388/8', CELERY_BROKER_URL='redis://127.0.0.1:6388/9', CELERY_RESULT_BACKEND='redis://127.0.0.1:6388/10', PYTHONPATH=str(root/'apps/agent/tests'))
files=['apps/agent/tests/'+n+'.py' for n in ['test_batch_execution','test_compact_generation','test_generation_strategies','test_intentional_reuse_quality','test_reuse','test_parallel_planning','test_pipeline','test_rewrite_preservation','test_rewrite_rounds','test_review_regressions','test_draft_planning_progress']]+['apps/api/tests/'+n+'.py' for n in ['test_model_scope','test_generation_strategy_intent','test_reuse_choices','test_conversation_intents','test_generation_asset_confirmation','test_planning_links','test_reuse_generation_boundaries','test_rewrite_dialogue','test_asset_rewrite_handoff','test_multi_user_concurrency','test_case_workflow_integration','test_case_asset_search']]
raise SystemExit(subprocess.call(['/tmp/casepilot-reuse-venv/bin/python','-m','pytest',*files,'--asyncio-mode=auto','--import-mode=importlib','-q','--junitxml=output/qa-journey-20261022/regression.xml'],env=v))
