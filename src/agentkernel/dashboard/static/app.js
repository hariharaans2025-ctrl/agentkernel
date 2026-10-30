'use strict';
const $ = id => document.getElementById(id);
const state = {config:null,runs:[],selected:null,tab:'response',busy:false,last:''};
function node(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;}
function error(message){$('error').textContent=message||'';$('error').hidden=!message;}
async function api(path,body){const r=await fetch(path,{cache:'no-store',...(body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.config.csrf},body:JSON.stringify(body)})});const data=await r.json();if(!r.ok)throw new Error(data.error||'Request failed');return data;}
const format = value => value===null||value===undefined?'NOT MEASURED':Number(value).toLocaleString();
const seconds = ms => ms===null||ms===undefined?'NOT MEASURED':(ms/1000).toFixed(2)+' s';
const money = value => value===null||value===undefined?'Unknown':'$'+Number(value).toFixed(5);
const date = value => value?new Date(value).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}):'—';
function selectedTiers(){return [...document.querySelectorAll('#models input:checked')].map(n=>n.value);}
const tierName = tier => tier==='ADAPTIVE_V4'?'Adaptive v4':tier[0]+tier.slice(1).toLowerCase();
function v4Problem(f,tiers){if(!f)return '';const v4=tiers.includes('ADAPTIVE_V4');if(f.v4&&!v4)return 'This product-v1 case runs with Adaptive v4 only.';if(v4&&!f.v4)return 'Adaptive v4 needs a complete contract (original tests, semantics, 3× TSan). Choose a product-v1 case (e.g. audit_3).';if(v4&&tiers.length>1)return 'Run Adaptive v4 on its own.';return '';}
function setup(){
 const c=state.config;
 for(const f of c.fixtures){const option=node('option','',f.id+' · '+f.bug.replaceAll('_',' '));option.value=f.id;$('fixture').append(option);}
 if(c.fixtures.some(f=>f.id==='deadlock_001'))$('fixture').value='deadlock_001';
 for(const [tier,id] of Object.entries(c.models)){
  const label=node('label','model-choice');const input=node('input');input.type='checkbox';input.value=tier;input.checked=tier==='ADAPTIVE';input.addEventListener('change',budget);
  label.append(input,node('strong','',tierName(tier)),node('small','',id));$('models').append(label);
 }
 $('fixture').addEventListener('change',budget);budget();
}
function budget(){
 const f=state.config.fixtures.find(f=>f.id===$('fixture').value);const tiers=selectedTiers();const count=tiers.length;const requestCount=tiers.reduce((n,t)=>n+(t==='ADAPTIVE'?3:t==='ADAPTIVE_V4'?2:1),0);const outputCap=tiers.reduce((n,t)=>n+(t==='ADAPTIVE'?4864:t==='ADAPTIVE_V4'?16384:2048),0);
 $('fixture-meta').textContent=f?`${f.baseline_runs} baseline runs · ${f.verification_runs} verification runs per accepted patch`+(f.v4?' · original tests + semantic oracle + 3× TSan (Adaptive v4 case)':''):'';
 const problem=v4Problem(f,tiers);
 $('budget').textContent=problem||(tiers.includes('ADAPTIVE_V4')?`Up to 2 paid Nemotron Ultra requests · ${format(outputCap)} total output-token cap. The second call happens only if execution rejects the first candidate, and it receives the failed candidate plus verifier evidence. Uses your .env Nebius keys.`:`Up to ${requestCount} paid requests · ${format(outputCap)} total output-token cap. One attempt per tier; adaptive uses 768 for triage and 2,048 per repair. Ultra follows failed verification only.`);
 $('start').disabled=state.busy||!count||!f||!!problem||!state.config.credentials_configured;
}
function connection(data){const ready=data.status==='ready';$('connection').textContent=ready?'Connected':data.status==='error'?'Connection issue':'Not checked';$('connection').className='pill '+(ready?'good':data.status==='error'?'bad':'');
 for(const input of document.querySelectorAll('#models input')){const available=data.models?.[input.value];input.parentElement.title=available===false?'Configured model unavailable in your catalog':state.config.models[input.value];}
 if(data.status==='error')error('Connection check failed. Check the private Nebius credentials and sandbox permissions. '+(data.model_error||data.sandbox?.error||''));
}
function metric(label,value,note){const n=node('div','metric');n.append(node('div','metric-label',label),node('div','metric-value',value),node('div','metric-note',note));return n;}
function render(){
 const run=state.runs.find(r=>r.id===state.selected);paintSpine(run);const key=JSON.stringify([run,state.tab,state.runs.map(r=>[r.id,r.status])]);
 state.busy=state.runs.some(r=>['queued','running'].includes(r.status));budget();
 if(key===state.last)return;state.last=key;
 $('history-list').replaceChildren();
 for(const r of state.runs){const button=node('button','history-item'+(r.id===state.selected?' selected':''));const left=node('div');left.append(node('strong','',r.fixture+' / '+r.tiers.join(' + ')),node('small','',date(r.created_at)+' · '+(r.provenance==='real'?'HISTORICAL · real model comparison':'HISTORICAL · saved response / sandbox replay')));button.append(left,node('span','pill',r.status));button.onclick=()=>{state.selected=r.id;render();};$('history-list').append(button);}
 if(!state.runs.length)$('history-list').append(node('div','empty','Your first comparison will appear here.'));
 $('performance').replaceChildren();$('outputs').replaceChildren();$('events').replaceChildren();$('metrics').replaceChildren();$('technical').replaceChildren();$('combined').replaceChildren();
 $('export').disabled=!run;$('stop').hidden=!run||!['queued','running'].includes(run.status);$('stop').disabled=!!run?.stop_requested;
 $('stop').textContent=run?.stop_requested?'Stopping after current model…':'Stop after current model';
 if(!run){$('run-status').textContent='No run selected';$('metrics').append(metric('Verified candidates','—','Awaiting execution'),metric('Output tokens','—','Reported by provider'),metric('Inference cost','—','No comparison yet'),metric('Verification runs','—','Uses fixture settings'));$('outputs').append(node('div','empty','Select models and run a comparison. Their responses and patches will appear side by side.'));return;}
 const replay=run.provenance!=='real';const entries=Object.entries(run.results);const verified=entries.filter(([,v])=>v.job?.status==='verified').length;
 const measured=entries.flatMap(([,v])=>v.inferences||[v.inference]).filter(Boolean);const tokenValues=measured.map(v=>v.metadata?.actual_output_tokens);
 const tokens=!replay&&tokenValues.length&&tokenValues.every(v=>v!=null)?tokenValues.reduce((a,b)=>a+b,0):null;
 const costs=entries.map(([,v])=>v.job?.cost_usd);const totalCost=!replay&&entries.length&&entries.every(([,v])=>v.job?.metadata?.pricing_authoritative)&&costs.every(v=>v!=null)?costs.reduce((a,b)=>a+b,0):null;
 const completedRuns=entries.reduce((a,[,v])=>a+(v.job?.verification?.total_runs||0),0);
 $('metrics').append(metric('Verified candidates',verified+' / '+entries.length,'Passed configured campaign'),metric('Output tokens',format(tokens),replay?'Replay · no new inference':'Actual provider usage'),metric('Inference cost',money(totalCost),'Excludes sandbox compute'),metric('Verification runs',format(completedRuns),`${run.verification_runs} required per accepted patch`));
 const benchmark=run.benchmark; const combined=benchmark?.combined;
 if(combined){
  $('combined').append(metric('Combined total tokens',format(combined.total_tokens),'Input + output, all selected models'),metric('Combined inference time',seconds(combined.inference_ms),'Sum of independent requests'),metric('Comparison wall time',seconds(combined.end_to_end_ms),'Includes sandbox and orchestration'),metric('Measured verification pass rate',combined.verification_pass_rate==null?'—':(combined.verification_pass_rate*100).toFixed(1)+'%',`${combined.models_with_verification} of ${combined.selected_models} models reached verification`),metric('Combined verification time',seconds(combined.verification_ms),'Measured campaigns only'),metric('Deadlocks / races / crashes',`${format(combined.deadlocks)} / ${format(combined.races)} / ${format(combined.crashes)}`,'Measured campaigns only'));
  const rows=[['Total tokens','total_tokens',format],['Reasoning tokens','reasoning_tokens',format],['Output budget used','output_budget_utilization',v=>v==null?'—':(v*100).toFixed(1)+'%'],['Effective output tokens/s','effective_output_tokens_per_second',v=>v==null?'—':v.toFixed(2)],['End-to-end time','end_to_end_ms',seconds],['Baseline time','baseline_ms',seconds],['Baseline failures','baseline_failures',format],['Patch accepted','patch_accepted',v=>v==null?'—':v?'Yes':'No'],['Lines added','patch_added_lines',format],['Lines removed','patch_removed_lines',format],['Candidate build passed','build_passed',v=>v==null?'—':v?'Yes':'No'],['Verification time','verification_ms',seconds],['Deadlocks','deadlocks',format],['Races','races',format],['Crashes','crashes',format],['Infrastructure failures','infrastructure_failures',format],['Sanitizer','sanitizer_status',v=>v||'—'],['Finish reason','finish_reason',v=>v||'—'],['Semantic passed','semantic_passed',v=>v==null?'Not measured':String(v)],['Sanitizer passed','sanitizer_passed',v=>v==null?'Not measured':String(v)],['False fix','false_fix',String],['Final tier','final_tier',v=>v||'—'],['Nano calls','nano_calls',format],['Super calls','super_calls',format],['Ultra calls','ultra_calls',format]];
  const heading=node('tr');heading.append(node('th','','Technical metric'));for(const [tier] of entries)heading.append(node('th','',tier));$('technical').append(heading);
  for(const [label,field,fmt] of rows){const row=node('tr');row.append(node('th','',label));for(const [tier] of entries)row.append(node('td','',fmt(benchmark.individual[tier]?.[field])));$('technical').append(row);}
 }
 $('run-status').textContent=run.status;$('run-status').className='pill '+(run.status==='completed'?'good':'');
 $('comparison-label').textContent=run.fixture+' · '+(['queued','running'].includes(run.status)?'LIVE':replay?'HISTORICAL / SAVED REPLAY':'HISTORICAL / REAL MODELS');
 $('run-note').textContent=(run.note||'')+' Passing tests do not prove semantic equivalence.';
 for(const [tier,item] of entries){
  const job=item.job,inf=replay?null:item.inference;const meta=inf?.metadata||{};const verification=job?.verification;
  const tr=node('tr');const td=node('td');td.append(node('span','model-icon',tier[0]),document.createTextNode(tierName(tier)),node('span','sub',item.model));tr.append(td);
  const outcome=job?.status||item.status;const statusCell=node('td');statusCell.append(node('span','pill '+(outcome==='verified'?'good':['failed','unresolved','execution_blocked'].includes(outcome)?'bad':''),outcome.replaceAll('_',' ')),node('span','sub',item.stage+(item.campaign_progress?' · '+item.campaign_progress.completed+'/'+item.campaign_progress.required:'')));tr.append(statusCell);
  tr.append(node('td','',seconds(benchmark?.individual[tier]?.inference_ms)),node('td','',format(benchmark?.individual[tier]?.input_tokens)+' / '+format(benchmark?.individual[tier]?.output_tokens)),node('td','',verification?`${verification.passed_runs} / ${verification.total_runs}`:(job?'Not reached':'Pending')),node('td','',replay?'Replay':money(job?.metadata?.pricing_authoritative?job.cost_usd:null)));$('performance').append(tr);
  const card=node('article','output-card');const heading=node('h3');heading.append(document.createTextNode(tier+' / '+state.tab),node('span','label',job?.status==='verified'?'CAMPAIGN PASSED':item.stage));card.append(heading);
  if(state.tab==='route'){
   const flow=node('div','run-note');const route=job?.route||[...new Set((item.inferences||[]).map(i=>i.tier))];
   if(!job&&item.active_tier&&!route.includes(item.active_tier))route.push(item.active_tier);
   const steps=['BASELINE',...route,job?'FINAL: '+job.status:item.stage];
   for(const [index,step] of steps.entries()){if(index)flow.append(document.createTextNode(' → '));flow.append(node('span','pill',step));}card.append(flow);
  }
  let text='Waiting for this model…';
  if(state.tab==='response'&&item.response){try{text=JSON.stringify(JSON.parse(item.response),null,2);}catch{text=item.response;}}
  if(state.tab==='route'&&tier==='ADAPTIVE_V4')text=JSON.stringify({flow:['BASELINE','DETERMINISTIC ROUTER (v4)','ULTRA REPAIR','VERIFY','ULTRA + FAILED-CANDIDATE EVIDENCE (only if rejected)','FINAL RESULT'],route:job?.route||[],router:job?.v4?.route_decision||null,recoveries:job?.v4?.recoveries||null,phases_ms:job?.v4?.phases_ms||null,stop_reason:job?.v4?.stop_reason||null,attempts:job?.metadata?.model_attempts||[],current_stage:item.stage},null,2);
  else if(state.tab==='route')text=JSON.stringify({flow:['BASELINE','NANO TRIAGE','SUPER REPAIR','VERIFY','OPTIONAL ULTRA','FINAL RESULT'],route:job?.route||[],attempts:job?.metadata?.model_attempts||[],current_stage:item.stage,progress:item.campaign_progress||null,trace:job?.metadata?.observability||null},null,2);
  if(state.tab==='patch')text=job?.repairs?.map(r=>r.proposal?.patch||'').filter(Boolean).join('\n\n')||(job?'No valid patch was accepted.':'Patch validation has not finished.');
  if(state.tab==='evidence')text=JSON.stringify({stage:item.stage,error:item.error||meta.error_code||null,detail:item.detail||meta.error_hint||null,baseline:job?.baseline||null,verification:verification||null,inference:replay?'Saved response replay; no new provider metrics':{finish_reason:meta.finish_reason,reasoning_tokens:meta.actual_reasoning_tokens,requested_thinking:meta.requested_enable_thinking??'Provider default',output_limit:meta.requested_max_output_tokens},observability:job?.metadata?.observability||null},null,2);
  if(item.status==='failed'&&!item.response&&state.tab==='response')text=item.detail||item.error||'Execution failed before a response was received.';
  if(item.status==='skipped')text='No request made. Stopped before this model.';
  card.append(node('pre','',text));$('outputs').append(card);
 }
 for(const event of [...(run.events||[])].reverse().slice(0,25)){const li=node('li');li.append(node('time','',new Date(event.at).toLocaleTimeString()),node('b','',event.tier),node('span','',event.message));$('events').append(li);}
 if(!run.events?.length)$('events').append(node('li','',replay?'Imported from saved sandbox evidence. No live job is running.':'Waiting for the first event.'));
}
async function refresh(){try{state.runs=await api('/api/runs');if(!state.selected&&state.runs.length)state.selected=state.runs[0].id;render();}catch(e){error('Cannot reach the controller. '+e.message);}}
$('check').onclick=async()=>{$('check').disabled=true;error('');try{connection(await api('/api/check',{}));}catch(e){error(e.message);}finally{$('check').disabled=false;}};
$('start').onclick=async()=>{if(state.busy)return;state.busy=true;budget();error('');try{const run=await api('/api/runs',{fixture:$('fixture').value,tiers:selectedTiers(),client_id:crypto.randomUUID()});state.selected=run.id;await refresh();}catch(e){error(e.message);await refresh();}};
$('stop').onclick=async()=>{try{await api('/api/runs/'+state.selected+'/stop',{});await refresh();}catch(e){error(e.message);}};
$('export').onclick=()=>{const run=state.runs.find(r=>r.id===state.selected);if(!run)return;const url=URL.createObjectURL(new Blob([JSON.stringify(run,null,2)],{type:'application/json'}));const a=node('a');a.href=url;a.download='agentkernel-'+run.id+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
for(const button of document.querySelectorAll('.tab'))button.onclick=()=>{state.tab=button.dataset.tab;for(const b of document.querySelectorAll('.tab')){b.classList.toggle('active',b===button);b.setAttribute('aria-selected',String(b===button));}render();};
(async()=>{try{state.config=await api('/api/config');setup();connection(state.config.connection);await refresh();if(!state.config.credentials_configured)error('Add your Nebius API key and project ID to the private .env file, then restart the controller.');setInterval(refresh,2000);}catch(e){error(e.message);}})();


// Presentation layer over the existing saved report and live-run adapters.
const stages=['BASELINE','FINGERPRINT','NANO','SUPER','PATCH','SANDBOX','BUILD','STRESS','SEMANTIC','TSAN','VERIFY'];
const modeNames={nano_only:'NANO ONLY',super_only:'SUPER ONLY',ultra_only:'ULTRA ONLY',adaptive:'AGENTKERNEL ADAPTIVE'};
let finalReport=null, selectedEvidence=0;
function textAt(id,value){$(id).textContent=value==null?'NOT MEASURED':String(value);}
function paintSpine(run){
 const spine=$('live-spine');if(!spine)return;spine.replaceChildren();
 const active=run&&['queued','running'].includes(run.status);const current=active?Object.values(run.results||{}).find(v=>v.status==='running'):null;
 const label=String(current?.stage||'').toLowerCase();
 let activeStage=current?.active_tier||'';
 if(label.includes('baseline')||label.includes('reproducing'))activeStage='BASELINE';
 else if(label.includes('applying'))activeStage='PATCH';
 else if(label.includes('compil'))activeStage='BUILD';
 else if(label.includes('verifying'))activeStage=current?.campaign_progress?'STRESS':'SANDBOX';
 else if(label.includes('starting sandbox'))activeStage='SANDBOX';
 spine.dataset.active=active?activeStage:'';
 for(const stage of stages){const n=node('span','live-stage',stage);if(active&&activeStage===stage)n.classList.add('active');spine.append(n);}
 spine.append(node('span','live-stage escalation','FAIL → EVIDENCE → ULTRA → REVERIFY'));
 spine.setAttribute('aria-label',active?'Live execution stages':'Execution stages; no active run');
}
function verdict(row){if(!row)return ['INTERRUPTED / UNKNOWN','interrupted'];if(row.status==='verified')return ['VERIFIED','verified'];if(row.false_fix)return ['FALSE FIX','false-fix'];if(row.format_rejections)return ['INVALID OUTPUT','invalid'];return ['INCOMPLETE OUTPUT','incomplete'];}
function gate(v){return v==null?'NOT MEASURED':v?'PASS':'FAIL';}
function addForensic(label,value){const part=node('article','forensic-step');part.append(node('h3','',label),node('pre','',value==null?'NOT MEASURED':typeof value==='string'?value:JSON.stringify(value,null,2)));$('forensic-content').append(part);return part;}
async function selectEvidence(fixture,mode,scroll=true){
 const ticket=++selectedEvidence;const row=finalReport.rows.find(r=>r.fixture===fixture&&r.mode===mode);const [label,cls]=verdict(row);
 for(const b of document.querySelectorAll('.matrix-button')){const selected=b.dataset.fixture===fixture&&b.dataset.mode===mode;b.classList.toggle('selected',selected);b.setAttribute('aria-pressed',String(selected));}
 textAt('evidence-title',fixture+' / '+modeNames[mode]);textAt('evidence-verdict',label);$('evidence-verdict').className='pill '+(cls==='verified'?'good':cls==='false-fix'?'bad':'');
 $('evidence-stats').replaceChildren();for(const [title,value] of [['ROUTE',row?.route?.join(' → ')||'UNKNOWN'],['STRESS PASSES',row?.verification_runs!=null?row.passes+' / '+row.verification_runs:'NOT MEASURED'],['SEMANTIC',gate(row?.semantic_passed)],['TSAN',gate(row?.sanitizer_passed)],['INPUT / OUTPUT TOKENS',row?format(row.input_tokens)+' / '+format(row.output_tokens):'UNKNOWN'],['DOLLAR COST','UNKNOWN']])$('evidence-stats').append(metric(title,value,''));
 textAt('evidence-provenance',row?'FINAL COMBINED BENCHMARK · '+row.source_report+' · events: '+row.source_events:'FINAL COMBINED BENCHMARK · Original Super-only job interrupted. No result preserved. Excluded from success and failure denominators.');
 textAt('evidence-details',JSON.stringify(row?{status:row.status,route:row.route,model_attempts:row.model_attempts,baseline:row.baseline,verification:{execution:row.execution_passed,semantic:row.semantic_passed,sanitizer:row.sanitizer_passed},observability:row.observability,grounding:row.grounding}:{status:'INTERRUPTED / UNKNOWN',outcome:null,additional_usage:'UNKNOWN'},null,2));
 textAt('patch-context',fixture+' / '+modeNames[mode]+' · FINAL COMBINED BENCHMARK');$('forensic-content').replaceChildren();
 const original=addForensic('ORIGINAL SOURCE','Loading preserved source identity…');
 const exact=addForensic('EXACT-SOURCE EDIT','Loading recorded model output…');
 const repairs=row?.repairs||[];
 addForensic('CANONICAL PATCH',repairs.length?repairs.map(p=>p.proposal?.patch||'NOT PRESERVED').join('\n\n'):row?'No accepted candidate.':'UNKNOWN — job interrupted.');
 addForensic('APPLICATION RESULT',repairs.length?repairs.map(p=>({tier:p.tier,...p.patch})):'NOT MEASURED');
 addForensic('BUILD RESULT',repairs.length?repairs.map(p=>({tier:p.tier,build:p.verification?.evidence?.build??null})):'NOT MEASURED');
 addForensic('STRESS RESULT',repairs.length?repairs.map(p=>({tier:p.tier,passed:p.verification?.execution_passed,total_runs:p.verification?.total_runs,passes:p.verification?.passed_runs,deadlocks:p.verification?.deadlock_count,campaign:p.verification?.evidence?.campaign??null})):'NOT MEASURED');
 addForensic('SEMANTIC RESULT',repairs.length?repairs.map(p=>({tier:p.tier,result:p.verification?.evidence?.semantic??null})):'NOT MEASURED');
 addForensic('TSAN RESULT',repairs.length?repairs.map(p=>({tier:p.tier,result:p.verification?.evidence?.sanitizer??null})):'NOT MEASURED');
 addForensic('FINAL VERDICT',label+(row?.status==='verified'?' — PASSED CONFIGURED VERIFICATION.':row?.false_fix?' — APPLIED CANDIDATE FAILED CONFIGURED VERIFICATION.':''));
 if(scroll)$('evidence').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
 const results=await Promise.allSettled([api('/api/benchmark/source/'+fixture),api('/api/benchmark/events/'+mode+'/'+fixture)]);
 if(ticket!==selectedEvidence)return;
 const source=results[0].status==='fulfilled'?results[0].value:null;
 original.querySelector('pre').textContent=source&&row?.source_sha256?.['main.c']===source.sha256?'main.c · SHA-256 MATCHES RECORDED SOURCE\n\n'+source.source:'NOT AVAILABLE AS VERIFIED ORIGINAL SOURCE'+(source?' — no matching recorded hash for this outcome.':'');
 const events=results[1].status==='fulfilled'?results[1].value.events:[];const summary=events.find(e=>e.event_type==='concurrency_job')?.summary;
 const attempts=summary?.metadata?.attempt_details||[];
 const edits=attempts.map(a=>{try{const proposal=JSON.parse(a.output_text);return {tier:a.tier,edits:proposal.edits??null};}catch{return null;}}).filter(a=>a?.edits);
 exact.querySelector('pre').textContent=edits.length?JSON.stringify(edits,null,2):'Exact-source edits were not preserved as complete parseable output for this outcome. Canonical patch and available evidence are shown separately.';
}
function ticks(id,count){$(id).replaceChildren();if(count==null){$(id).textContent='UNKNOWN';return;}for(let i=0;i<count;i++)$(id).append(node('i'));$(id).setAttribute('aria-label',count+' Ultra calls');}
async function loadCombined(){
 try{
  const d=await api('/api/benchmark/combined');if(!d.mode_comparison||!d.rows?.length)throw new Error('Final combined evidence unavailable');finalReport=d;
  const rows=d.rows,m=d.mode_comparison,a=d.adaptive_analysis,adaptive=m.adaptive,ultra=m.ultra_only;
  textAt('measured-jobs',rows.length+' / '+(rows.length+(d.interrupted_unknown?1:0)));textAt('interrupted-count',(d.interrupted_unknown?1:0)+' INTERRUPTED / UNKNOWN');textAt('benchmark-source','IMMUTABLE ORIGINAL + CONTINUATION EVIDENCE');
  textAt('adaptive-jobs',adaptive.completed_jobs);textAt('solved-super',a.super_solved_fixtures.length);textAt('escalated-ultra',a.escalated_fixtures.length);textAt('triage-stops',a.triage_only_unresolved.length);
  textAt('ultra-count',ultra.calls_by_tier.ULTRA);textAt('adaptive-ultra-count',adaptive.calls_by_tier.ULTRA);ticks('ultra-ticks',ultra.calls_by_tier.ULTRA);ticks('adaptive-ticks',adaptive.calls_by_tier.ULTRA);
  textAt('ultra-reduction',ultra.calls_by_tier.ULTRA?Math.round(100*(1-adaptive.calls_by_tier.ULTRA/ultra.calls_by_tier.ULTRA)):'UNKNOWN');
  textAt('adaptive-tokens',format(adaptive.total_tokens));textAt('ultra-tokens',format(ultra.total_tokens));textAt('adaptive-time',seconds(adaptive.mean_end_to_end_latency_ms)+' mean end-to-end');textAt('ultra-time',seconds(ultra.mean_end_to_end_latency_ms)+' mean end-to-end');
  const verified=rows.filter(r=>r.status==='verified');textAt('verified-outcomes',verified.length);textAt('verified-races',verified.filter(r=>r.fixture.startsWith('race_')).length);
  const failure=rows.find(r=>r.fixture==='deadlock_001'&&r.mode==='super_only');
  if(failure){textAt('survivors',failure.passes+' / '+failure.verification_runs);textAt('deadlock-survivors',failure.deadlocks);textAt('failure-percent',Math.round(failure.passes/failure.verification_runs*100));textAt('failure-verdict',failure.false_fix?'REPAIR REJECTED / FALSE FIX':failure.status);for(const [key,value] of Object.entries({applied:failure.patch_accepted?'APPLIED':'NOT APPLIED',build:gate(failure.build_passed),semantic:gate(failure.semantic_passed)}))document.querySelector('[data-failure="'+key+'"]').textContent=value;}
  const worked=[a.super_solved_fixtures.length+' Adaptive repairs verified at Super','Ultra used on '+a.escalated_fixtures.length+'/'+adaptive.completed_jobs+' Adaptive jobs',a.unnecessary_ultra_fixtures.length+' Ultra calls after successful Super verification','Execution verification caught plausible false fixes','All verified race outcomes passed required TSan checks'];
  const limits=[a.recovered_fixtures.length+' Super failures recovered by Ultra',a.triage_only_unresolved.length+' Adaptive jobs stopped at incomplete Nano triage','Adaptive used more tokens than Ultra-only','Adaptive was slower on average','One job remains interrupted / unknown'];
  for(const [id,items] of [['worked',worked],['limitations',limits]]){$(id).replaceChildren(...items.map(t=>node('li','',t)));}
  $('mode-summary').replaceChildren();for(const [mode,v] of Object.entries(m)){const part=node('article','mode-measure');part.append(node('h3','',modeNames[mode]),node('strong','',v.verified_repairs+' / '+v.completed_jobs),node('p','', 'VERIFIED · '+(v.verified_rate_completed_jobs*100).toFixed(1)+'%'),node('p','',v.patches_accepted+' accepted candidates'),node('p','',v.false_fix_denominator?v.false_fixes+' / '+v.false_fix_denominator+' false fixes · '+(v.false_fix_rate_evaluated_candidates*100).toFixed(1)+'%':'False-fix rate: NOT MEASURED'),node('p','',format(v.total_tokens)+' tokens'),node('p','',mode==='nano_only'?'Incomplete under this frozen configuration.':mode==='super_only'?'9 measured · 1 interrupted / unknown':v.recorded_calls+' model calls'));$('mode-summary').append(part);}
  const fixtures=[...new Set(rows.map(r=>r.fixture))].sort();$('benchmark-matrix').replaceChildren();
  for(const fixture of fixtures){const tr=node('tr');const th=node('th','',fixture);th.scope='row';tr.append(th);for(const mode of Object.keys(modeNames)){const r=rows.find(r=>r.fixture===fixture&&r.mode===mode);const [label,cls]=verdict(r);const td=node('td');const b=node('button','matrix-button '+cls,label);b.dataset.fixture=fixture;b.dataset.mode=mode;b.setAttribute('aria-label',fixture+', '+modeNames[mode]+': '+label);b.setAttribute('aria-pressed','false');if(r?.mode==='adaptive')b.append(node('small','',r.route.join(' → ')));b.onclick=()=>selectEvidence(fixture,mode);td.append(b);tr.append(td);}$('benchmark-matrix').append(tr);}
  await selectEvidence('deadlock_001','super_only',false);
 }catch(e){textAt('benchmark-error','Evidence unavailable. No benchmark values have been substituted. '+e.message);textAt('benchmark-source','UNAVAILABLE');}
}
for(const [i,label] of ['BASELINE','FINGERPRINT','NANO','SUPER','EXACT-SOURCE EDIT','CANONICAL PATCH','NEBIUS SANDBOX','BUILD','100× STRESS','SEMANTIC ORACLE','TSAN WHEN REQUIRED','VERIFY'].entries()){const part=node('div','pipeline-step');part.append(node('small','',String(i+1).padStart(2,'0')),document.createTextNode(label));$('story-pipeline').append(part);}
const sceneObserver=new IntersectionObserver(entries=>{for(const e of entries)if(e.isIntersecting)e.target.classList.add('in-view');},{threshold:.2});document.querySelectorAll('.scene').forEach(s=>sceneObserver.observe(s));
function failureMotion(){const box=$('failure').getBoundingClientRect();const progress=-box.top/(box.height-innerHeight);$('failure').classList.toggle('failed',progress>.22);}
let framePending=false;addEventListener('scroll',()=>{if(!framePending){framePending=true;requestAnimationFrame(()=>{failureMotion();framePending=false;});}},{passive:true});addEventListener('resize',failureMotion);failureMotion();loadCombined();
