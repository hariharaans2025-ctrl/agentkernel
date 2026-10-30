# Verification outcome: rejected

The exact saved Super candidate passed 100/100 stress executions, both original tests, and the required semantic oracle. ThreadSanitizer detected a data race in all 3/3 executions. There were no infrastructure failures in this fresh verification campaign. This is a false fix, not an accepted repair.

The model moved the barrier waits out of critical sections, removing the previously observed hang. It also removed the common locking around shared queue statistics: queue_process_one updates completed under queue_lock, whereas queue_inspect reads completed under stats_lock. Different mutexes do not synchronize these conflicting accesses. TSan reports a four-byte read and prior write protected by different mutexes. Its external symbolizer was unavailable, so the raw report contains binary offsets rather than source lines; the completed-field attribution comes from source review.

Stress and semantic success do not establish race freedom. The full verification gate correctly rejected this candidate despite 100% stress success and model confidence of 0.95. No patch was promoted to the original example or production runtime.

This campaign made zero model calls and used zero new inference tokens. The original Super request used 5,022 input plus 1,040 output tokens (6,062 total), with 5.564 seconds provider latency. Fresh verification took 61.128 seconds; its full controller elapsed time was 74.951 seconds. The interrupted campaign remains a separate UNKNOWN result and its elapsed time is not erased or included in this fresh verification duration.

All 565 protected files were unchanged. Full per-batch and combined campaign evidence is retained. These measurements describe one synthetic example and do not establish statistical improvement.
