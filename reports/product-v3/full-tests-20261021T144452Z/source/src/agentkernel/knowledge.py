"""Optional bounded external documentation grounding; ordinary reasoning never searches."""
import os
from typing import Protocol
import httpx
from agentkernel.telemetry.redaction import redact
QUERIES = {
 'unknown_compiler_error':'Clang C pthread compiler diagnostics documentation',
 'unknown_sanitizer_behavior':'Clang ThreadSanitizer runtime diagnostics documentation',
 'unfamiliar_api':'POSIX pthread mutex condition variable API documentation',
 'toolchain_issue':'Clang ThreadSanitizer Linux supported platforms requirements'}
class KnowledgeTool(Protocol):
 async def search_documentation(self, query: str) -> list[dict[str,str]]: ...
class DisabledKnowledgeTool:
 async def search_documentation(self, query):
  raise RuntimeError('External grounding is disabled')
class TavilyKnowledgeTool:
 def __init__(self, client=None): self.client=client
 async def search_documentation(self, query):
  key=os.getenv('TAVILY_API_KEY')
  if not key: raise ValueError('missing_tavily_key')
  async def send(client):
   response=await client.post('https://api.tavily.com/search', headers={'Authorization':'Bearer '+key},
    json={'query':query,'search_depth':'basic','max_results':3,'include_domains':['clang.llvm.org','pubs.opengroup.org','gcc.gnu.org'],'include_answer':False,'include_raw_content':False},timeout=15,follow_redirects=False)
   response.raise_for_status()
   if len(response.content)>100000: raise ValueError('grounding_response_too_large')
   return [{k:str(item.get(k,''))[:1500] for k in ('title','url','content')} for item in response.json().get('results',[])[:3]]
  if self.client is not None: return await send(self.client)
  async with httpx.AsyncClient(trust_env=False) as client: return await send(client)
class ConditionalGrounding:
 def __init__(self, tool=None, enabled=None):
  self.enabled=os.getenv('AGENTKERNEL_TAVILY_ENABLED','false').lower()=='true' if enabled is None else enabled
  self.tool,self.calls=tool or TavilyKnowledgeTool(),0
 async def lookup(self, reason):
  record={'used':False,'reason':reason,'status':'not_needed','results':[]}
  if reason not in QUERIES: return record
  if not self.enabled or self.calls: return {**record,'status':'disabled' if not self.enabled else 'budget_exhausted'}
  self.calls+=1
  try:
   results=await self.tool.search_documentation(QUERIES[reason])
   return {**record,'used':True,'status':'retrieved','results':redact(results),'untrusted':True}
  except Exception as exc: return {**record,'used':True,'status':'unavailable','error':type(exc).__name__}
