# Adaptive v4 live results (30 October 2026)

All model calls are fresh NVIDIA Nemotron calls through Nebius Token Factory. All compilation and execution ran in Nebius Sandbox (`agentkernel-clang:20261003122908`). Every accepted repair passed every check below:

- a fresh build
- the original tests
- 100/100 stress runs
- the protected semantic oracle
- 3/3 ThreadSanitizer runs
- preserved scheduling hooks

No cache, no reference repairs in prompts, no retries, and no automatic replay. The spending ledger shows 0 unknown calls.

**Scope.** These eight product-v1 test cases are **development-seen**. The v4 diagnosis and prompt were written after their v3 failures. Nothing here is an unseen benchmark or a statistical claim.

## What v4 is

1. A deterministic router. With no development calibration yet, it sends every case to Nemotron Ultra, which is the best measured route.
2. A plain-text line-block reply contract with no JSON grammar. This removes the quote-closure defect behind Super's 0/8 in the v3 run.
3. **One evidence-directed correction.** Only if execution rejects the first candidate, Ultra receives the failed candidate, its canonical patch and the verifier evidence (stress, semantics, TSan conflicts) in a lossless packet.

## 1. Frozen pilot: all 8 test cases, router-3 / contract v4

Evidence: `reports/adaptive-v4-live/20261030T120841Z/`

| Case | v4 | v3 Ultra-only | v3 Super→Ultra |
| --- | --- | --- | --- |
| ledger_3 | verified (1 call) | verified | verified |
| snapshot_3 | verified (1) | verified | verified |
| capacity_3 | rejected: **v4 parser defect** | verified | verified |
| rendezvous_3 | rejected (2 calls; genuine repair failure) | rejected | rejected |
| lock_order_3 | verified (1) | verified | verified |
| predicate_3 | verified (1) | verified | verified |
| audit_3 | **verified (1)**; v3 never solved it | rejected | rejected |
| aggregate_3 | rejected: **v4 input-bound defect** | verified | verified |

| Route | Verified | Calls | Tokens | USD | Median e2e |
| --- | --- | --- | --- | --- | --- |
| **v4 (live, frozen)** | **5/8** | 10 | 14,826 | $0.0173 | 31.9 s |
| v3 Ultra-only (29 Oct) | 6/8 | 8 | 13,055 | $0.0160 | 40.8 s |
| v3 Super→Ultra (29 Oct) | 6/8 | 16 | 25,743 | $0.0206 | 43.6 s |

As frozen, v4 **lost** to Ultra-only by one case. Both lost cases were my integration defects, not model failures:

- **capacity_3.** Ultra's reply fixed the missing unlock but also restated an unchanged file, and the v4 parser voided the whole reply.
- **aggregate_3.** The correction prompt (source + 10,975-byte evidence packet) exceeded a 12,000-byte input bound. It was refused before any call.

## 2. Post-fix regression check: contract v4_1, 36k input cap

Evidence: `reports/adaptive-v4-live/20261030T122329Z/`

These two cases were **selected because the defects hit them**. This check is never merged into the score above.

| Case | Result |
| --- | --- |
| capacity_3 | verified on the first call. Ultra's reply had no no-op block this time, so the parser fix was not exercised live; it is covered by an offline test on the saved reply. |
| aggregate_3 | **verified by the evidence-directed correction.** The first Ultra candidate passed 92/100 stress runs and failed TSan, so it was rejected. The second call received that evidence and passed 100/100 stress and 3/3 TSan. |

3 calls, 8,730 tokens, $0.0094.

## 3. Local dashboard run (Model Lab, `.env` keys)

This run was launched from the Model Lab UI (`Start-Dashboard.ps1` → **Adaptive v4** on **audit_3**). Evidence: `reports/dashboard/8792a943-652e-4ed8-bf58-636cea59d45f.json` and `…-v4/`.

**Result: verified on the first Ultra call.**

| Check | Result |
| --- | --- |
| Build | passed |
| Original tests | passed |
| Stress runs | 100/100 |
| Semantic oracle | passed |
| ThreadSanitizer | 3/3 |
| Scheduling hooks | preserved |

Usage: 1,237 input / 58 output tokens, 1.41 s inference, 40.8 s end to end, $0.001411.

An earlier dashboard attempt (`04920635-…`) passed the build, tests, 100/100 stress and semantics, but stopped as **unknown**. The dashboard had not pinned the TSan-capable clang image, and v4 refuses to accept a candidate without its required TSan runs. The image is now pinned for the v4 route, and that earlier run is kept as recorded, not counted as verified.

## Supported and unsupported claims

**Supported:**

- The v4 contract and prompt changes let Nemotron Ultra repair audit_3, which no v3 route solved.
- The evidence-directed correction recovered a candidate that execution had rejected (aggregate_3), live.
- After the two integration fixes, v4 verified every case where Ultra-only verified, plus audit_3. That is 7 of the 8 cases across the frozen pilot and the post-fix check, which are separate runs and not one comparison.

**Unsupported:**

- Any statistical or unseen-generalization superiority.
- Any cost claim. v4 spent slightly more than Ultra-only in the frozen pilot.
- rendezvous_3 remains unsolved by every route.

## Spend

The delegated cap was 16 paid calls / $0.50.

| Run | Calls | Spend |
| --- | --- | --- |
| Frozen pilot | 10 | $0.0173 |
| Post-fix check | 3 | $0.0094 |
| Dashboard runs (2, one stopped as unknown on TSan) | 2 | $0.0028 |
| **Total** | **15 of 16** | **$0.0295 of $0.50** |

The spending ledger shows 0 unknown paid calls.

## Reproduce

```powershell
.\.venv\Scripts\python.exe scripts\live_adaptive_v4.py smoke --case audit_3   # real sandbox, scripted replies, 0 paid calls
.\.venv\Scripts\python.exe scripts\live_adaptive_v4.py prepare                # freeze; 0 paid calls
.\.venv\Scripts\python.exe scripts\live_adaptive_v4.py execute <protocol.json>  # paid, sequential, never replays
.\Start-Dashboard.ps1   # Model Lab: choose a product-v1 case + "Adaptive v4"
```
