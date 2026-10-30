# Model-generated repair: runtime verified, scheduling policy deviation

The Qwen model generated the patch and Nebius Sandbox executed the full mandatory verifier. The returned edits were applied exactly, without an assistant source-code correction. Neither the manual repair nor reference repairs were included in the request.

The patch adds guard locking around both reads in snapshot_ok. The existing candidate already held that same guard across both writes. This addresses the remaining unsynchronized reader. It also removes the reader's sched_yield hook, contrary to the explicit prompt instruction. The earlier failed correction had already removed the writer's hook, and this call did not restore it. The original source had two hooks; the final candidate has zero.

**Runtime verification passed. Full policy compliance failed. The artifact is not promoted as a fully compliant repair.** The fixed verifier checks correctness of the protected workload and tests, but does not enforce preservation of scheduling hooks in editable source. This audit keeps that distinction explicit; no manual change was inserted into the model patch.

| Check | Result |
|---|---|
| Compilation | PASS |
| Protected original tests | PASS |
| Stress | 100/100 PASS |
| Semantic oracle | PASS |
| TSan | 3/3 PASS |
| Protected interface and oracle | Unchanged |
| Scheduling-hook preservation | FAIL |
| Runtime recovery | Yes |
| Full policy compliance / promotion | No |

## New model call

- Model: `Qwen/Qwen3-30B-A3B-Instruct-2507`; temperature 0; 2,048 output-token cap.
- One newly authorized call; no retries or separate paid critique.
- Input tokens: 11,387; output tokens: 438; total: 11,825.
- Inference latency: 12.93 s.
- Verification latency: 28.66 s.
- End-to-end latency: 48.00 s.
- Calculated inference cost: $0.0012701, below the frozen $0.0268288 bound; Sandbox is free per user confirmation.

## Preserved history

The initial few-shot attempt remains rejected (5,889 tokens). The first model correction remains rejected (11,923 tokens). The new second correction passed runtime verification (11,825 tokens) with the scheduling deviation above. Across all three calls, total usage is **29,637 tokens**, with 131.68 s summed active end-to-end time, excluding time between attempts and preparation.

See attempt-lineage.json for totals across all three model calls. The inherited results.json combined fields include only the first attempt and the newest correction, so they must not be interpreted as the full lineage. Frozen first-attempt benchmark scores remain zero-shot 2/4 and few-shot 3/4. All prior evidence hashes remained unchanged.

This is an adapted recovery experiment on a previously inspected case, not fresh held-out generalization. The prompt added an edit-coverage self-check; it did not supply successful source edits. The final audit demonstrates a remaining acceptance-policy gap even when runtime tests pass.

Evidence: [exact model source](model-produced-project/solution.c), [canonical correction](correction.patch), [raw response](response.json), [runtime verification](verification.json), [acceptance audit](acceptance-audit.json), [full lineage](attempt-lineage.json), [frozen request](payload.json).
