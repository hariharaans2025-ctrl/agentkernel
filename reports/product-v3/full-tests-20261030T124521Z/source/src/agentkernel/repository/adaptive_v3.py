"""Production repair profiles with strict responses, persistent spending limits and remote verification."""
import asyncio
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
from time import perf_counter
import uuid
import httpx

from agentkernel.concurrency.compile.compiler import CCompiler
from agentkernel.concurrency.instrumentation.sanitizer import instrumented_task, SanitizerConfig, runtime_unavailable
from agentkernel.concurrency.sandbox.nebius import NebiusSandboxBackend
from agentkernel.concurrency.sandbox.local import safe_path
from agentkernel.concurrency.verification.concurrency_verifier import ConcurrencyVerifier
from agentkernel.repository.learning import require_verified
from .adaptive import local_generate
from .specialist import active_root, tagged_messages, tagged_to_proposal
from .remote_repair import quote_repair_model
from .line_repair import line_messages as repair_messages, plan_line_repair as plan_remote_repair, parse_line_response as parse_remote_response
from .budget import BudgetLedger
from .product_campaign import ProductCampaign

FAST_ID = 'agentkernel/adaptive-v3-fast'
BALANCED_ID = 'agentkernel/adaptive-v3-balanced'
CAPS = {'fine_tuned':2048, 'super':4096, 'ultra':8192}


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)


def remote_models(models):
    available = {m['id']:m for m in models}
    result = {}
    defaults = {'super':'nvidia/nemotron-3-super-120b-a12b', 'ultra':'nvidia/Nemotron-3-Ultra-550b-a55b'}
    for stage, default in defaults.items():
        identifier = os.environ.get('AGENTKERNEL_NEMOTRON_'+stage.upper()+'_MODEL', default)
        if identifier not in available:
            raise ValueError('Configured fallback is unavailable: '+stage)
        result[stage] = available[identifier]
    return result


def product_quote(models, *, max_input_tokens=48000):
    return sum(quote_repair_model(m, max_input_tokens=max_input_tokens,max_output_tokens=CAPS[s])
               for s,m in remote_models(models).items())


def verification_summary(v, hooks):
    return {'build_passed':v.build_passed, 'original_tests_passed':v.evidence.get('original_tests',{}).get('passed'),
            'passed_runs':v.passed_runs,'total_runs':v.total_runs,'semantic_passed':v.semantic_passed,
            'tsan_passed':v.sanitizer_passed,'scheduling_hooks_preserved':hooks}


class ProductRepair:
    def __init__(self, root, models, *, on_progress=None, model_root=None, ledger=None, campaign_factory=ProductCampaign):
        self.root = Path(root).resolve(); self.models = models
        self.progress = on_progress or (lambda data:None)
        self.model_root = Path(model_root) if model_root is not None else active_root(root)
        self.ledger = ledger or BudgetLedger(self.root/'reports/product-v3/budget.json')
        self.campaign_factory = campaign_factory

    async def run(self, task, folder, *, profile='fast', max_cost_usd, max_calls=None,
                  max_total_tokens=180224, max_input_tokens=48000, max_output_tokens=8192):
        if profile not in ('fast','balanced','super_only','ultra_only'):
            raise ValueError('Unknown product profile')
        if type(max_cost_usd) not in (int,float) or not math.isfinite(max_cost_usd) or not 0<=max_cost_usd<=1:
            raise ValueError('Explicit charge cap no greater than $1 required')
        options = remote_models(self.models)
        selected = {'super_only':['super'],'ultra_only':['ultra'],'fast':['super','ultra'],
                    'balanced':['fine_tuned','super','ultra']}[profile]
        required_quote=sum(quote_repair_model(options[s],max_input_tokens=max_input_tokens,max_output_tokens=CAPS[s])
                           for s in selected if s!='fine_tuned')
        if required_quote>max_cost_usd:
            raise ValueError('Reviewed route ceiling is insufficient')
        stages = selected
        if max_calls is not None and max_calls < len(stages):
            raise ValueError('Reviewed contract cannot accommodate this profile')
        if max_output_tokens < 8192:
            raise ValueError('This profile requires a reviewed 8192-token maximum output cap')
        cfg=task.verification_config
        if (cfg.stress_runs<100 or not cfg.required_build_success or not cfg.required_original_tests
                or not cfg.original_test_commands or not cfg.semantic_checks or not all(c.required for c in cfg.semantic_checks)
                or not cfg.sanitizer_enabled or not cfg.sanitizer_required or cfg.sanitizer_runs<3
                or cfg.allowed_deadlocks or cfg.allowed_races or cfg.allowed_crashes):
            raise ValueError('Product repair requires complete independent verification before inference')
        folder = Path(folder); folder.mkdir(parents=True,exist_ok=False)
        started = perf_counter(); rows=[]
        original_workspace=task.workspace.resolve(strict=True)
        frozen=folder/'input'; frozen.mkdir()
        for name in task.source_files+task.support_files:
            if any(part.startswith('.') or part.startswith('.env') for part in Path(name).parts):
                raise ValueError('Hidden or credential files cannot enter repair scope')
            source=safe_path(original_workspace,name)
            if not source.is_file() or source.stat().st_size>2000000:
                raise ValueError('Invalid source capture')
            data=source.read_bytes()
            target=safe_path(frozen,name);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
            if hashlib.sha256(source.read_bytes()).digest()!=hashlib.sha256(data).digest():
                raise ValueError('Source changed during capture')
        task=task.model_copy(update={'workspace':frozen})
        sources = {n:(task.workspace/n).read_text(encoding='utf-8') for n in task.source_files}
        headers = {n:(task.workspace/n).read_text(encoding='utf-8') for n in task.support_files if n.endswith(('.h','.hpp'))}
        hashes = {n:hashlib.sha256((task.workspace/n).read_bytes()).hexdigest() for n in task.source_files+task.support_files}
        config = task.verification_config.model_dump(mode='json')
        save(folder/'started.json',{'profile':profile,'max_calls':len(stages),'caps':CAPS,'max_cost_usd':max_cost_usd,
             'max_total_tokens':max_total_tokens,'source_hashes':hashes,'task':task.model_dump(mode='json'),
             'automatic_replay':False,'verification_transport':'journaled 40-run batches','ledger':str(self.ledger.path)})
        result = {'status':'unknown','profile':profile,'attempts':rows,'model_calls':0,'remote_model_calls':0,
                  'tokens':0,'cost_usd':0,'reserved_usd':0,'false_fix':False}
        description = task.metadata.get('fixture_description',task.metadata.get('description','Repair the observed concurrency failure while preserving every task invariant.'))
        requirements = [c.name for c in task.verification_config.semantic_checks]
        baseline = None; sanitizer_baseline=None
        try:
            self.progress({'stage':'Remote baseline and source validation','attempts':rows})
            base_folder = folder/'baseline'; base_folder.mkdir()
            async with NebiusSandboxBackend() as box:
                await box.upload_project(task.workspace,task.source_files+task.support_files)
                build = await CCompiler().compile(task,box); save(base_folder/'build.json',build.model_dump(mode='json'))
                if not build.success: raise RuntimeError('Baseline build unavailable; no inference started')
                campaign = self.campaign_factory(base_folder)
                baseline = await campaign.run(task,box,runs=3)
                if baseline.infrastructure_failures: raise RuntimeError('Baseline infrastructure unavailable')
                observed = bool(baseline.failed_runs)
                if not observed and task.verification_config.sanitizer_required:
                    checked_task=instrumented_task(task)
                    checked = await CCompiler().compile(checked_task,box,SanitizerConfig().flags)
                    save(base_folder/'tsan-build.json',checked.model_dump(mode='json'))
                    if not checked.success: raise RuntimeError('Required baseline sanitizer unavailable')
                    races = await campaign.run(checked_task,box,runs=3)
                    if races.infrastructure_failures or any(runtime_unavailable(r.stderr) for r in races.runs):
                        raise RuntimeError('Baseline sanitizer infrastructure unavailable')
                    sanitizer_baseline=races.compact()
                    observed = bool(races.failed_runs)
                if not observed:
                    result['status']='baseline_clean'; result['stop_reason']='No observed failure; no model call.'
                    return result
            for stage in stages:
                attempt_folder = folder/stage; attempt_folder.mkdir()
                row={'stage':stage,'outcome':'unknown','model_calls':0,'tokens':0,'cost_usd':0,'reserved_usd':0,'false_fix':False}
                rows.append(row)
                self.progress({'stage':stage+' inference','attempts':rows})
                used=sum(r['tokens'] for r in rows if r.get('tokens') is not None)
                tick=perf_counter(); proposal=None
                if stage=='fine_tuned':
                    chat=tagged_messages(sources,description,headers,requirements)
                    bound=sum(len(m['content'].encode('utf-8'))+64 for m in chat)
                    if bound>min(max_input_tokens,6144) or used+bound+2048>max_total_tokens:
                        row.update(outcome='skipped',error_code='local_context_capacity',inference_ms=0)
                        save(attempt_folder/'result.json',row); continue
                    save(attempt_folder/'messages.json',chat)
                    row.update(model_calls=1,tokens=None); result['model_calls']+=1
                    self.progress({'attempts':rows})
                    response=await local_generate(self.root,chat,model_root=self.model_root)
                    save(attempt_folder/'response.json',response)
                    row.update(model=response['model'],input_tokens=response['input_tokens'],output_tokens=response['output_tokens'],
                               tokens=response['input_tokens']+response['output_tokens'],response=response['text'],
                               adapter_sha256=response.get('adapter_sha256'))
                    try:
                        if response['finish_reason']!='stop': raise ValueError('output_budget_exhausted')
                        proposal,canonical=tagged_to_proposal(response['text'],sources)
                        row['canonical_response']=canonical
                    except (ValueError,TypeError) as exc:
                        row.update(outcome='invalid_output',error_code='no_change' if str(exc)=='No repair proposed' else ('output_budget_exhausted' if str(exc)=='output_budget_exhausted' else 'invalid_local_contract'))
                else:
                    previous=[{k:r.get(k) for k in ('stage','outcome','error_code','verification','validation')} for r in rows[:-1]]
                    context={'description':description,'requirements':requirements,'observed_baseline':baseline.compact(),'baseline_sanitizer':sanitizer_baseline,'previous_attempts':previous}
                    chat=repair_messages(sources,headers,context)
                    plan=plan_remote_repair(options[stage],chat,sources,max_cost_usd=max_cost_usd-result['reserved_usd'],
                        max_input_tokens=max_input_tokens,max_output_tokens=CAPS[stage],max_total_tokens=max_total_tokens-used)
                    save(attempt_folder/'payload.json',plan.payload);save(attempt_folder/'pricing.json',options[stage])
                    call_id=uuid.uuid4().hex
                    self.ledger.reserve(call_id,bound_usd=plan.reservation_usd,model=options[stage]['id'],evidence=str(attempt_folder.relative_to(self.root)))
                    row.update(model_calls=1,tokens=None,cost_usd=None,reserved_usd=plan.reservation_usd,model=options[stage]['id'],ledger_call_id=call_id)
                    result['model_calls']+=1;result['remote_model_calls']+=1;result['reserved_usd']+=plan.reservation_usd
                    self.progress({'attempts':rows,'reserved_usd':result['reserved_usd']})
                    try:
                        async with httpx.AsyncClient(timeout=150) as client:
                            response=await client.post('https://api.tokenfactory.nebius.com/v1/chat/completions',json=plan.payload,
                                headers={'Authorization':'Bearer '+os.environ['NEBIUS_API_KEY']})
                        save(attempt_folder/'http-status.json',{'status':response.status_code})
                        if response.status_code!=200:
                            save(attempt_folder/'provider-error.json',{'status':response.status_code,'body':response.text[:5000]})
                            raise RuntimeError('Provider rejected request; no automatic replay')
                        data=response.json();save(attempt_folder/'response.json',data)
                        parsed=parse_remote_response(data,plan,sources)
                        row.update(input_tokens=parsed.input_tokens,output_tokens=parsed.output_tokens,tokens=parsed.tokens,
                                   reasoning_tokens=parsed.reasoning_tokens,cost_usd=parsed.cost_usd,response=parsed.text,
                                   error_code=parsed.error_code,validation=list(parsed.validation),outcome=parsed.outcome)
                        if parsed.usage_known:
                            self.ledger.settle(call_id,actual_usd=parsed.cost_usd,input_tokens=parsed.input_tokens,output_tokens=parsed.output_tokens)
                        else:
                            self.ledger.unknown(call_id,parsed.error_code or 'unknown_usage')
                        proposal=parsed.proposal
                        if parsed.canonical_text: row['canonical_response']=parsed.canonical_text
                    except BaseException:
                        self.ledger.unknown(call_id,'request_interrupted_or_provider_error')
                        raise
                row['inference_ms']=(perf_counter()-tick)*1000
                if proposal is None:
                    save(attempt_folder/'result.json',row);self.progress({'attempts':rows})
                    if row['outcome']=='unknown': result['stop_reason']=row.get('error_code');break
                    continue
                row['patch']=proposal.patch;(attempt_folder/'candidate.patch').write_text(proposal.patch,encoding='utf-8')
                self.progress({'stage':stage+' verification: original tests, 100 stress, semantics, 3 TSan','attempts':rows})
                async with NebiusSandboxBackend() as box:
                    await box.upload_project(task.workspace,task.source_files+task.support_files)
                    applied=await box.apply_patch(proposal.patch,task.source_files);save(attempt_folder/'patch-application.json',applied.model_dump(mode='json'))
                    if not applied.success:
                        row.update(outcome='invalid_output',error_code='canonical_patch_rejected')
                    else:
                        for name in task.support_files:
                            if hashlib.sha256((await box.read_file(name)).encode()).hexdigest()!=hashes[name]:
                                raise RuntimeError('Protected source changed')
                        candidate={n:await box.read_file(n) for n in task.source_files}
                        save(attempt_folder/'candidate-sources.json',candidate)
                        v=await ConcurrencyVerifier(campaigns=self.campaign_factory(attempt_folder)).verify_workspace(task,box,baseline)
                        save(attempt_folder/'verification.json',v.model_dump(mode='json'))
                        hooks=all(candidate[n].count('sched_yield(')==sources[n].count('sched_yield(') for n in sources)
                        if v.passed and hooks: require_verified(v.model_dump(mode='json'),config)
                        row.update(outcome='unknown' if v.infrastructure_failures else ('verified' if v.passed and hooks else 'rejected'),
                                   verification=verification_summary(v,hooks),verification_ms=v.duration_ms,false_fix=v.false_fix or not hooks)
                        if row['outcome']=='verified': require_verified(v.model_dump(mode='json'),config)
                save(attempt_folder/'result.json',row);self.progress({'attempts':rows})
                if row['outcome']=='verified':result['status']='verified';break
                if row['outcome']=='unknown':break
            else:
                result['status']='rejected'
        except Exception as exc:
            result.update(status='unknown',error=type(exc).__name__,stop_reason='Stopped without automatic replay')
        finally:
            result['tokens']=None if any(r.get('model_calls') and r.get('tokens') is None for r in rows) else sum(r.get('tokens') or 0 for r in rows)
            result['cost_usd']=None if any(r.get('reserved_usd') and r.get('cost_usd') is None for r in rows) else sum(r.get('cost_usd') or 0 for r in rows)
            result['false_fix']=any(r.get('false_fix') for r in rows)
            result['end_to_end_ms']=(perf_counter()-started)*1000
            result['inference_ms']=sum(r.get('inference_ms',0) for r in rows)
            result['verification_ms']=sum(r.get('verification_ms',0) for r in rows)
            final=next((r for r in reversed(rows) if r.get('patch')),rows[-1] if rows else {})
            for key in ('patch','response','verification'):result[key]=final.get(key)
            save(folder/'result.json',result)
        return result
