# Zero-shot versus few-shot pilot

Completed four single-attempt calls to `Qwen/Qwen3-30B-A3B-Instruct-2507`. No training, retries, correction calls, or escalation.

| Measurement | Zero-shot | Two training examples |
|---|---:|---:|
| Verified repairs | 0 | 2 |
| False fixes (verifier definition) | 2 | 0 |
| Total tokens (including failures) | 3,968 | 13,434 |
| Tokens per verified repair | N/A (no verified repairs) | 6,717 |
| Total inference latency | 36.80 s | 25.57 s |
| Total verification latency | 254.13 s | 56.58 s |
| Total end-to-end latency | 303.11 s | 98.57 s |

Both arms used temperature 0, a 2,048-token output cap, one attempt per program, identical task messages, unchanged protected support files, and the same mandatory verifier: compilation, 100 stress executions, original tests, semantic oracle, and three required TSan executions. A compilation failure stops verification before execution.

| Case | Outcome | Stress | Semantics | TSan | Tokens | Inference / verification / end-to-end |
|---|---|---|---|---|---:|---|
| zero_shot-rwlock_mode | rejected | Not run: compile failure | Not run | Not run | 1,906 | 9.66 s / 1.44 s / 17.51 s |
| zero_shot-wake_all | rejected | 0/100 | FAIL | 3/3 TIMEOUT | 2,062 | 27.13 s / 252.69 s / 285.60 s |
| few_shot-rwlock_mode | verified | 100/100 | PASS | 3/3 PASS | 5,912 | 17.88 s / 28.60 s / 57.63 s |
| few_shot-wake_all | verified | 100/100 | PASS | 3/3 PASS | 7,522 | 7.68 s / 27.98 s / 40.95 s |

The zero-shot rwlock repair failed compilation (`false` without `<stdbool.h>`). The zero-shot wake-up repair timed out in all 100 stress executions; semantic/original tests and TSan did not pass. TSan timeouts are not evidence of a detected data race. The frozen verifier labels applied candidates rejected by verification as false fixes, including compilation failure; neither was accepted as safe.

Both few-shot repairs passed the full verifier. Training examples were selected before outcomes: race_002/race_003 for shared-state protection, deadlock_004/job_queue for liveness. There was no direct condition-variable example in this training subset.

Exact payload audit confirmed that inserted demonstrations are exclusively the selected training messages. Held-out reference patches and repaired sources were never read into inference payloads. Their prior passing verification only establishes solvability and is excluded from all model-success counts. Original datasets, sources, implementation, and previous evidence passed the frozen hash check.

Inference cost calculated from actual provider token usage and the frozen live catalog: **$0.0021188**. Conservative pre-run bound: **$0.1073152**. Sandbox incremental cost: $0 based on the user confirmation of free beta access. These are calculated usage charges, not an invoice. No training cost was incurred.

On these two held-out programs, adding examples changed verified repairs from 0/2 to 2/2, while consuming 3.39 times as many total tokens. The shorter measured end-to-end time mainly reflects avoiding failed timeout-heavy verification. Inference timing is a single observation per case and arm, performed in fixed order, and can reflect provider/network variability. This tiny pilot does not establish statistical superiority or generalization to real repositories.

The result supports further prompting evaluation before paying for training. These two programs have now been evaluated; any tuning based on these results requires a fresh untouched evaluation set. The mandatory verifier remains the acceptance gate.

Evidence: [frozen plan](plan.json), [aggregate results](results.json), [integrity check](integrity.json), per-job responses, patches, verification records, and raw campaign batches in this directory.
