"""Audit a completed comparison and state only measured per-suite tradeoffs."""
import argparse
import hashlib
import json
from pathlib import Path
from agentkernel.repository.learning import require_verified


def main(path):
    path=Path(path);out=path.parent;protocol=json.loads(path.read_text())
    view=json.loads((out/'comparison-view.json').read_text())
    if not view['complete'] or len(view['rows'])!=len(protocol['jobs']):raise ValueError('Comparison is incomplete')
    rows={(r['case'],r['arm']):r for r in view['rows']}
    expected={(r['case'],r['arm']) for r in protocol['jobs']}
    if len(rows)!=len(protocol['jobs']) or set(rows)!=expected:raise ValueError('Missing or duplicate arms')
    unnecessary=[];recovered=[];stopped=[];unresolved=[];better_cost=[];worse_cost=[];gates=[]
    paid_calls=0;known_cost=0;unknown_cost=False
    for job in protocol['jobs']:
        r=rows[job['case'],job['arm']];attempts=r.get('attempts',[])
        paid_calls+=r.get('remote_model_calls',0)
        if r.get('cost_usd') is None:unknown_cost=True
        else:known_cost+=r['cost_usd']
        for name,h in job['files'].items():
            if hashlib.sha256((Path(job['task']['workspace'])/name).read_bytes()).hexdigest()!=h:raise ValueError('Frozen source changed')
        for i,a in enumerate(attempts):
            if a.get('stage')=='ultra' and any(p.get('outcome')=='verified' for p in attempts[:i]):unnecessary.append(job['case'])
            if a.get('model_calls') not in (0,1):raise ValueError('Unexpected retry count')
            v=a.get('verification') or {}
            if v.get('passed_runs')==v.get('total_runs')==100 and v.get('semantic_passed') and v.get('tsan_passed') is False:
                gates.append({'case':job['case'],'arm':job['arm'],'stage':a['stage'],'rejected_by':'TSan after stress and semantics passed'})
            if a.get('outcome')=='verified':
                raw=json.loads((out/(job['case']+'--'+job['arm'])/a['stage']/'verification.json').read_text())
                require_verified(raw,job['task']['verification_config'])
        if job['arm']=='fast':
            if any(a.get('stage')=='super' and a.get('outcome')=='verified' for a in attempts):stopped.append(job['case'])
            if any(a.get('stage')=='ultra' and a.get('outcome')=='verified' for a in attempts):recovered.append(job['case'])
            if r.get('status')!='verified':unresolved.append(job['case'])
            u=rows[job['case'],'ultra_only']
            if r.get('cost_usd') is not None and u.get('cost_usd') is not None:
                if r['cost_usd']<u['cost_usd']:better_cost.append(job['case'])
                if r['cost_usd']>u['cost_usd']:worse_cost.append(job['case'])
    if paid_calls>protocol['max_new_paid_calls'] or known_cost>protocol['maximum_incremental_usd']+1e-9:
        raise ValueError('Protocol budget exceeded')
    totals=view['aggregates'];adaptive=totals['fast'];super_=totals['super_only'];ultra=totals['ultra_only']
    claims=[]
    if adaptive['verified']>super_['verified']:
        claims.append(f"On this suite adaptive verified {adaptive['verified']}/8 versus Super-only {super_['verified']}/8.")
    if adaptive['verified']>ultra['verified']:
        claims.append(f"On this suite adaptive verified {adaptive['verified']}/8 versus Ultra-only {ultra['verified']}/8.")
    if adaptive['cost_usd'] is not None and ultra['cost_usd'] is not None:
        if adaptive['cost_usd']<ultra['cost_usd'] and adaptive['verified']>=ultra['verified']:
            claims.append('Adaptive used less measured inference spend than Ultra-only without reducing the observed verified count.')
        elif adaptive['cost_usd']>ultra['cost_usd']:
            claims.append('Adaptive cost more than Ultra-only in this run; a cost-saving claim is unsupported.')
    economics={arm:{'tokens_per_verified':v['tokens_per_verified'],
        'cost_per_verified_usd':v['cost_usd']/v['verified'] if v['verified'] and v['cost_usd'] is not None else None,
        'calls_per_verified':v['calls']/v['verified'] if v['verified'] else None} for arm,v in totals.items()}
    audit={'jobs':len(rows),'paid_calls':paid_calls,'known_cost_usd':known_cost,'unknown_cost_exists':unknown_cost,
           'adaptive_stopped_at_super':stopped,'adaptive_recovered_by_ultra':recovered,
           'adaptive_unresolved':unresolved,'unnecessary_ultra_calls':unnecessary,
           'adaptive_cheaper_than_ultra_cases':better_cost,'adaptive_more_expensive_than_ultra_cases':worse_cost,
           'stress_and_semantics_pass_but_tsan_fail':gates,'verified_outputs_audited':True,
           'economics':economics,'supported_suite_claims':claims,
           'conclusion_policy':'Describe suite tradeoffs. Do not claim adaptive is universally cheaper, faster or more accurate.'}
    (out/'audit.json').write_text(json.dumps(audit,indent=2))
    with (out/'REPORT.md').open('a',encoding='utf-8') as stream:
        stream.write('\n\n## Independent outcome audit\n\n')
        stream.write(f"Adaptive stopped at Super on {len(stopped)} cases; Ultra recovered {len(recovered)}; {len(unresolved)} remained unresolved. Ultra calls after a verified Super: {len(unnecessary)}.\n\n")
        stream.write(f"Adaptive was cheaper than Ultra-only on {len(better_cost)} cases and more expensive on {len(worse_cost)}. Compare the verified outcomes alongside these costs.\n\n")
        stream.write(f"The verifier rejected {len(gates)} candidate attempts that passed stress and semantics but failed TSan. These are not accepted repairs.\n\n")
        stream.write('This is a single-pass synthetic-suite comparison. No confidence claim or production generalization follows from these counts.\n')
        stream.write('\n## Claims supported by this run\n\n'+'\n'.join('- '+c for c in claims)+'\n')
    print(json.dumps(audit,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('protocol',type=Path);main(p.parse_args().protocol)
