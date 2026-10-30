# Pair snapshot: verified direct repair

The source-level repair passed the mandatory verifier in Nebius Sandbox.

Both update_pair and snapshot_ok acquire the same guard mutex. The writer holds it across both field updates, including sched_yield. The reader holds it while copying both fields, including its scheduling hook, then releases it before checking the local copies. Concurrent readers therefore cannot observe an intermediate paired update.

The writer scheduling hook removed by the failed model correction was restored. The protected header, oracle, original tests, verification counts, timeouts, and sanitizer settings remain unchanged.

| Check | Result |
|---|---|
| Compilation | PASS |
| Original tests | PASS |
| Stress | 100/100 PASS |
| Semantic oracle | PASS |
| TSan | 3/3 PASS |
| Infrastructure failures | 0 |
| Verification time | 29.99 s |
| End-to-end time | 36.92 s |
| Additional model calls/tokens | 0 / 0 |
| Additional inference cost | $0 |

This is a direct assistant-authored source repair, not a recovered target-model success. The first few-shot attempt and the paid correction both remain REJECTED with their original evidence untouched. The frozen model benchmark remains zero-shot 2/4 and few-shot 3/4. Integrity checking confirmed 1397 existing files remained unchanged.

The complete corrected program and protected support files are in [repaired-project](repaired-project/solution.c); task.json records the unchanged execution contract for the exported folder. The [canonical patch](candidate.patch) applies to the failed correction candidate, which is retained in failed-candidate. [Raw verification](verification.json), [metrics](metrics.json), and campaign batches provide the execution evidence.

This verifies the configured workload; it is not a general proof of concurrency safety or evidence that the target model learned the repair. No training or additional model call was performed.
