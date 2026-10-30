# Model repair attempt comparison

One synthetic job-queue example. All three attempts used Super, temperature 0, no thinking, 2,048 output-token cap, and one model call each. Compact plus diagnostic differs only by added original-source static evidence; no known-good repair was included.

| Attempt | Input | Output | Total tokens | Provider seconds | Complete verification seconds | Stress | TSan | Verified repair |
|---|---:|---:|---:|---:|---:|---|---|---|
| Full context | 5299 | 612 | 5911 | 5.619 | 254.001 | 0/100 | 3/3 timeouts | Rejected |
| Compact context | 4384 | 549 | 4933 | 5.264 | 250.812 | 0/100 | 3/3 timeouts | Rejected |
| Compact + barrier diagnostic | 5022 | 1040 | 6062 | 5.564 | 61.128 | 100/100 | 3/3 races | Rejected |

Compared with compact alone, the diagnostic attempt used 1129 more tokens (22.89%): input +638 (14.55%), output +491 (89.44%). Provider latency changed by 5.71%.

All attempts passed their completed semantic checks, but all were false fixes. Earlier candidates deadlocked; the diagnostic-assisted candidate passed stress but introduced a TSan-detected race. Verified model repairs remain 0/3. Tokens per verified repair is undefined, not zero.

Recorded controller times: full 273.763s; compact 263.560s; diagnostic interrupted attempt 81.398s plus separate verification 74.951s = 156.348s. The sum excludes tokenizer setup, recovery and waiting between turns. It is not a comparable continuous end-to-end measurement.

The diagnostic inference call used 6,062 tokens once. Verification used no further inference tokens. Complete verification took less time because stress runs terminated instead of timing out; this does not demonstrate a faster or correct application.

Across all three attempts: 16,906 inference tokens, three model calls, zero verified model repairs. The manually authored repair and additional positive controls are excluded from model-success counts.

One attempt per condition cannot establish statistical superiority or attribute the outcome change causally to the diagnostic. All prior evidence remains unchanged.
