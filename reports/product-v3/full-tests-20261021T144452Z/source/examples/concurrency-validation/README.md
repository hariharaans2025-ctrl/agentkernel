# Additional concurrency controls

These are new synthetic diagnostic controls, separate from the immutable original
ten-fixture benchmark. They are not real application bugs or model-generated repairs.

| Case | Fault | REPAIRED positive control | Invariant in both variants |
|---|---|---|---|
| lost_signal | Unconditional wait after the producer's signal | Check predicate in a while loop under its mutex | Consumer receives 42 |
| missing_sync | Concurrent unsynchronized increments | Protect every increment with the same mutex | Exactly 20,000 increments |
| account_inversion | Opposite account-lock ordering | Rendezvous before locks, then A before B | Both transfers execute; both balances remain 100 |

The controller compiles each faulty variant for three diagnostic executions.
The missing-sync fault additionally receives three TSan executions. Each positive
control receives a fresh build, an original test, 100 stress executions, a separately
built semantic oracle execution, and three required TSan executions. The original
test and semantic run exercise the same workload; they are not independent coverage.

All C execution is remote in Nebius Sandbox. The flag selects a manually authored
control, not a runtime repair or model success. A passing finite campaign is not a
proof of race freedom. A timeout without a supported wait cycle remains unexplained
in the generic diagnostic output, even when the synthetic fault is known by design.
