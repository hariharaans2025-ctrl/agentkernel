"""Strict text-only adapter interface. Candidate code is never executed here."""
import json
import re
from pathlib import Path
from agentkernel.concurrency.repair.patch_parser import parse_repair

SYSTEM = ('Repair C/pthreads synchronization while preserving all original work, '
    'scheduling hooks, interfaces and protected tests. Return ONLY a JSON object with one key '
    '"files": an object mapping each editable filename to its complete corrected source. '
    'Do not include Markdown, explanations, commands, tests, or new files.')


def messages(sources, description, headers=None, requirements=None,system_prompt=None):
    return [{'role':'system','content':system_prompt or SYSTEM},{'role':'user','content':json.dumps({
        'task':description,'editable_files':list(sources),'sources':sources,
        'headers':headers or {},'requirements':requirements or []},ensure_ascii=False)}]


def to_proposal(response, sources):
    if not isinstance(response,str) or len(response)>160000: raise ValueError('Invalid specialist response')
    data=json.loads(response)
    if not isinstance(data,dict) or set(data)!={'files'} or not isinstance(data['files'],dict) or set(data['files'])!=set(sources):
        raise ValueError('Specialist must return exactly the editable files')
    edits=[]
    for name,original in sources.items():
        candidate=data['files'][name]
        if not isinstance(candidate,str) or not candidate or len(candidate)>120000: raise ValueError('Invalid candidate source')
        if candidate.count('sched_yield(')!=original.count('sched_yield('): raise ValueError('Scheduling hooks changed')
        if candidate!=original: edits.append({'file':name,'search':original,'replacement':candidate})
    if not edits: raise ValueError('No repair proposed')
    text=json.dumps({'diagnosis':'Local fine-tuned specialist proposal','root_cause':'Synchronization change proposed; independent verification required.',
        'confidence':0.5,'edits':edits,'reasoning_summary':'','expected_effect':'Preserve workload invariants.',
        'risk_notes':['Not accepted until every mandatory execution check passes.']})
    return parse_repair(text,sources),text


def artifact_ready(root):
    path=Path(root)/'training.json'
    if not path.is_file(): return False
    try:
        data=json.loads(path.read_text(encoding='utf-8'))
        return data.get('status')=='trained' and (Path(root)/'adapter/adapter_model.safetensors').is_file()
    except (ValueError,OSError): return False


def active_root(root):
    root=Path(root).resolve()
    pointer=root/'models/active-specialist.json'
    target=(root/json.loads(pointer.read_text())['path']).resolve() if pointer.exists() else root/'models/adaptive-specialist-v1'
    if not target.is_relative_to(root/'models'):raise ValueError('Specialist path must stay in the project models directory')
    return target


TAGGED_SYSTEM=('Repair C/pthreads synchronization. Preserve all original functional work, interfaces and scheduling hooks. '
    'Return ONLY complete corrected editable files using exactly this format:\n'
    '<<<FILE:filename.c>>>\nraw C source with actual newlines\n<<<END_FILE>>>\n'
    'Do not JSON-encode the source, do not escape quotes/newlines, and do not use Markdown. '
    'Do not add or remove sched_yield calls. Never modify protected headers or tests.')


def tagged_messages(sources,description,headers=None,requirements=None):
    user='Task: '+description+'\nRequirements: '+ '; '.join(requirements or [])+'\nEditable ORIGINAL files:\n'
    for name,source in sources.items():
        user+='<<<FILE:'+name+'>>>\n'+source+'<<<END_FILE>>>\n'
        user+='Required sched_yield call count for '+name+': '+str(source.count('sched_yield('))+'\n'
    for name,header in (headers or {}).items():user+='Protected header '+name+':\n'+header+'\n'
    return [{'role':'system','content':TAGGED_SYSTEM},{'role':'user','content':user}]


def tagged_to_proposal(response,sources):
    matches=list(re.finditer(r'<<<FILE:([^>\n]+)>>>\n(.*?)<<<END_FILE>>>',response,re.S))
    if not matches or len(matches)!=len(sources):raise ValueError('Missing or duplicate tagged editable files')
    remainder=response
    files={}
    for match in matches:
        if match[1] in files:raise ValueError('Repeated editable filename')
        files[match[1]]=match[2];remainder=remainder.replace(match[0],'',1)
    if remainder.strip():raise ValueError('Explanations or Markdown outside the file markers')
    return to_proposal(json.dumps({'files':files}),sources)
