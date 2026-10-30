# Repository repair workflow

Improve the system around Nano/Super/Ultra first. No model weights are trained
by this work. Keep the original benchmark, prompts, routing and evidence frozen.
Use new versioned experiments for every comparison.

## 1. Repository onboarding and measurement contract — implemented

Start with the synthetic `examples/job-queue-service` project requested by the
user. It contains a worker/monitor lock inversion, protected workload tests and
an exactly-once/checksum invariant. This is a teaching example, not a real-world
repair result. Source retrieval from GitHub and cloning are not implemented.

The new `agentkernel.repository` command validates explicit editable/support
file lists, rejects unsafe paths, links, common secret filenames and overlapping
test/source paths, checks file size limits, and records SHA-256 identity. File
selection is an allowlist, not a general-purpose secret scanner. Review selected
files and commands before remote execution. No credentials belong in the contract.

Example from the AgentKernel root:

```powershell
.\.venv\Scripts\python.exe -m agentkernel.repository --root examples/job-queue-service --config examples/job-queue-service/agentkernel.repository.json --out reports/repository-onboarding/my-new-plan
```

The output directory must not already exist. Planning reads files only: it does
not execute commands, upload a repository, clone Git, or call a model.

Proposed limits for this NEW repository workflow: 3 model calls, 24,000 total
tokens, 6,000 input tokens and 2,048 output tokens per call, 1,800 seconds wall
time. These do not alter existing provider configuration. A tested reservation
component blocks calls whose known input + maximum output would exceed the
budget, blocks overlapping unsettled calls, and stops after unknown usage or a
provider overrun. It requires a trustworthy tokenizer count including request
overhead. It is not connected to live providers yet; wall-time enforcement is
also future work. No claim of runtime budget enforcement is made at step 1.

**Completion evidence:** targeted tests in Nebius, source build, passing smoke
and exactly-once tests, and a 3-run baseline reproducer. A repair is not attempted.

Completed validation: `reports/repository-onboarding/20261007T110957Z/REPORT.md`.
23 targeted tests passed remotely. The application built, both ordinary tests
passed, and all three concurrent executions logged opposing lock waits and timed
out (classified POSSIBLE_DEADLOCK). Zero model calls; 371 prior protected files
unchanged. Earlier unsuccessful validation directories remain intact for audit.

## 2. Reproduction and evidence collection

**Completed for the synthetic example.** Evidence review:
`reports/repository-diagnostics/review-20261007T114952Z/REPORT.md`.
Eight diagnostic tests passed. Both serial and batch TSan detected the racy
control in 3/3 runs and accepted the mutex-protected control in 3/3 runs.
The queue reproduced opposing waits in 3/3 timed-out runs. GDB captured worker
and monitor stacks blocked in pthread_mutex_lock at queue.c:19 and queue.c:37.
All 430 protected files remained unchanged; no inference calls were made.

The first stack-result gate required an unavailable libc pthread_join symbol.
The separate review corrected that check using the saved raw capture without
repeating executions or modifying the original report. Lock dependencies are
currently extracted from explicit application HOLD/WAIT logs; automatic tracing
of arbitrary uninstrumented repositories remains future work. These controls do
not establish generic detection equivalence or authorize production batching.

Capture thread stacks on timeout, progress events, lock ownership and waits;
distinguish suspected deadlock, confirmed wait-cycle, race and infrastructure
failure. Add a known TSan-failing control to the batching experiment. Keep all
per-run records, seeds, toolchain/image identity and command timeouts.

**Gate:** reproduce both a known deadlock and a known race; both serial and batch
verification must reject the negative controls. Timeout alone remains suspected
deadlock. Sandbox support for stack collection must be measured, not assumed.

## 3. Smaller, useful model context

**Completed for the synthetic queue example.** Evidence:
`reports/repository-context/20261007T120315Z/REPORT.md` and `context-result.json`.
Six tests passed in Nebius. Clang indexed seven project functions and retrieved
their connected caller/reference set. All three C/header files were retained
byte-for-byte; README and Makefile prose were omitted while explicit build argv
and verification requirements stayed intact. Identical observations were grouped
with every original run field retained and round-trip checked. Full captured
thread stacks and repair instructions were unchanged.

Measured public Super-tokenizer input counts (including chat template): full
5,299; minified full 5,122; selected/grouped 4,384. Reduction: 915 tokens (17.27%)
versus the newly constructed full-context prompt. This is NOT a measurement of
historical benchmark prompts or provider-billed tokens. The tokenizer revision
and asset hashes are recorded; no model weights or remote model code were loaded.
All 460 protected files remained unchanged and zero inference calls were made.
Preparation took about 325 ms in one sandbox observation, excluding setup and
tokenizer download; this is not an end-to-end repair speedup.

The three exact message sets are saved for Step 4. Nebius tokenizer equivalence,
Nano/Ultra counts and repair-quality preservation remain untested. The source
index currently uses this example's C include flags, not a general repository
compilation-database adapter. Unresolved seeds/includes stop preparation.

Index functions, callers, locks and shared data. Retrieve relevant source and
dependencies; deduplicate repeated evidence and serialize each failed attempt
once. Keep protected tests outside editable context. Archive exact final prompts
and use provider-compatible tokenization to measure input, rather than treating
byte reductions as token savings. Keep uncropped source blocks for exact edits.

**Gate:** compare context/token size and missing relevant evidence on fixed cases.
Existing results are 12.3% evidence-byte reduction and 57.9% reduction of one
failure-context segment; neither demonstrates model token or quality improvement.

## 4. Bounded model repair experiment

**Full-versus-compact comparison completed; neither repair verified.** Results:
`reports/repository-live-ab/20261007T121122Z/ANALYSIS.md`.
Exactly two approved Super calls used 10,844 tokens total. Provider input counts
matched Step 3: 5,299 versus 4,384 (17.27% reduction). Including outputs, usage
was 5,911 versus 4,933 (16.55% reduction). Both produced the identical patch,
which retained a barrier while holding the queue mutex. Each failed 100/100
stress runs and all 3 TSan runs by timeout, despite passing sequential semantic
checks. Neither candidate was deployed or applied to the original example.

The experimental runner used token reservations, provider usage reconciliation,
a 1,800-second deadline, no retries and full verification. All 469 protected
files remained unchanged. This does not prove general tokenizer equivalence,
repair-quality preservation, or latency superiority. Conditional Nano routing
and integration into production remain unperformed; future experiments must
address barrier reachability before claiming verified repairs.

Wire the reservation component, actual provider usage, deadlines and model IDs
into a NEW experimental runner. Keep a small declared call/token budget. Compare
full-context vs compact-context first; only then compare compulsory vs conditional
Nano triage. Keep all other settings fixed within each comparison. Super may
stop the chain only after real verification; Ultra receives actual failure
evidence under the versioned policy. No confidence-only escalation.

**Gate:** compare verified repairs, invalid output, false fixes, input/output
tokens, calls per tier and tokens per verified repair, including tokens spent on
failed jobs. Unknown provider usage blocks another call; it is never zero cost.

## 5. Candidate verification

Apply canonical source edits in a fresh remote workspace. Preserve protected
tests, the original workload and support hashes. Run the original tests, 100
stress executions, semantic oracle and 3 TSan executions for the sample contract.
Add a reproducer-derived regression test without allowing the model to weaken
the original tests. Batching remains experimental until negative-control gates
are satisfied. Do not silently reduce verification counts to meet a time budget.

**Gate:** all required checks pass. Incomplete verification remains unknown, never
verified. Passing finite campaigns does not prove absence of concurrency bugs.

## 6. Application performance

Use separate unsanitized builds and equivalent hardware/workloads. Alternate
before/after order and repeat measurements. Measure throughput, p50/p95/p99
latency, CPU, memory and lock wait time. Set acceptable regression bounds before
running the comparison. A patch that fixes deadlock by serializing work still
needs performance review. If baseline hangs, report completion rate and timeouts;
do not compare conditional latency of only successful requests as total latency.

**Gate:** correctness plus measured performance within declared bounds. Faster
verification is a tooling improvement, not proof of a faster repaired application.

## 7. Reviewable delivery and continuous evaluation

Produce a patch/branch, reproducer, regression test, exact inputs, toolchain,
verification report, cost/usage and performance comparison. Add repository and
commit views to the existing dashboard. Create a PR only within the user's
authorized repository workflow; production deployment is a separate action.
Grow evaluation with external real bugs after the synthetic example works.
Split evaluation by repository and bug family to reduce leakage. Consider
fine-tuning only after enough reviewed, verified examples and a held-out set exist.

## Metrics contract

| Area | Measurements |
|---|---|
| Outcomes | Verified, rejected, interrupted/unknown; accepted candidate count |
| Correctness | Stress failures, semantic regressions, TSan findings, false fixes |
| Model use | Calls by tier, input/output tokens, finish reason, invalid JSON, provider usage availability |
| Efficiency | Total tokens / verified repairs; unknown if usage is incomplete or no repairs verified |
| Latency | Inference, context preparation, build, stress, semantics, TSan, transport, end-to-end |
| Application | Throughput, latency percentiles, CPU, memory, lock contention |
| Provenance | Content/contract hashes, model IDs, prompt version, compiler/image, seeds |

At step 1, the metrics primitives aggregate total calls/tokens/latency/cost and
outcome counts. Stage-level instrumentation and application metrics are planned,
not already implemented. Missing measurements and prices remain null. Unknown
jobs do not enter the rejected count. Ratios must state their denominator.

All production source paths outside the new repository package remain unchanged.
Frozen Super race_005 stays INTERRUPTED / UNKNOWN and must not be replayed.
