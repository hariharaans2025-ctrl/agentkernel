# Real cloud repair and matched route evidence

The primary cloud demonstration makes fresh NVIDIA Nemotron calls through Nebius Token Factory and verifies proposed code in Nebius Sandbox. The candidate-reuse experiment is a separate optional repeated-input optimization. It is not evidence of new model repair ability.

## Recorded fresh repair

Evidence: `reports/cloud-adaptive/20261029T165615Z`.

Super proposed a patch that passed original tests, 100 stress runs and semantics but failed all three TSan runs. The controller rejected it. Ultra then produced a new patch that passed every gate. This route used 2 remote calls, 3,348 tokens and $0.0028022; measured end-to-end time was 58.66 seconds. It used neither the local specialist nor a cached candidate. The route reserved at most $0.0438624 before execution.

The result's `false_fix: true` records the rejected intermediate Super candidate. It does not mean that the final accepted Ultra repair failed verification. Always report both the intermediate false-fix candidate and final route outcome.

## Prospective comparison

Protocol: `reports/cloud-comparison/20261029T170003Z/protocol.json`.

- All eight pre-existing synthetic product-v1 test designs; no selection based on a favorable result.
- Super-only, Ultra-only, and cloud adaptive Super → Ultra: 24 jobs, at most 32 paid calls.
- Same per-model prompts/contracts and component caps: 12,000 input tokens; 4,096 output for Super and 8,192 for Ultra. The adaptive fallback receives the preceding failure summary as part of its policy.
- Same original source, protected files, oracle and verification requirements for every arm. Reference repair files are excluded from model inputs.
- Fresh model calls only; no local specialist, cached proposal, correction retry, or post-result policy change.
- Independent sandbox baseline per job; two concurrent jobs with rotated arm order. Latency is measured under these shared-service/network conditions.
- Pre-established incremental inference ceiling: $0.7017984. Unknown calls retain their reservation.

The cases are existing designs, not claimed to be unseen by all historical development or by model pretraining. This is a per-suite systems comparison, not a general model leaderboard. Invalid responses are failures of the tested pipeline/model combination, not necessarily failures of the underlying model on every prompting strategy.

The runner writes `comparison-view.json` and `REPORT.md` as jobs finish. Only `complete: true` is a final comparison. `analyze_cloud_comparison.py` audits accepted outcomes against their original verifier files, preserves unknowns, counts unnecessary Ultra calls, and emits supported claims. `render_cloud_scorecard.py` produces a read-only HTML evidence viewer for judges without credentials or new inference charges.

## Reproduction

The preparation command lists the complete future charge bound without starting inference:

```powershell
.\.venv\Scripts\python.exe scripts\compare_cloud_routes.py --prepare
```

Running `--execute` with the returned protocol path starts the paid comparison. An existing executed/interrupted protocol cannot be automatically replayed. A deliberate new comparison creates a new directory and incurs new charges. The prototype's persistent ledger and conservative pilot ceiling must still permit it.

## How to present the result

Compare verified count, invalid responses, rejected false-fix candidates, total tokens/cost including failures, tokens and cost per verified repair, median end-to-end latency, and Ultra calls. Report unknowns separately. If adaptive recovers Super failures but spends more than Ultra-only, state that tradeoff explicitly. Never claim that adding stages is universally cheaper, faster, or more accurate.

For the hackathon, the strongest defensible demonstration is a real model response, a strict independent verifier, an evidence-driven escalation, and an accepted patch with reproducible evidence. Superiority claims need measured support and broader independent evaluation, not selected successes or altered baselines.
