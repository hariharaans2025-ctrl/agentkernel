# Live Super direct-edit validation

Outcome: the model returned valid exact-source edits, the generated patch applied and compiled, and the patched temporary workspace passed the fixture's full **100/100 verification campaign**.

- Exactly one paid Super request; zero transport retries, correction calls, or escalation.
- Model: `nvidia/nemotron-3-super-120b-a12b`.
- Request: `chat_template_kwargs.enable_thinking=false`, output cap 4,096 tokens.
- Response: `finish_reason=stop`, 1,890 input tokens, 661 output tokens, zero reported reasoning tokens.
- Measured inference latency: 4.75 seconds, including catalog check.
- Verification: 100 requested and completed; 100 PASS; zero deadlocks, crashes, or infrastructure failures. Build plus verification took 12.84 seconds.
- ThreadSanitizer and additional original tests were not configured for this fixture. Zero race detections is not proof of race freedom.
- LangSmith confirmed all 7 spans; 11 feedback submissions.
- Monetary cost unavailable without configured pricing.
- Original fixture source and configuration were unchanged, checked by SHA-256.

## Patch review limitation

The candidate releases the first mutex before the barrier, locks and unlocks the second mutex, then locks and unlocks the first mutex again. It never holds both mutexes simultaneously. This eliminates circular wait for this fixture, which contains no protected shared-data operation, but changes the original locking semantics. The campaign verifies termination and the fixture's configured behavior, not preservation of a hypothetical critical section requiring both locks. Do not generalize this result to arbitrary shared-state code or claim a semantic-equivalence proof.

No model output was manually repaired. The candidate was applied only to a temporary execution copy. The original benchmark remains intact.

Evidence: `request.json`, `response.json`, `inference.json`, `result.json`, `telemetry.jsonl`, `candidate-1.patch`, `request-count.json`, and the start/completion manifests. This is a separate authorization and report from the earlier truncated paid attempt.
