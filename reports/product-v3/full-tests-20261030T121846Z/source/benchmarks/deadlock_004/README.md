# Cache and logger nested locks

Deliberately faulty C/pthreads workload for `deadlock_004`.

Expected behavior: terminate with PASS while preserving: Two reads and log writes preserve cache value. The independent trusted `oracle.c` checks state after execution; deleting work cannot pass merely by printing PASS. Only main.c is editable.

Build: `gcc -pthread -g -O1 main.c -o app`
Run: `./app`
Semantic harness: `gcc -pthread -g -O1 oracle.c -o semantic`, then `./semantic`.

Verification: 100 stress executions plus the required semantic harness.
Trusted commands are in task.json. Baseline: 3 executions. Sanitizer unavailability blocks required verification; it is not evidence of race freedom. Source hashes distinguish this fixture version from historical reports.
