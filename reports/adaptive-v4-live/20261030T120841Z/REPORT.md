# Adaptive v4 live pilot

Router `adaptive-v4-router-3`, contract `agentkernel_line_blocks_v4`. Real Nebius Sandbox and Token Factory. Complete: True.

Cases are development-seen; v4 prompt includes lessons from their v3 failures. Not unseen evaluation.

## Per case

| Case | v4 | v4 attempts | v3 ultra_only | v3 fast (Super→Ultra) | v3 super_only |
| --- | --- | --- | --- | --- | --- |
| ledger_3 | verified | ultra:verified | verified | verified | rejected |
| snapshot_3 | verified | ultra:verified | verified | verified | rejected |
| capacity_3 | rejected | ultra:invalid_output → ultra:invalid_output | verified | verified | rejected |
| rendezvous_3 | rejected | ultra:rejected → ultra:rejected | rejected | rejected | rejected |
| lock_order_3 | verified | ultra:verified | verified | verified | rejected |
| predicate_3 | verified | ultra:verified | verified | verified | rejected |
| audit_3 | verified | ultra:verified | rejected | rejected | rejected |
| aggregate_3 | unknown | ultra:rejected → ultra:unknown | verified | verified | rejected |

## Aggregates over the same cases

| Route | Jobs | Verified | Calls | Tokens | USD | USD per verified | Median e2e (s) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| v4 (live) | 8 | 5 | 10 | 14826 | 0.017288 | 0.0034576000000000003 | 31.86186835000012 |
| ultra_only | 8 | 6 | 8 | 13055 | 0.015955 | 0.002659166666666667 | 40.781171000009635 |
| fast | 8 | 6 | 16 | 25743 | 0.020602 | 0.0034336666666666665 | 43.553339799982496 |
| super_only | 8 | 0 | 8 | 12496 | 0.0043578 | None | 18.3816547000024 |

v3 rows are the frozen 29 Oct run (same model IDs, prices, caps, cases), not interleaved with this run. Network and service conditions differ between dates. Single pass, eight development-seen cases: no statistical or unseen-generalization claim. v4 may use a second Ultra call only after a real rejection; a gain over ultra_only can come from that extra call as well as from the evidence it carries — no blind-retry control was affordable within the 16-call cap.