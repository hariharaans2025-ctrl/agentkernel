# Expanded concurrency validation

Manually authored synthetic controls, not model-generated repairs. Zero model calls or tokens.
Three diagnostic runs per faulty variant; three additional TSan runs for missing synchronization.

| Case | Faulty diagnostic | Fixed stress | Fixed semantics | Fixed TSan | Verified |
|---|---|---|---|---|---|
| lost_signal | timeout_unexplained, timeout_unexplained, timeout_unexplained | 100/100 | True | True | True |

Completed positive-control cases: 1/3. Protected files unchanged: True.
Semantic and original-test executions repeat the workload; they do not provide independent behavioral coverage.
Lost-signal diagnosis deliberately remains timeout_unexplained in the generic detector: a known synthetic root cause is not equivalent to runtime proof.
These controls broaden verifier coverage. They do not demonstrate improved model repair quality or real-application readiness. Frozen benchmark outcomes and production policies remain unchanged.
