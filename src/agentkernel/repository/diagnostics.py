"""Evidence-based diagnostic labels, separate from repair verification."""
import hashlib
import json
import re
from agentkernel.concurrency.instrumentation.sanitizer import parse_sanitizer, runtime_unavailable


def diagnose(result):
    stderr, stdout = result.get('stderr', ''), result.get('stdout', '')
    text = stderr + '\n' + stdout
    findings = [f.model_dump() for f in parse_sanitizer(text)]
    observations = sorted(set(re.findall(r'^([A-Z][A-Z0-9_]*) HOLD ([\w.-]+) WAIT ([\w.-]+)$', text, re.MULTILINE)))
    owners, waits, consistent = {}, {}, True
    for thread, held, requested in observations:
        if held in owners and owners[held] != thread: consistent = False
        if thread in waits and waits[thread] != requested: consistent = False
        owners[held], waits[thread] = thread, requested
    edges = {thread: owners[lock] for thread, lock in waits.items() if lock in owners}
    cycles = []
    if consistent:
        for origin in sorted(edges):
            seen, current = [], origin
            while current in edges and current not in seen:
                seen.append(current)
                current = edges[current]
            if current in seen:
                cycle = sorted(seen[seen.index(current):])
                if len(cycle) > 1 and cycle not in cycles: cycles.append(cycle)
    if result.get('metadata', {}).get('error') or runtime_unavailable(text):
        kind = 'infrastructure_failure'
    elif any(f['type'] == 'data_race' for f in findings):
        kind = 'data_race'
    elif result.get('timed_out'):
        kind = 'deadlock_supported_by_wait_cycle' if cycles else 'timeout_unexplained'
    elif result.get('exit_code') == 0:
        kind = 'completed_not_verified'
    else:
        kind = 'process_failure'
    normalized = re.sub(r'0x[0-9a-fA-F]+', '<address>', text)
    normalized = re.sub(r'\b(?:pid=\d+|T\d+)\b', '<runtime-id>', normalized)
    basis = {'kind': kind, 'waits': observations, 'cycles': cycles,
             'findings': [(f['type'], f['file'], f['line']) for f in findings]}
    if not findings and not observations:
        basis['message'] = normalized[:4000]
    return {'kind': kind, 'observed_waits': observations, 'thread_wait_edges': edges,
            'cycles': cycles, 'observations_consistent': consistent, 'sanitizer_findings': findings,
            'fingerprint': hashlib.sha256(json.dumps(basis, sort_keys=True).encode()).hexdigest(),
            'limitation': 'Wait cycles are application-reported evidence, not a generic mutex ownership tracer. Completion is not verification.'}
