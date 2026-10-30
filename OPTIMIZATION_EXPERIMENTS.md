# Optimization experiments v1

These standalone scripts do not change the production dashboard, runtime,
prompts, routing, fixtures, verification requirements or frozen benchmark.
They never call an inference provider. Sandbox use can incur execution charges.

## Scope

`scripts/optimization_experiment.py` measures lossless serialization against ten
stored Adaptive evidence records. Measurements are UTF-8 bytes, not model
tokens. It then replays the saved race_002 Adaptive Super candidate, comparing
the existing serial remote execution with chunks of ten sequential processes
inside each remote instance. Both arms use the unchanged verifier: 100 stress
runs, the fixture semantic oracle and three required TSan runs. Seeds,
environments, timeouts and per-stream output caps are unchanged. Complete
per-run evidence is saved for both stress and TSan campaigns.

The batch runner calls the existing remote child wrapper without modifying it.
Remote checks compare Unicode output, nonzero exits, timeouts and truncated
stdout/stderr against serial execution. Malformed or incomplete batch output
aborts without replay; transport interruption leaves execution outcomes unknown.
Batch duration is bounded below the current SDK operation timeout.

`scripts/escalation_compaction_experiment.py` serializes the recorded failed
Super attempt from deadlock_002 once, preserving failure evidence, proposal,
verification status and instructions. The exact original prompt was not saved,
so both comparison arms use the same original-task sentinel. Its measured
reduction applies ONLY to this failure-context segment, not the full prompt.

## Reproduction

From the repository root, use the existing Python environment to run either
script. The first reads credentials privately from `.env`; the second needs no
network. Each creates a new timestamped directory under
`reports/optimization-experiments`; existing evidence is never overwritten.
The controller does text processing locally, but all child processes, builds
and fixture verification execute in Nebius Sandbox, using
`agentkernel-clang:20261003122908`. Only fixture sources/support files are
uploaded, never credentials. No local execution fallback exists.

## Interpretation

This is one saved repair, with serial before batch and no randomized repetitions.
Service load, warm state and ordering can affect timing. Sharing an instance
changes its lifetime even though each stress run starts a new process. This is
not proof of equivalent race detection or suite-wide speedup. No model received
the compressed representation, so token savings and repair quality are untested.
Reference wrapping adds overhead on records without repeated long strings;
plain minification is better for those records.

Next gates: failure-detection replay on known rejected candidates, balanced-order
timing repetitions, then a separately bounded model comparison with actual usage
accounting. Only after those checks should production integration be considered.
Conditional Nano routing is deferred and would require a separately versioned
policy experiment. Do not replay the frozen interrupted Super race_005 job.
