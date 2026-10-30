# Adaptive v4 scorecard (offline, judge-readable)

No new paid inference was run for this record. All counts below come from the preserved v3 comparison (`reports/cloud-comparison/20261029T170003Z`, 6/8 Ultra-only, 6/8 fixed fallback, 0/8 Super-only), now development-seen.

## Failure taxonomy of preserved attempts

| Stage | verified | envelope | schema | line_mapping | truncation | compilation | original_tests | stress | semantics | tsan | unknown |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| super | 0 | 0 | 0 | 5 | 5 | 5 | 1 | 0 | 0 | 0 | 0 |
| ultra | 12 | 0 | 0 | 0 | 0 | 0 | 3 | 1 | 0 | 0 | 0 |

Super attempts: 16; rewrote the unchanged include line: 15; quote-closure truncation: 5; `'state.h'` substitution: 3.

Interpretation: Super failures concentrate on rewriting the unchanged #include "state.h" line under a strict JSON schema; the unescaped quote closes the JSON string (contract defect), or the include is replaced and later line numbers shift. Remaining Super candidates failed real verifier gates. Unresolved Ultra cases: audit_3 removed the lock (TSan race, unsymbolized stacks); rendezvous_3 kept barrier waits inside the mutex (100/100 TIMEOUT). v3 fallback received only outcome summaries, not candidate evidence.

## Prepared, not executed

- Stage A development pilot: 12 calls max, reserved bound $0.20459519999999998, within delegated cap: True.
- Stage B held-out four-arm comparison: 30 calls max, reserved bound $0.657936: exceeds the 16-call/$0.50 delegated cap, so it needs an explicit expanded limit.

## Claims

Supported: the Super failures in the frozen run are dominated by a response-contract defect that is reproducible offline.

Unsupported (not measured): any v4 verified-count, cost or latency improvement; any statistical claim.