# Step 4 measured outcome

The approved two-call experiment completed. Compact context reduced actual
provider-reported token usage, but both proposed repairs failed verification.
No candidate was applied to the example project or deployed.

| Metric | Full | Selected/grouped |
|---|---:|---:|
| Super calls | 1 | 1 |
| Input tokens | 5,299 | 4,384 |
| Output tokens | 612 | 549 |
| Total tokens | 5,911 | 4,933 |
| Provider wall time (includes catalog check) | 5.619 s | 5.264 s |
| Verification time | 254.001 s | 250.812 s |
| End-to-end arm time | 273.763 s | 263.560 s |
| Stress passes | 0/100 | 0/100 |
| Stress timeouts | 100/100 | 100/100 |
| Semantic oracle | Passed | Passed |
| TSan execution timeouts | 3/3 | 3/3 |
| Verified repair | No | No |

Actual input counts matched the saved public-tokenizer predictions in this pair.
Input reduction was 915 tokens (17.27%); total reduction was 978 tokens (16.55%).
Total experiment usage was 10,844 tokens, within the 24,000-token budget.
There were no retries, correction calls, substitutions or Nano/Ultra calls.
Monetary cost is unknown because no pricing measurement is available.
Tokens per verified repair is undefined because neither repair verified.

Both canonical patches are byte-identical. They change the monitor to acquire
the queue mutex before the stats mutex, but keep the barrier inside the queue
critical section. The first arriving thread holds the queue mutex and waits for
the other barrier participant; the other thread cannot acquire that mutex to
reach the barrier. The existing instructions warned about this pattern, but
neither response corrected it.

The sequential semantic check still passes. This demonstrates why it cannot
replace concurrent stress verification. The TSan runs timed out; they did not
report a data race. They are failed required executions, not clean sanitizer
passes or evidence that the program is race-free.

This pair demonstrates input-token reduction, not a successful optimized repair,
general repair-quality preservation or statistically established latency gains.
Two false fixes were rejected by real verification. All 469 protected files
remain unchanged. The historical interrupted Super race_005 was untouched.

The next repair experiment should explicitly check barrier reachability while
preserving worker/monitor functionality and the protected tests. No such retry
or additional paid request is included in this result. Conditional Nano routing
also remains a separate, unperformed experiment.
