# Expanded validation: combined view

Three manually authored synthetic positive controls. No model inference; these are not model repair successes.
Source run: reports\additional-concurrency-controls\20261010T094228Z. Original evidence remains unchanged.
The interrupted missing-sync semantic attempt remains UNKNOWN. Its 100 completed stress runs were reused unchanged; build/original-test/semantic checks ran afresh and 3 TSan checks ran for the first time.

| Case | Verified | Stress | Semantics | TSan |
|---|---|---|---|---|
| lost_signal | True | 100/100 | True | True |
| missing_sync | True | 100/100 | True | True |
| account_inversion | True | 100/100 | True | True |

Protected files unchanged: True.
Original tests and semantic runs repeat the workload, not independent coverage. No general safety, model quality or statistical superiority claim follows.
