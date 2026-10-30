# Job queue service: deliberately buggy example

This is a synthetic, small multi-file C/pthreads application inspired by queue
workers and monitoring. It is not a deployed service or an external real-world
bug. It has a fixed in-memory workload, no networking or persistence.

The worker locks queue then statistics; monitoring locks statistics then queue.
`--stress` enables a barrier scheduling hook that forces the lock inversion to
deadlock. `--smoke` processes one job and `--check` processes 100 without a
concurrent monitor. Both assert exactly-once work, queue drain and checksum.
These passing sequential checks alone do NOT establish concurrency correctness.
The stress mode checks those same invariants if the worker and monitor finish.

Only src/queue.c is editable by a repair. main.c, queue.h, the build recipe and
the semantic contract are protected. A repair must preserve worker and monitor
functionality and their synchronization; deleting workload or avoiding the
monitor is not acceptable. The barrier is a test hook, not a production feature.

All builds and execution must run in Nebius Sandbox. The intended workflow is
onboard -> reproduce -> propose edit -> 100 stress runs -> semantic checks ->
3 TSan runs -> performance measurement on a separate unsanitized build.
The initial onboarding step proposes no repair and makes no inference calls.
