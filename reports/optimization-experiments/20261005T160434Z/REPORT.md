# Optimization experiment v1

Model calls: 0. Frozen source/evidence unchanged: True.
Evidence corpus: 125,349 -> 109,880 UTF-8 bytes (12.3% smaller).
All 10 evidence records round-trip exactly. This is not a measured token or repair-quality improvement.

| Arm | Verified | Stress passed | Semantics | TSan | Full verification seconds |
|---|---:|---:|---:|---:|---:|
| serial | True | 100/100 | True | True | 180.274 |
| batch | True | 100/100 | True | True | 28.691 |

Single saved race_002 repair, serial then batch. Order/service-load effects are uncontrolled; no suite-wide speedup or semantic equivalence claim.
Batch size 10; distinct subprocesses and unchanged seeds, run counts, timeouts, output limits, oracle and TSan requirements. Instance lifetime differs.
No production integration, prompt replacement, routing change or paid model inference. Conditional Nano routing remains deferred.
