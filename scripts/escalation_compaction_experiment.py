"""Offline comparison of escalation serialization; no inference or execution."""
from datetime import datetime, timezone
import json
from pathlib import Path

from agentkernel.core.models import AttemptRecord, TaskRequest
from agentkernel.runtime.evidence import build_escalation_task
from optimization_experiment import ROOT, summary, wire


def compact_escalation(original, history):
    # Retain the established escalation instructions and failure metadata exactly.
    legacy = build_escalation_task(original, history)
    instructions = legacy.prompt.rsplit('\nINSTRUCTION:\n', 1)[1]
    attempts = [{key: a.model_dump(mode='json')[key] for key in (
        'attempt_number', 'tier', 'provider', 'status', 'output_text',
        'verification_status', 'verification_reason', 'verification_evidence')}
        for a in history]
    legacy.prompt = ('ORIGINAL TASK\n' + original.prompt + '\nATTEMPT HISTORY (latest attempt is last; each appears once)\n'
                     + wire(attempts) + '\nINSTRUCTION:\n' + instructions)
    return legacy, attempts


def main():
    out = ROOT / 'reports/optimization-experiments' / ('escalation-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    out.mkdir(parents=True, exist_ok=False)
    stored = summary('deadlock_002')['metadata']['attempt_details']
    # The one measured adaptive escalation. Original prompts were not persisted;
    # isolate only the failure-context serialization using an identical sentinel.
    history = [AttemptRecord(input_prompt='', **stored[0])]
    original = TaskRequest(task_id='deadlock_002', task_type='debug',
                           prompt='ORIGINAL_TASK_HELD_CONSTANT', metadata={'phase': 'repair'})
    old = build_escalation_task(original, history)
    new, records = compact_escalation(original, history)
    assert new.metadata == old.metadata
    assert records[0]['verification_evidence'] == history[0].verification_evidence
    assert records[0]['output_text'] == history[0].output_text
    assert new.prompt.rsplit('\nINSTRUCTION:\n', 1)[1] == old.prompt.rsplit('\nINSTRUCTION:\n', 1)[1]
    a, b = len(old.prompt.encode('utf-8')), len(new.prompt.encode('utf-8'))
    measured = {'fixture': 'deadlock_002', 'unit': 'UTF8 bytes, NOT tokens',
                'legacy_failure_context_bytes': a, 'single_copy_failure_context_bytes': b,
                'reduction_percent': 100*(1-b/a), 'model_calls': 0,
                'evidence_preserved': True, 'instructions_preserved': True,
                'limitation': 'Original task replaced by equal sentinel in both arms; not full production prompt savings or measured model quality.'}
    (out / 'measurement.json').write_text(json.dumps(measured, indent=2), encoding='utf-8')
    (out / 'legacy.txt').write_text(old.prompt, encoding='utf-8')
    (out / 'single-copy.txt').write_text(new.prompt, encoding='utf-8')
    print(json.dumps(measured, indent=2))
    print(out)


if __name__ == '__main__':
    main()
