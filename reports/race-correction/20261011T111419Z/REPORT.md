# One verifier-triggered correction: pair_snapshot

The single authorized correction did not recover the failed few-shot repair. The verifier rejected the correction. No further model call or retry was made.

| Measurement | Frozen first attempt | Separate correction |
|---|---:|---:|
| Outcome | REJECTED | REJECTED |
| Compilation | PASS | PASS |
| Original tests | FAIL | FAIL |
| Stress passes | 0/100 | 0/100 |
| Semantic oracle | FAIL | FAIL |
| TSan | 3 detected races | 3 detected races |
| Tokens | 5,889 | 11,923 additional |
| Inference latency | 6.72 s | 10.07 s |
| Verification latency | 27.11 s | 28.03 s |
| End-to-end latency | 39.32 s | 44.36 s |

Recovery count: 0/1. The correction is an additional false fix rejected by the verifier; it is not folded into or substituted for the frozen first attempt. Combined model usage for this case is 17,812 tokens across two calls. The active durations sum to 83.68 s, excluding preparation and intervening human time. Tokens per verified recovery are undefined because there was no recovery.

## Trigger and input

The gate requires a built failed candidate, zero recorded infrastructure failures, a sanitizer campaign with RACE_DETECTED, and raw stderr containing an actual TSan data-race warning. It does not consult confidence. Six gate/contract tests passed in Nebius Sandbox, including rejection of confidence-only input, missing raw evidence, infrastructure failures, an already verified candidate, and protected-file edits.

The frozen request includes the original task and sources, reconstructed failed candidate, original-to-failed canonical patch, protected header/oracle, compilation results, original-test failures, stress counts and representative results, semantic results, and all three recorded TSan conflicting-access stacks. It reads no reference repair or successful counterpart. The old TSan logs contain unsymbolized binary offsets. This limitation was stated explicitly; model claims mapping an address to a source variable are not verified evidence.

One structured response combines conflicting accesses, missing synchronization, the invariant to preserve, and exact edits against the failed candidate. Strict canonical patch conversion and protected-file checks precede remote execution. Both failed-to-corrected and original-to-corrected patches are saved.

## Why verification rejected it

The model described a need to protect both readers and writers, but its edits only combined the writer's updates under one lock and removed sched_yield from that function. snapshot_ok still reads shared state without locking. All 100 workload executions failed and all three TSan runs reported races. The explanation also inaccurately described the original writer's right-hand assignment as unlocked; the source had reacquired the lock. The structured explanation is an untrusted model proposal, not proof of correctness.

## Fixed budget and policy

Model: `Qwen/Qwen3-30B-A3B-Instruct-2507`. Exactly one correction call, temperature 0, 2,048 output-token cap, no separate critique call, no retries, no training, no substitution. The conservative input reservation was 262,144 tokens (the advertised context), with a total call bound of $0.0268288, below the $0.03 correction limit and within the existing $10 pilot. Actual usage was 11,522 input plus 401 output tokens; calculated inference cost was **$0.0012725**. Sandbox access is free per the user's confirmation. Cost is calculated from catalog rates and provider usage, not an invoice.

Mandatory verification used the exact unchanged configuration: compilation, original tests, 100 stress executions, semantic oracle, and three required TSan executions in Nebius Sandbox. Existing benchmark, dataset, prompt, input, first-attempt, and source hashes remained unchanged. The frozen four-case first-attempt scores remain zero-shot 2/4 and few-shot 3/4; this separate failed recovery does not alter them.

This is one retrospective recovery experiment, not evidence that the correction policy improves generalization. The next policy revision, if authorized, should be evaluated separately; this result remains immutable.

Evidence: [plan](plan.json), [request payload](payload.json), [structured correction](structured-correction.json), [verification](verification.json), [separate metrics](results.json), [integrity](integrity.json), and raw campaign files in this directory.
