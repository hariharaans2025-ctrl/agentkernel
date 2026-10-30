# Partial live benchmark validation

Status: **partial**. 19/40 jobs completed; the 20th started at `super_only / race_005` and has no result. The process is no longer visible and its session is unavailable. Root cause and exact total paid requests are unknown. **19 calls are confirmed**; no automatic restart was performed.

All readiness checks passed before inference, including 255 remote tests (8 deselected), the exact three model IDs, and the prepared Clang image.

## Mode comparison

| Mode | Started/completed | Verified | False fixes | Tokens | Inference mean/median (s) | End-to-end mean/median (s) |
|---|---:|---:|---:|---:|---:|---:|
| nano_only | 10/10 | 0/10 | 0 | 87142 | 7.99/8.02 | 26.92/27.24 |
| super_only | 10/9 | 5/9 | 3 | 60942 | 5.42/4.94 | 378.38/414.20 |
| ultra_only | 0/0 | 0/0 | 0 | N/A | N/A/N/A | N/A/N/A |
| adaptive | 0/0 | 0/0 | 0 | N/A | N/A/N/A | N/A/N/A |

Rates use completed jobs; false-fix rates use applied candidates with non-infrastructure verification outcomes. Nano: 0/10 verified, false-fix rate not applicable (no candidate). Super: 5/9 completed jobs verified (55.6%), 3/8 evaluated candidates false fixes (37.5%). Missing jobs are not failures or successes.

## Fixture results

| Fixture | Nano-only | Super-only | Ultra-only | Adaptive |
|---|---|---|---|---|
| deadlock_001 | Incomplete output | False fix | Not run | Not run |
| deadlock_002 | Incomplete output | False fix | Not run | Not run |
| deadlock_003 | Incomplete output | Invalid repair output | Not run | Not run |
| deadlock_004 | Incomplete output | Verified | Not run | Not run |
| deadlock_005 | Incomplete output | False fix | Not run | Not run |
| race_001 | Incomplete output | Verified | Not run | Not run |
| race_002 | Incomplete output | Verified | Not run | Not run |
| race_003 | Incomplete output | Verified | Not run | Not run |
| race_004 | Incomplete output | Verified | Not run | Not run |
| race_005 | Incomplete output | Interrupted; unknown | Not run | Not run |

## Findings and requested questions

- All ten Nano calls exhausted the 2,048-token output cap; no partial repair was accepted. Their 87,142 recorded tokens yielded no verified repair.
- Super produced eight applied candidates and one malformed repair response. Its verified fixtures were deadlock_004 and race_001 through race_004. Each passed 100 stress runs and its semantic oracle; the four race repairs also passed their required three TSan executions.
- Super deadlock_001 passed semantics but deadlocked 4/100 times. Its deadlock_002 and deadlock_005 candidates deadlocked 100/100 times each and failed semantics. These are three false fixes; 204 post-repair deadlock observations in total.
- Two semantic checks failed (the established aggregate records them as semantic regressions); neither candidate passed stress. No observed candidate passed stress and then failed semantics.
- No observed candidate passed semantics and failed TSan. Four repaired race fixtures had measured clean TSan outcomes; untested cases remain unknown. Finite campaigns do not prove race freedom.
- No Adaptive jobs ran. Ultra-after-success, Super-to-Ultra recovery, and Ultra avoidance performance are therefore **not evaluated**. Observed Adaptive Ultra calls: zero; successful avoidance rate: unavailable.
- No statistical or adaptive-routing superiority claim is supported. The useful current demonstration is that real verification rejected plausible-looking repairs, including a 96/100 stress result with a passing oracle. The intended Super/Ultra/Adaptive research comparison remains incomplete.
- LangSmith confirmed traces for all 19 completed jobs. Tavily was unused in all completed jobs. The interrupted job has no preserved observability/grounding outcome.
- Completed jobs recorded zero transport/verification infrastructure failures. The controller interruption is separate, with unknown root cause and no retained terminal exception.
- Recorded usage: 122,955 input + 25,129 output = 148,084 tokens. The interrupted job may have additional unrecorded usage. Nano reasoning-token counts are unavailable; Super reported zero reasoning tokens. Dollar cost remains null.
- No model substitutions, retries, cap changes, output repairs, or post-run source changes were made.

## Evidence

- `final-benchmark.json`: original rows, combined aggregate, per-mode metrics, interruption and adaptive-not-run metadata.
- `final-benchmark.csv`: all 19 measured job rows.
- `final-benchmark.md`: benchmark table plus this validation report.
- `final-benchmark-jobs/<mode>/<fixture>/`: copied result and event evidence, including the empty interrupted-job event file.
- `final-live-original-checkpoint/`: untouched copies of the last runner-written JSON/CSV/Markdown.
- `live-readiness.json`: pre-inference checks; tests under `nebius-sandbox/20261004T054834Z/`.

Stopped for review. Do not replay the original live command against started evidence.
