# Adaptive efficiency experiment — 29 October 2026

## Implemented: verified proposal reuse

For repeated requests on an identical codebase input, reuse the previously model-generated canonical patch and run full fresh verification. Never reuse the old PASS verdict. This is an opt-in CLI experiment; the deployed website and frozen hackathon archives are unchanged.

```powershell
.\.venv\Scripts\python.exe scripts\run_adaptive_repair.py --case inventory_stock --mode adaptive --reuse-verified-candidate --max-cost-usd 0.25
```

A cache miss invokes the original adaptive route, including its reviewed budget and model-call limits. A cache hit makes zero model calls and zero model tokens, then runs compilation, original tests, 100 stress runs, the semantic oracle and three TSan runs in a fresh Nebius Sandbox. Failure or infrastructure uncertainty stops the cache attempt; it does not buy another model call automatically. This does not merge a patch into the repository.

The identity includes every editable/protected file's bytes, task configuration and environment, absolute workspace scope, model/adapter policy, sandbox image identifier, and verifier implementation hashes. Changed source, tests, build commands, policy, image identifier or verifier causes a miss. Entries expire after seven days; expired records remain on disk and must be removed explicitly before refreshing the same key. The image is identified by its configured tag, not a remote immutable image digest; fresh verification remains necessary. Cached patches are trusted local artifacts, not imported executable commands.

Cache records live under `work/verified-candidates`. They are excluded from release packages. Admission requires complete passing verification and original tests. Results record hit/miss, lookup time, originating evidence, zero current model usage, and the new verdict. An old verified patch is never counted as a new model-generated repair or an unseen success.

## Measured repeated-input demonstration

| Measurement | Preserved original model run | Fresh proposal reuse |
| --- | --- | --- |
| Outcome | Verified | Verified again |
| New model calls | 1 local specialist | 0 |
| New model tokens | 502 | 0 |
| Hosted inference charge | $0 | $0 |
| End to end | 91.61 s | 38.56 s |
| Stress | 100 / 100 | 100 / 100 |
| Original tests / semantics / TSan | Passed / passed / 3 passed | Passed / passed / 3 passed |

The baseline already had no hosted inference charge, so this test demonstrates avoided inference and tokens, not a measured dollar saving. Reusing a proposal that previously required a paid model could avoid its new inference charge; that case has not been measured here. Runs occurred on different dates and network conditions, so the wall-clock comparison is descriptive, not a controlled speedup estimate. No new paid model call was made. The original evidence hashes remained unchanged.

New evidence: `reports/candidate-reuse/20261029T165000Z/comparison.json`. Original model evidence: `reports/sites-console/runs/2c402840-71de-4ce2-a684-0e67dc7a9d75`. The validation script reconstructs the exact saved candidate from the patch and verifies captured original file hashes before admitting it.

37 focused tests passed: cache identity/invalidation, corruption, expiration, weak verifier rejection, fresh verifier invocation, unknown outcomes, cache-miss delegation and existing adaptive/runtime behavior. Routing/verification control tests use fakes. The repeated-input demonstration above uses the real Nebius Sandbox verifier.

## Next optimizations, in priority order

1. **Resident specialist worker.** The old inventory call spent 46.92 s in local inference, which includes model loading and generation. A worker retaining the loaded adapter could avoid repeated loading. Measure cold versus warm time separately before changing the default; serialize requests, bound GPU memory and isolate credentials. Potential improvement is unmeasured.
2. **Failure-specific evidence packets.** Start with exact conflicting-access stacks, lock/barrier relationships and the smallest complete dependency scope. Store full evidence by hash and expand deterministically when required. Preserve every editable source and required contract; measure verified rate and semantic regressions against the complete-context arm. Do not simply truncate TSan stacks or source to meet a token target.
3. **Route by measured break-even performance.** Choose the local specialist only for supported context sizes and bug families with enough verified calibration data. Compare expected time/cost per verified repair with direct Super, including failed calls and verification. Two held-out cases are too few to calibrate a reliable learned router.
4. **Avoid repeated source uploads.** A Nebius snapshot of the frozen source/toolchain could become the base for each candidate if the SDK supports safe branching. Keep each candidate isolated and rebuild/reverify. No sandbox snapshot reuse is implemented by this change.
5. **Keep output edits small.** Use the existing numbered-line repair contract on the experimental v3 route rather than repeating full source in responses. Preserve its fixed reviewed caps and compare invalid/truncated responses as well as tokens. Do not silently change the deployed v2 prompt.

None of these prospective savings is a benchmark claim. No provider prompt-cache billing discount is assumed. The full verifier remains mandatory for all accepted proposals.
