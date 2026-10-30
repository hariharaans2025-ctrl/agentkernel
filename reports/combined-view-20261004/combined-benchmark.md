# Final live benchmark: combined report view

**Continuation completed: 20/20 jobs, 28 confirmed model calls, 207,565 tokens.** Combined evidence contains 39 completed jobs and one **INTERRUPTED / UNKNOWN** Super-only job. No paid job was replayed. Original evidence, continuation evidence, and implementation are unchanged.

This is a derived report view. Its source references and SHA-256 manifest identify the original files; neither evidence directory was merged or edited.

## Source evidence

- [Original partial JSON](../final-benchmark.json), [CSV](../final-benchmark.csv), [Markdown](../final-benchmark.md): 19 completed jobs.
- [Continuation JSON](../continuation-20261004T104857Z/final-benchmark.json), [CSV](../continuation-20261004T104857Z/final-benchmark.csv), [Markdown](../continuation-20261004T104857Z/final-benchmark.md): all 20 authorized jobs completed.
- [Readiness evidence](../continuation-20261004T104857Z/readiness.json): exact live model IDs, available sandbox/toolchain, credentials present without disclosure, and 164 files matching the original tested snapshot.
- [Combined JSON](combined-benchmark.json), [CSV](combined-benchmark.csv), [evidence hashes](evidence-sha256.json). Each measured row references its source report and per-job JSONL evidence.

The post-run audit again matched all 164 frozen source/configuration/fixture files and all 164 pre-existing report/evidence files. No prompts, caps, models, oracles, sanitizer requirements, routing, or verification counts changed.

## Mode comparison

| Mode | Completed | Verified | Accepted candidates | False fixes / evaluated | Calls (Nano/Super/Ultra) | Input tokens | Output tokens | Total tokens | Tokens / verified repair |
|---|---:|---:|---:|---:|---|---:|---:|---:|---:|
| nano_only | 10 | 0/10 (0.0%) | 0 | N/A (no candidate) | 10/0/0 | 66,662 | 20,480 | 87,142 | Not measured |
| super_only | 9 | 5/9 (55.6%) | 8 | 3/8 | 0/9/0 | 56,293 | 4,649 | 60,942 | 12,188 |
| ultra_only | 10 | 4/10 (40.0%) | 4 | 0/4 | 0/0/10 | 66,724 | 17,342 | 84,066 | 21,016 |
| adaptive | 10 | 6/10 (60.0%) | 7 | 1/7 | 10/7/1 | 110,395 | 13,104 | 123,499 | 20,583 |

Super-only has nine measured outcomes; race_005 remains interrupted and is excluded from success/failure rates. On the same nine completed Super fixtures, verified counts are Super 5/9, Ultra 4/9, Adaptive 6/9. False-fix rates are Super 37.5% (3/8), Ultra 0% (0/4), Adaptive 14.3% (1/7); Nano has no evaluated candidate. These denominators are candidates, not model calls.

## Fixture outcomes

| Fixture | Nano-only | Super-only | Ultra-only | Adaptive |
|---|---|---|---|---|
| deadlock_001 | Incomplete output | False fix; unresolved | Incomplete output | Verified at SUPER |
| deadlock_002 | Incomplete output | False fix; unresolved | Incomplete output | False fix; unresolved |
| deadlock_003 | Incomplete output | Invalid repair output | Incomplete output | Incomplete triage |
| deadlock_004 | Incomplete output | Verified at SUPER | Incomplete output | Verified at SUPER |
| deadlock_005 | Incomplete output | False fix; unresolved | Incomplete output | Verified at SUPER |
| race_001 | Incomplete output | Verified at SUPER | Verified at ULTRA | Incomplete triage |
| race_002 | Incomplete output | Verified at SUPER | Verified at ULTRA | Verified at SUPER |
| race_003 | Incomplete output | Verified at SUPER | Verified at ULTRA | Verified at SUPER |
| race_004 | Incomplete output | Verified at SUPER | Verified at ULTRA | Verified at SUPER |
| race_005 | Incomplete output | **INTERRUPTED / UNKNOWN** | Incomplete output | Incomplete triage |

All 15 verified outcomes across the combined evidence passed 100/100 stress executions and the trusted semantic oracle. The 11 verified race outcomes additionally passed all three required TSan executions each. Unknown or unexecuted sanitizer results remain null.

## Adaptive routing audit

| Measurement | Result |
|---|---|
| Solved at Super; no Ultra | 6: deadlock_001, deadlock_004, deadlock_005, race_002, race_003, race_004 |
| Escalated to Ultra | 1: deadlock_002 |
| Super failures recovered by Ultra | 0 |
| Unresolved after Ultra | 1: deadlock_002 |
| Ultra after successful Super verification | 0 |
| Any Ultra use | 1/10 jobs (10%) |
| No Ultra call | 9/10 jobs; six solved, three stopped at incomplete triage |
| Calls | Nano 10, Super 7, Ultra 1; 18 total |
| False fixes | 1 applied Super candidate |
| Semantic regressions/check failures | 1 |
| TSan failures | 0 |

The single escalation followed an applied Super candidate on deadlock_002 that failed 100/100 stress executions and its semantic oracle. Ultra returned incomplete output within its unchanged cap, so there was no second applied candidate and no recovery. It was not an escalation based on confidence.

The frozen escalation builder includes the original task prompt and its source/Nano context, previous Super output, and full verification evidence. The preserved Super evidence contains the canonical proposal/patch, application record, candidate source, compilation, stress and semantic results; this deadlock fixture does not require TSan. Deterministic baseline fingerprints are retained. This is a source-path and persisted-evidence audit, not a separately captured wire-level payload.

## Requested research answers

1. **Six Adaptive fixtures stopped successfully at Super.**
2. **One escalated to Ultra:** deadlock_002.
3. **Zero Super failures were recovered by Ultra.**
4. **Ultra never ran after a successful Super verification.**
5. **One Adaptive false fix** occurred: the applied Super bank-transfer candidate.
6. **Yes, verification rejected a mostly successful-looking patch:** original Super-only deadlock_001 passed its oracle and 96/100 stress runs, but four deadlocks made it fail.
7. **No measured candidate passed stress and failed semantics.** There were three semantic failures across runs (two Super-only, one Adaptive), all also failed stress.
8. **No measured candidate passed stress and semantics but failed TSan.** Unexecuted checks are unknown, not zero-race evidence.
9. **Adaptive: 18 calls and 123,499 tokens. Ultra-only: 10 calls and 84,066 tokens.** Adaptive used 46.9% more total tokens despite fewer Ultra calls.
10. **Aggregate verified count was preserved and higher (6 versus 4), with 90% fewer Ultra calls (1 versus 10).** Coverage was not a superset: Adaptive lost race_001 to incomplete Nano triage, while Ultra verified it. This single small suite does not establish statistical superiority or general cost savings.

## Latency

Seconds; inference means/medians are per-job sums of inference attempts. Verification means/medians include evaluated jobs only, and the recorded verifier duration includes candidate compilation. End-to-end values are the runner's recorded job durations, not the total time between launches and observation.

| Mode | Inference mean / median | Verification mean / median | End-to-end mean / median |
|---|---:|---:|---:|
| nano_only | 7.99 / 8.02 | Not measured / Not measured | 26.92 / 27.24 |
| super_only | 5.42 / 4.94 | 380.70 / 375.62 | 378.38 / 414.20 |
| ultra_only | 7.45 / 7.16 | 191.23 / 192.26 | 106.46 / 32.13 |
| adaptive | 11.70 / 10.77 | 206.64 / 178.25 | 181.35 / 210.39 |

Adaptive took longer per job than Ultra-only on this run (181.35 versus 106.46 seconds mean end-to-end). It evaluated more repair candidates (7 versus 4); rejected/incomplete outputs end earlier. Original Super-only and continuation measurements were collected in separate runs with different transport conditions, so raw latency differences are not a controlled model-speed comparison.

## Failure classification and integrations

- Nano-only: ten incomplete responses; no applied patch and no false fix.
- Super-only: eight accepted candidates, five verified, three false fixes, one invalid repair output; one interrupted job remains unknown.
- Ultra-only: four accepted/verified candidates and six incomplete responses. No applied false fix.
- Adaptive: seven accepted candidates, six verified, one false fix; three incomplete Nano triages and one incomplete Ultra response.
- All confirmed requests have request IDs and zero recorded retries. Continuation: 28 calls. Combined: 47 confirmed calls and 355,649 recorded tokens; any request or usage in the original interrupted job remains unknown.
- Reasoning tokens are included in output totals; Nano's reasoning breakdown is unavailable. Ultra consumed its full 2,048-token allowance on reasoning on some incomplete responses. Caps were not increased.
- LangSmith confirmed traces for all 39 completed jobs. Tavily usage: zero.
- No transport or verification infrastructure failures were recorded in completed jobs. The original controller interruption remains separately documented with unknown cause.
- Dollar cost is null: no authoritative pricing provenance is available.

## Interpretation and limitations

The strongest hackathon story is execution-aware stopping with an honest tradeoff: six Adaptive repairs verified at Super, no unnecessary Ultra call occurred, and the single escalation had real failure evidence. Verification also rejected a 96/100 candidate rather than presenting it as fixed.

However, escalation recovered nothing in this sample, Nano triage prevented three Adaptive repairs from being attempted, and Adaptive spent more total tokens and took longer per job than Ultra-only. Super-only remains a useful comparison: 5/9 measured repairs at 60,942 tokens, versus Adaptive's 6/10 at 123,499 tokens. The extra coverage has a measured token cost.

These are measurements on ten small fixtures with one attempt per configured tier, not a statistical ranking. Model stochasticity, the strict output budget, reasoning-token allocation, different routes/context, and cloud timing affect results. Passing finite campaigns and oracles does not prove semantic equivalence, deadlock freedom, race freedom, fairness, or production safety.

**Stopped for review. No additional paid calls, implementation changes, or replay of super_only/race_005 were performed.**
