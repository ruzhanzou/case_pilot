"""Capture the exact SDK system/user prompt with the transport replaced (no model call)."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from dotenv import load_dotenv
root=Path(__file__).resolve().parents[2]
load_dotenv(root/'.env')
sys.path.insert(0,str(root/'apps/agent/tests'))
from test_reuse import with_decision
from casepilot_agent.config import get_settings
from casepilot_agent.pipeline import GenerationPipeline
from casepilot_agent.providers import create_provider
from casepilot_agent.providers.mock import MockProvider
provider=create_provider(get_settings().provider)
request=with_decision('modify')
request.confirmed_plan['reuse']['decisions'][0]['reason']='操作步骤需明确账号与提交动作；预期保持不变'
request.batch_concurrency=1
request.prompt='测试对象：账号系统。登录成功建立会话。参考已确认来源，只为当前测试点改写，不增加其他范围。'
request.conversation_memory=[{'role':'user','content':'保留原有预期'},{'role':'user','content':'步骤明确写出输入有效账号并提交'}]
captured=[]
current_type=None
async def intercept(agent,prompt,max_turns):
    data=json.loads(prompt)
    captured.append({'system_instructions':agent.instructions,'user_message':data})
    result,_=MockProvider().complete(stage=data['stage'],instruction=data['task'],payload=data['input'],result_type=current_type,model_id=None)
    return SimpleNamespace(final_output=result,context_wrapper=SimpleNamespace(usage=SimpleNamespace(input_tokens=0,output_tokens=0,total_tokens=0)))
def execute(stage,instruction,payload,result_type,model_id):
    global current_type
    current_type=result_type
    return provider.complete(stage=stage,instruction=instruction,payload=payload,result_type=result_type,model_id=model_id)[0]
with patch('agents.Runner.run',intercept):
    GenerationPipeline(provider).run(request,context={},answers={},execute_stage=execute)
(root/'output/journey-acceptance-20261021/prompt-capture.json').write_text(json.dumps({'transport':'mocked for exact prompt inspection; benchmark transport is real','calls':captured},ensure_ascii=False,indent=2))
print('Captured',len(captured),'assembled SDK prompt(s)')
