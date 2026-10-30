# Step 2: repository diagnostics

Model calls: 0. Synthetic controls; no repair attempted.
Protected files unchanged: True. Runtime error: none.
Queue diagnostic runs: 3. User-space thread stacks captured: False.

| Control / method | Diagnostic results |
|---|---|
| racy-serial | data_race, data_race, data_race |
| racy-batch | data_race, data_race, data_race |
| clean-serial | completed_not_verified, completed_not_verified, completed_not_verified |
| clean-batch | completed_not_verified, completed_not_verified, completed_not_verified |

Queue dependency: WORKER holds queue and waits for stats; MONITOR holds stats and waits for queue.
Wait edges are application-reported evidence. Timeouts without a cycle remain unexplained, and sanitizer runtime failures are infrastructure failures.
Raw diagnostics and sanitizer stack traces are retained. Fingerprints omit runtime addresses and retain finding locations.
TSan controls used 3 executions per method/control (12 total), not full repair verification. No production batching rollout or universal detection guarantee follows.
GDB was installed only in a disposable diagnostic snapshot after TSan controls; the pinned base tag is unchanged.
No token savings or application performance improvement is claimed.
User-space stack capture remains unavailable/unverified; inspect debugger evidence before marking Step 2 complete.
