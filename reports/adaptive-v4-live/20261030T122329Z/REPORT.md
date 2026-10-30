# Adaptive v4 live pilot

Router `adaptive-v4-router-3`, contract `agentkernel_line_blocks_v4_1`. Real Nebius Sandbox and Token Factory. Complete: True.

Cases are development-seen; v4 prompt includes lessons from their v3 failures. Not unseen evaluation.

## Per case

| Case | v4 | v4 attempts | v3 ultra_only | v3 fast (Super→Ultra) | v3 super_only |
| --- | --- | --- | --- | --- | --- |
| capacity_3 | verified | ultra:verified | verified | verified | rejected |
| aggregate_3 | verified | ultra:rejected → ultra:verified | verified | verified | rejected |

## Aggregates over the same cases

| Route | Jobs | Verified | Calls | Tokens | USD | USD per verified | Median e2e (s) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| v4 (live) | 2 | 2 | 3 | 8730 | 0.009364 | 0.004682 | 50.10241759999985 |
| ultra_only | 2 | 2 | 2 | 3202 | 0.003896 | 0.001948 | 38.63217685002019 |
| fast | 2 | 2 | 4 | 6084 | 0.004857800000000001 | 0.0024289000000000003 | 44.669909649994224 |
| super_only | 2 | 0 | 2 | 3102 | 0.0010782 | None | 25.445669349981472 |

v3 rows are the frozen 29 Oct run (same model IDs, prices, caps, cases), not interleaved with this run. Network and service conditions differ between dates. Single pass, eight development-seen cases: no statistical or unseen-generalization claim. v4 may use a second Ultra call only after a real rejection; a gain over ultra_only can come from that extra call as well as from the evidence it carries — no blind-retry control was affordable within the 16-call cap.