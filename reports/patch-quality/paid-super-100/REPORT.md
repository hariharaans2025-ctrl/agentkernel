# Single paid Super attempt: deadlock_001

Outcome: unresolved. Exactly one real Nemotron Super request was sent using the new exact-source-edit repair contract. No HTTP retries, correction calls, Nano calls, or Ultra escalation occurred.

- Model: `nvidia/nemotron-3-super-120b-a12b`.
- Verification configured from the fixture: **100 runs**, without an override.
- Actual post-patch verification: **0 runs**. The model returned no final answer (`content: null`) and `finish_reason: length`; the provider correctly rejected the incomplete response before patch parsing, application, or verification.
- Usage: 1,890 input tokens and 4,096 output tokens, all output tokens reported as reasoning tokens. The 4,096-token response budget was exhausted before the edit JSON was emitted.
- Measured inference latency: 21.67 seconds (including model availability check).
- Monetary cost: unavailable; no configured pricing estimate is reported.
- LangSmith: confirmed, with 5 spans observed and 5 feedback submissions.
- Original fixture source and task configuration: unchanged (SHA-256 checked).

This attempt does not establish live-model patch quality or a 100-run pass. No partial proposal was reconstructed from the reasoning output. The earlier scripted 10-run regression is separate and is not counted here.

Evidence: `started.json`, `request-count.json`, `request.json`, `response.json`, `inference.json`, `result.json`, `telemetry.jsonl`, and `completed.json`. The one-shot runner refuses to reuse this report directory, preventing an accidental paid rerun.
