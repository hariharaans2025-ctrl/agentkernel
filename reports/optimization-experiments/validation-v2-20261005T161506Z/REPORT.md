# Optimization validation v2

Saved-candidate replay on Nebius Sandbox. Model calls: 0. No production changes.
Prior source, fixtures, benchmark and experiment evidence unchanged: True.
Completed arms: 6/6. Interrupted: False.

| Candidate | Method | Verified | Stress passes | Deadlocks | Semantic pass | TSan pass | Seconds |
|---|---|---:|---:|---:|---|---|---:|
| race_002 | batch | True | 100/100 | 0 | True | True | 27.144 |
| race_002 | serial | True | 100/100 | 0 | True | True | 184.808 |
| deadlock_001 | serial | False | 99/100 | 1 | True | not configured | 173.879 |
| deadlock_001 | batch | False | 98/100 | 2 | True | not configured | 24.056 |
| deadlock_002 | batch | False | 0/100 | 100 | False | not configured | 240.259 |
| deadlock_002 | serial | False | 0/100 | 100 | False | not configured | 397.088 |

## Reversed timing

Batch-first pair: serial 184.808s, batch 27.144s; 85.3% less time with batching.
Prior serial-first pair (read-only reference): C:\Users\HARI HARAAN\Documents\Codex\2026-09-14\files-pasted-by-the-user-you\outputs\agentkernel\reports\optimization-experiments\20261005T160434Z

## Detection gates

deadlock_001: both methods rejected the saved faulty candidate = True.
deadlock_002: both methods rejected the saved faulty candidate = True.

Observed replay gates passed: True.
This is not a production approval or proof of equivalent bug-detection sensitivity.

Only one successful candidate has two opposite-order pairs across two sessions. Negative candidates have one pair each; failure frequencies may differ because concurrency is nondeterministic.
The intermittent deadlock candidate previously passed 96/100; a clean rerun would not establish that it is correct. Any missed rejection blocks recommending production rollout.
All arms retain 100 stress runs and the original semantic oracle. race_002 additionally retains 3 required TSan runs; deadlock fixtures do not configure TSan.
No known TSan-failing candidate is included, so race-detection sensitivity remains unvalidated.
Batch shares a remote instance per 10 independent processes. Service load, scheduling and instance lifetime remain confounders.
No token savings or model quality measurements are produced. The interrupted frozen Super race_005 job is untouched.
