import json,time,threading,httpx,os
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from casepilot_agent.config import get_settings
from pathlib import Path
settings=get_settings();state={'mode':'normal','remaining':0,'calls':[]};lock=threading.Lock()
out=Path(os.environ.get('QA_EVIDENCE','output/nl-e2e-fix-20261009/fault-proxy.json'))
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):
  self.respond(200,state if self.path=="/state" else {"ok":True})
 def do_POST(self):
  data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
  if self.path=='/control':
   with lock:state.update(mode=data['mode'],remaining=data.get('remaining',1),skip=data.get('skip',0))
   self.respond(200,{'ok':True});return
  stage=''
  for m in data.get('messages',[]):
   if m.get('role')=='user':
    try:stage=json.loads(m['content']).get('stage','')
    except (ValueError,TypeError):pass
  with lock:
   fault=state['mode'] if state['remaining'] and stage in ('rewrite.batch','test_case.rewritten') else 'normal'
   if fault!='normal' and state.get('skip',0):
    state['skip']-=1;fault='normal'
   elif fault!='normal':state['remaining']-=1
   state['calls'].append({'time':time.time(),'stage':stage,'fault':fault});out.write_text(json.dumps(state,indent=2))
  if fault=='429':self.respond(429,{'error':{'message':'QA controlled rate limit','type':'rate_limit_error'}});return
  if fault=='invalid':
   self.respond(200,{'id':'qa-invalid','object':'chat.completion','created':int(time.time()),'model':data.get('model'),'choices':[{'index':0,'message':{'role':'assistant','content':json.dumps({'items':[{'ref':'invalid','proposed':[]}]})},'finish_reason':'stop'}],'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}});return
  if fault=='delay':time.sleep(45)
  try:
   r=httpx.post(settings.base_url.rstrip('/')+'/chat/completions',json=data,headers={'Authorization':'Bearer '+settings.api_key},timeout=240)
   self.send_response(r.status_code);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(r.content)
  except Exception:self.respond(502,{'error':{'message':'upstream request failed'}})
 def respond(self,status,data):
  self.send_response(status);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps(data).encode())
ThreadingHTTPServer(('0.0.0.0',8101),Handler).serve_forever()
