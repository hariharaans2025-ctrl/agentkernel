# Interrupted diagnostic-assisted repair

The single Super call completed: 5,022 input + 1,040 output = 6,062 tokens, 5.564 seconds provider latency. The candidate was applied in Nebius Sandbox.

DNS resolution failed while retrieving the last stress batch. A read-only fetch recovered 10 executions from that existing operation, with 10 passing. The earlier 90 executions were reported as completed by progress output, but their detailed results were held in memory and not persisted before interruption. Do not claim 100/100 or even 90/100 passes.

Overall verification: **INTERRUPTED / UNKNOWN**. Semantic and TSan results are unavailable. No workload was replayed and no additional model call was made.

Source review: the model removed the barrier-with-held-lock pattern, but writes q->completed under queue_lock while the monitor reads it under stats_lock. These different mutexes do not synchronize the accesses. This is a suspected introduced data race, not a measured TSan result. The emitted HOLD/WAIT messages also no longer describe the actual lock state.

The candidate is not accepted or promoted. Original run evidence remains immutable. Completing evaluation requires a separately recorded verification-only campaign against the exact saved candidate, with no model call or source edits.
