"""Read-only hosted health/protocol check. No jobs, model calls, or credential files."""
import getpass
import json
from pathlib import Path
import time
import httpx

SITE = 'https://agentkernel-control.abuzzleaf32.chatgpt.site'
if __name__ == '__main__':
    token = getpass.getpass('Private Site token (hidden): ')
    with httpx.Client(base_url=SITE, headers={'OAI-Sites-Authorization':'Bearer '+token}, timeout=30) as client:
        response = client.get('/api/control')
        response.raise_for_status()
        state = response.json()
        def rpc(method, params=None):
            r = client.post('/mcp', json={'jsonrpc':'2.0','id':1,'method':method,'params':params or {}})
            if r.status_code == 401:
                return {'authentication_required': True, 'http_status': 401}
            r.raise_for_status()
            return r.json()
        discovery = rpc('server/discover')
        listed = rpc('tools/list')
        denied = rpc('tools/call', {'name':'agentkernel_status','arguments':{}})
        snapshot = state.get('snapshot') or {}
        result = {'site':SITE, 'heartbeat_age_seconds':round((time.time()*1000-snapshot.get('heartbeat',0))/1000,2),
                  'connected_codebases':len(snapshot.get('repositories',[])), 'available_routes':len(snapshot.get('models',[])),
                  'queued_commands':len(state.get('commands',[])), 'protocol':discovery.get('result'),
                  'tools':[t['name'] for t in listed.get('result',{}).get('tools',[])],
                  'mcp_requires_user_oauth':discovery.get('authentication_required', False),
                  'service_access_cannot_impersonate_user':denied.get('authentication_required') is True or denied.get('result',{}).get('isError') is True,
                  'paid_model_calls':0}
        print(json.dumps(result,indent=2))
        output=Path(__file__).resolve().parents[1]/'reports/release-20261022'
        output.mkdir(exist_ok=True)
        (output/'hosted-check.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
