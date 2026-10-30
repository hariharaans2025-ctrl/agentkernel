# Adaptive v4: implementation record (30 October 2026)

> **Update, later on 30 October:** v4 has now run live in Nebius Sandbox with real Token Factory calls. The live results are in [ADAPTIVE_V4_LIVE.md](ADAPTIVE_V4_LIVE.md); the architecture decision is in [docs/adr/0001-adaptive-routing-architecture.md](docs/adr/0001-adaptive-routing-architecture.md). The status paragraph below describes the morning's offline-only state.
>
> Changes since that offline record:
>
> | Change | What changed and why |
> | --- | --- |
> | router-2 | `calibrate()` now counts `accepted_false_fix`. Latency comes from inference plus pooled verification time; the old equal defaults made Super-first unreachable. |
> | router-3 | `with_correction()` gives a single-tier route one evidence-directed correction at that tier. |
> | contract `v4_1` | A no-op block next to a real fix is dropped and recorded instead of voiding the reply. This was found live on capacity_3. |
> | Input cap | Raised from 12,000 to 36,000, with a per-job total of 48,000, so the prompt plus a full evidence packet fits. Found live on aggregate_3. A correction refused before any call is now `not_started`/`rejected`, never `unknown`. |
> | Progress | Stage callbacks added for the website. |
> | Website | The Sites agent offers **Adaptive v4 \| Evidence-routed Nemotron Ultra**: 2 calls max, reviewed bound $0.121. Console copy updated. |
> | Runner | `scripts/live_adaptive_v4.py` has three commands: `smoke`, `prepare` and `execute`. `smoke` runs the real sandbox with scripted replies and a scratch ledger. `prepare` and `execute` are the frozen paid run, enforcing ≤ 16 calls / $0.50. |

Status (end of 30 October): **implemented, fixed and run live.** Router `adaptive-v4-router-3`, contract `agentkernel_line_blocks_v4_1`, input cap 36,000. Live results are in [ADAPTIVE_V4_LIVE.md](ADAPTIVE_V4_LIVE.md):

- **Frozen pilot:** 5/8, vs Ultra-only 6/8. audit_3 was newly solved. Two cases were lost to the parser and input-bound defects, since fixed.
- **Post-fix re-check:** 2/2. aggregate_3 was recovered by the evidence-directed correction.
- **Dashboard:** audit_3 verified.

The frozen v3 results (Ultra-only 6/8, Super→Ultra 6/8, Super-only 0/8, at `reports/cloud-comparison/20261029T170003Z`) are unchanged and remain the baseline. The sections below record the morning's design; the update table above lists every later change.

## Diagnosis (from the preserved records; development-seen, not evaluation)

Evidence: `reports/adaptive-v4/20261030T115040Z/diagnosis.json`, `SCORECARD.md`.

- 15 of 16 Super attempts rewrote the unchanged `#include "state.h"` line.
- 5 replies are exactly `["#include "]` with `finish_reason=stop` after 39 tokens. Under strict `json_schema` constrained decoding, the raw `"` closes the JSON string and the grammar forces closure. This is a **response-contract defect**, not evidence of a lack of repair ability.
- 3 replies replaced the include with `'state.h'` (compile failure). Others replaced it with `<pthread.h>`/`<stdatomic.h>` and expanded one line into two, which shifted later line numbers. This explains every `line_range_out_of_bounds` / `line_ranges_overlap` result.
- `predicate_3`'s `printf("…")` broke the same way.
- **audit_3**: Ultra removed the mutex entirely, so the race on `committed`/`bytes` remained. TSan stacks are unsymbolized (`<null>`, "invalid path to external symbolizer").
- **rendezvous_3**: Ultra kept `checkpoint()` (two barrier waits in a protected header helper) inside the mutex, giving 100/100 TIMEOUT.
- The v3 fallback received only outcome summaries. It never saw the failed candidate or the TSan stacks.

## Changed / added files (all new; no existing file modified)

| File | Behavior |
| --- | --- |
| `src/agentkernel/repository/adaptive_v4_core.py` | Pure layer: `agentkernel_line_blocks_v4` contract, failure taxonomy, lossless evidence packets, deterministic router `adaptive-v4-router-1`, development calibration aggregation. |
| `src/agentkernel/repository/adaptive_v4.py` | Opt-in route `agentkernel/adaptive-v4` (`AdaptiveV4.run`, arms `super_only`/`ultra_only`/`fixed_fallback`/`v4`). |
| `scripts/run_adaptive_v4.py` | `diagnose` (offline) and `prepare --query-live` (frozen protocol, hashes, live IDs/prices, bound check, scorecard). Starts no inference. |
| `tests/test_adaptive_v4.py` | 24 offline tests. |
| `reports/adaptive-v4/20261030T115040Z/` | `diagnosis.json`, `protocol.json`, `hashes.json`, `SCORECARD.md`. |

### 1. Cheaper-tier interface

- Replies use plain-text blocks: `@@ REPLACE <file> <a>-<b>` / verbatim lines / `@@ END`. There is no `response_format` grammar and no JSON escaping, so quotes and backslashes in C reach the parser byte-exact.
- Canonical identity is the sha256 of the exact source bytes. Parsing rejects any context whose identity changed.
- Numbering is deterministic and one-based. File line endings, including CRLF, are preserved, and whitespace is never stripped.
- **Rejected, never repaired:**
  - text outside blocks
  - unterminated or nested blocks (classed as truncation/envelope)
  - non-editable files
  - reversed or out-of-bounds ranges
  - copied `000001|` prefixes
  - overlaps
  - no-op blocks
  - a changed `sched_yield` count
  - **ambiguous blocks that re-emit an unchanged neighbouring line** (the shifted-numbering signature)
- The only normalization is removing a single fence that wraps the whole reply. It is recorded in `parse_notes`.
- The prompt says that uncovered lines stay unchanged and not to rewrite includes. It also says to read protected helpers that wait or lock (the rendezvous lesson).
- The example rule is a single fixed synthetic snippet, never retrieved from any task.
- Taxonomy (`classify_attempt`): envelope, schema, line_mapping, truncation, compilation, original_tests, stress, semantics, tsan, unknown. All failed gates are listed for each attempt.

### 2. Deterministic router

- Features: source/header bytes, editable files/lines, primitive counts (mutex, cond, barrier, rwlock, semaphore, atomic, join), distinct mutexes, blocking helper in a protected header, and baseline stress/TSan fingerprints.
- Buckets: `protected_blocking_helper`, `multi_lock`, `hang`, `tsan_only`, `single_lock_invariant`.
- Super is skipped, with a logged reason, for any of: context capacity, `protocol_capability_not_demonstrated` (development valid-output rate < 0.75 or n < 2), `sparse_calibration_for_bucket`, `false_fix_history`, or `expected_cost_or_latency_not_lower`.
- Expected cost uses a conservative lower estimate p = k/(n+2) for Super verifying, so the router picks Ultra directly when that is cheaper.
- There is no confidence-based escalation and no Nano call. Feature values, policy version, skip reasons, expected values and decision overhead go to `route.json`.
- **With no v4 development calibration yet, v4 routes every case to Ultra directly.** That is the honest consequence of 0/8 demonstrated Super capability.

### 3. Evidence-directed correction

- After a candidate actually fails verification, the fallback receives: the original task, sources and interface; the failed candidate files; the canonical patch; the build result; original-test outputs; stress counts and fingerprint; semantic requirement results; TSan conflict reports; and the verifier regressions.
- Repeated runs are deduplicated through an explicit reference map. Each run stores its template fingerprint plus the exact variable values, and `reconstruct()` reproduces its stderr byte for byte (tested). Distinct reader/writer conflict reports are never merged away.
- An over-budget packet raises `evidence_budget_exceeded` instead of truncating.
- Format recovery (a reply rejected before execution) and verifier recovery have separate caps (1 each, 2 calls per job maximum).
- The route stops without replay on any of: unknown usage, transport/provider error, verifier infrastructure failure, or TSan unavailable.

### 4. Transport

- Measured phases: queue, sandbox_create, upload, baseline build/stress/TSan, inference, apply, build, stress, TSan build, TSan, original tests + semantics (derived), and e2e.
- Candidates verify on an isolated branch of the immutable post-upload, pre-build snapshot. Contree `run`/`apply_files` return new image objects, so the parent is never mutated, and verification is sequential.
- This saves one sandbox creation and upload per candidate. The saving is **not measured**.
- The 40-run journaled batches, 100 stress runs, 3 TSan runs, schedules and oracles are unchanged.

### 5. Integration

- The CLI and module are opt-in. They reuse `reports/product-v3/budget.json` (reserve → settle/unknown, no replay) and the unchanged `ConcurrencyVerifier`.
- v2 (Sites agent) and v3 (`ProductRepair`) code is untouched.
- **Done later on 30 October:**
  - the local Model Lab option **Adaptive v4**, on product-v1 cases only, with the TSan image pinned
  - the Sites agent option, which reuses the existing single-use review and budget checks
- **Not done:** the hosted console wording is built but not redeployed, and the ChatGPT plugin has no v4-specific tool.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests\test_adaptive_v4.py   # 24 passed
.\.venv\Scripts\python.exe scripts\run_adaptive_v4.py diagnose
.\.venv\Scripts\python.exe scripts\run_adaptive_v4.py prepare --query-live            # catalog GET only, no inference
```

Regression check: `pytest --basetemp=work/pytest-v4-tmp` over the v4, line-repair, remote-repair, product budget/campaign/profile and candidate-reuse suites gave 111 passed. `--basetemp` is needed because the default `%TEMP%\pytest-of-…` directory belongs to another Windows account.

The tests cover:
- reproduction of the saved quote-closure and out-of-bounds responses
- gate classification of the saved audit/rendezvous rejections
- raw-quote and CRLF preservation
- 9 rejection cases
- identity change and fence handling
- prompt exclusion of references and grammar
- lossless dedupe with reader/writer retention
- evidence fields and the refusal to truncate
- router conservatism, calibrated Super-first, context skip and buckets
- v3 identifiers unchanged

## Paid-run protocol and blockers

`protocol.json` freezes the prompt hash, example rule, contract, router version, live model IDs/prices (unchanged since the v3 run), caps, attempts, image, verifier counts and implementation hashes. The ledger shows $0.2234 committed, 0 unknown calls, against a conservative ceiling of $10.

| Stage | Contents | Paid calls max | Reserved bound | Status |
| --- | --- | --- | --- | --- |
| A, development pilot | Super with v3 JSON contract vs v4 block contract on `ledger_2`, `snapshot_2`, `capacity_2`, `predicate_2`, plus at most 4 Ultra evidence-directed corrections | 12 | $0.2046 | Within the delegated $0.50 / 16-call cap. Expected actual spend is about $0.01. |
| B, held-out four-arm comparison | 5 new program families, rotated arm order, concurrency 1 | 30 | $0.658 | **Exceeds the delegated cap; needs an explicit expanded limit.** |

Stage A, the Super contract comparison, was **not executed**. The delegated budget went instead to a frozen live v4 pilot on all eight product-v1 test cases (10 calls), a post-fix re-check (3 calls) and two dashboard runs (2 calls). That is 15 of 16 calls and $0.0295 in total, with no unknown calls. `AdaptiveV4.run` has run end to end against the real Nebius Sandbox: a smoke test with scripted replies, then the live runs.

Stage B's held-out families are named in the protocol only. Their fixtures and private reference validation are not built yet.

## Limitations

- **Development-seen only.** The live results come from eight development-seen programs, with no unseen or statistical claim. The cost target (−25% spend) was not met: v4 cost slightly more than Ultra-only in the frozen pilot. The latency target is unproven.
- **Super-first is uncalibrated,** so the cheaper tier is still never tried first.
- **No blind-retry control was run,** so the aggregate_3 recovery can't be attributed to the evidence rather than to the extra call alone.
- TSan phase attribution in `TimedCampaign` uses a heuristic on the task. The verification-phase split for tests + semantics is derived by subtraction.
- TSan symbolization is still missing in the image, so stacks carry no function names. The verifier was not altered.
- Router calibration from 4 development programs would remain sparse. No learned-accuracy claim follows from it.
