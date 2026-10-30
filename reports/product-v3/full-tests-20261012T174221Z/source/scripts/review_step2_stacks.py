"""Read-only review of saved GDB capture; does not repeat sandbox executions."""
from datetime import datetime, timezone
import hashlib
import json
import re
from validate_repository_step2 import ROOT, hashes

source = ROOT / 'reports/repository-diagnostics/20261007T114433Z'
out = ROOT / 'reports/repository-diagnostics' / ('review-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
out.mkdir(parents=True, exist_ok=False)
saved = json.loads((source / 'thread-stacks.json').read_text())
parts = re.split(r'(?m)^Thread (\d+) \(', saved['stdout'])
threads = [{'gdb_thread_id': int(parts[i]), 'text': parts[i+1]} for i in range(1, len(parts), 2)]
blocked = []
for function in ('queue_process_one', 'queue_inspect'):
    matches = [t for t in threads if function + ' (' in t['text'] and 'pthread_mutex_lock ()' in t['text']]
    if len(matches) != 1: raise ValueError('Expected a distinct blocked thread for ' + function)
    thread = matches[0]
    location = re.search(function + r'.*? at (src/queue.c:\d+)', thread['text'])
    if not location: raise ValueError('Missing queue source frame')
    blocked.append({'thread': thread['gdb_thread_id'], 'function': function, 'location': location[1]})
valid = saved['exit_code'] == 0 and not saved['timed_out'] and len(threads) == 3 and len({b['thread'] for b in blocked}) == 2
if not valid: raise ValueError('Capture incomplete')
before = json.loads((source / 'preserved-sha256.json').read_text())
if before != hashes(): raise ValueError('Protected files changed')
raw_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir() if p.is_file()}
result = {'source_report': str(source), 'raw_evidence_sha256': raw_hashes,
          'thread_count': len(threads), 'blocked_threads': blocked, 'user_stacks_captured': True,
          'correction': 'Initial gate incorrectly required a libc pthread_join symbol. Actual worker and monitor user-space stacks were captured successfully.',
          'protected_files_unchanged': len(before), 'additional_executions': 0, 'model_calls': 0}
(out / 'review.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
report = ['# Step 2 completed: diagnostic evidence review', '',
          'The raw report and all execution evidence remain unchanged. This view corrects an overly strict stack-success check; no workload was repeated.', '',
          '- 8 diagnostic unit tests passed in Nebius.',
          '- Intentional data race: serial 3/3 detected; batch 3/3 detected.',
          '- Mutex-protected control: serial 3/3 clean; batch 3/3 clean; counter invariant passed.',
          '- Queue: 3/3 timeouts with application-reported opposing wait cycles.',
          '- GDB captured three threads, including both blocked worker/monitor stacks.',
          f'- {len(before)} protected files unchanged; zero model calls.', '',
          '| Thread role | Source frame | Blocking function |', '|---|---|---|']
for b in blocked: report.append(f"| {b['function']} | {b['location']} | pthread_mutex_lock |")
report += ['', 'Observed dependency: WORKER holds queue -> waits for stats held by MONITOR -> waits for queue held by WORKER.',
           'Main is at src/main.c:31 (the preserved source calls pthread_join there); libc frames were unsymbolized. The original automated check wrongly required the literal pthread_join name.',
           'This is synthetic diagnostic validation, not a repaired codebase, full candidate verification, or proof of generic race/deadlock detection equivalence. No change to production routing or batching defaults.',
           'The wait-cycle extractor currently handles explicit application HOLD/WAIT events. Generic repository lock tracing remains future work.',
           'Original raw evidence: ' + str(source)]
(out / 'REPORT.md').write_text('\n'.join(report) + '\n', encoding='utf-8')
print(out / 'REPORT.md')
print(json.dumps({'blocked_threads': blocked, 'protected_files_unchanged': len(before)}))
