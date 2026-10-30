# Concurrent queue/shared state

Deliberately faulty C/pthreads workload for `race_004`.

Expected behavior: terminate with PASS while preserving: All 200 items consumed exactly once. The independent trusted `oracle.c` checks state after execution; deleting work cannot pass merely by printing PASS. Only main.c is editable.

Build: `gcc -pthread -g -O1 main.c -o app`
Run: `./app`
Semantic harness: `gcc -pthread -g -O1 oracle.c -o semantic`, then `./semantic`.

Verification: 100 stress executions plus the required semantic harness and 3 required Clang ThreadSanitizer executions.
Trusted commands are in task.json. Baseline: 3 executions. Sanitizer unavailability blocks required verification; it is not evidence of race freedom. Source hashes distinguish this fixture version from historical reports.
