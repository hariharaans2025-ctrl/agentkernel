# Validation record — Concurrency Bug Hunter

Implementation continues the existing AgentKernel repository and preserves its
runtime/provider/router/verifier boundaries. All changes are local; this work has
not been pushed to GitHub.

## Milestones

| Milestone | Main added/changed files | Validation at milestone |
|---|---|---|
| A | `concurrency/models.py`, `compile/`, `sandbox/base.py`, `sandbox/local.py` | 98 offline tests passed |
| B | `execution/`, `campaign/`, `analyzer/classifier.py` | 106 offline tests passed |
| C | `instrumentation/sanitizer.py`, `analyzer/trace_parser.py` | 109 offline tests passed |
| D | `analyzer/fingerprints.py` | 112 offline tests passed |
| E | `verification/concurrency_verifier.py` | 114 offline tests passed |
| F | `repair/patch_parser.py`, `repair/patch_applier.py` | 122 offline tests passed |
| G | `app.py`, `analyzer/routing.py`, `repair/prompts.py`, `mock_inference.py`, `verification/repair_verifier.py`; bounded runtime tier schedules | 125 offline tests passed; real compiler demo passed 100 post-patch executions |
| H | `providers/nebius_token_factory.py`, nullable core cost fields, telemetry redaction, experimental cloud sandbox placeholder | 135 offline tests passed; HTTP mocks only |
| I | `benchmark/`, five deadlock and five race fixtures, baseline sanitizer gate | 142 offline tests passed; all ten fixtures compiled; all five deadlocks reproduced; TSan integration skipped |
| J | `concurrency/cli.py`, existing CLI dispatch, JSON reports, README, telemetry detail, iterative lock-graph traversal | 154 offline tests passed; 4 integration tests excluded |

All 88 pre-existing tests remain in the full suite. Milestones were implemented and
tested sequentially; failures were fixed before continuing. The first forced-Ultra
compiler test had an unresolved run; a later rerun passed. Its initial cause was not
established. Later CLI evidence also records a transient process-start failure, so
host/toolchain reliability must remain part of interpretation.

## Execution environment and boundaries

- Windows, Python 3.14.7, official LLVM-MinGW 20260908 / Clang 23.1.1, pthreads,
  `-static` for standalone native Windows binaries.
- Portable compiler download checksum was verified against the official release
  asset digest: `1bcf74d06b724aeecaa6412ca85f5b26fb1da770e7cdcefa9263c9c5c3ad34b6`.
  Toolchain files are outside the repository and are not bundled.
- Real compiler processes, program executions, timeout handling, copied workspaces,
  patch application and verification campaigns were exercised.
- Model outputs use a scripted `MockNebiusProvider`; inference tokens, latency and
  per-call costs are synthetic. No live Nebius call, credits or GPU were used.
- Real Nebius API contracts were exercised through mocked HTTP transports. Catalog
  availability for the user's account remains untested.
- The Windows compiler rejects ThreadSanitizer for this target. Race fixtures are
  present and compile normally, but the required TSan counter repair demonstration
  has **not** been validated. These jobs cannot be marked verified on this host.
- The local backend separates files using disposable directories; it does not
  contain hostile native code. Use an isolated development host for untrusted code.
- `NebiusSandboxBackend` remains explicitly experimental/unavailable; no guessed
  endpoints or cloud sandbox claims are included.

## Interpreting results

`reports/deadlock-demo.json` contains the real baseline, structured fingerprints,
mock proposal, patch hash and independent verification. Its configured verification
is 100 runs, zero allowed deadlocks/races/crashes, and expected output `PASS`.
Separate original tests and ThreadSanitizer are not configured for this deadlock.

`reports/windows-mock-comparison.json` compares ten fixtures under all four modes.
It uses one baseline run per fixture to keep this smoke comparison bounded, and
retains each fixture's 100-run verification configuration. Each mode receives a
four-call budget; adaptive triage consumes part of that budget. Required TSan
unavailability is counted and exposed, not scored as a successful race repair.

The mock recognizes only the lock-order and counter examples. It does not attempt
general reasoning for the other source shapes, and it uses identical response logic
at every tier. Therefore these numbers cannot support a claim that adaptive routing
matches Ultra model quality or saves real inference cost.

A schema-valid candidate whose executed verification reveals failures/regressions
counts as a false fix. Rejected patches are separately counted; the false-fix rate
uses all schema-valid proposals as denominator. A zero rate with no applicable
candidates is reported as null, not evidence of perfect repair reliability.

Acceptance wording: **The patch passed the configured verification campaign.**
No run establishes mathematical race/deadlock freedom or full semantic equivalence.

## Host-policy audit and final validation

The later native integration run completed with **2 passed, 1 failed, 1 skipped**.
The failure was the forced-Ultra test: compilation succeeded, but Windows refused
to start the generated executable with `winerror=4551`. The operating system's own
message is: "An Application Control policy has blocked this file." The skipped test
was the unsupported ThreadSanitizer counter integration. The two passing checks
were the ten-fixture compile/deadlock smoke test and an applied-but-wrong candidate
followed by a successful Ultra repair. That latter test observed 100 failing
functional checks, propagated the failure evidence, and then observed 100 passes.

No host security settings were changed and no further native-C integration run was
attempted after identifying the policy denial. Integration tests now explicitly skip
when the environment returns a policy-block result, rather than pretending to pass.
Independent offline tests check the denial path using simulated OS errors.

The code now stops the campaign immediately on Windows policy error 4551, prevents
further model repair attempts through a nonretryable verifier result, and stops an
entire benchmark comparison. Process-start failures cannot count as program
regressions or false fixes. They still prevent verification from passing.

The saved ten-fixture comparison predates this correction. Its false-fix metrics
were **withdrawn**, not replaced with guessed numbers. The JSON preserves original
values under `audit.withdrawn_original_metrics` and explains the issue. The call and
execution totals below are historical measurements from that run; they include its
old retries and must not be treated as predictions for the corrected stopping policy.

| Mode | Verified fixtures | Nano / Super / Ultra calls | Measured execution time |
|---|---:|---:|---:|
| Nano-only | 1 / 10 | 17 / 0 / 0 | 53,664.0 ms |
| Super-only | 1 / 10 | 0 / 17 / 0 | 54,412.5 ms |
| Ultra-only | 1 / 10 | 0 / 0 / 18 | 56,821.3 ms |
| Adaptive | 1 / 10 | 5 / 8 / 4 | 53,212.1 ms |

Each mode reports five TSan-unavailable tasks. The one verified task is the scripted
opposite-lock-order example. All inference measurements are mocked and aggregate
cost is null. This table does not establish a model-performance advantage.

The standalone saved demo observed two deadlock timeouts and one process-start
failure in three baseline attempts, then a Nano -> Super proposal and **100/100
passing executions** in verification. Its measured total elapsed time was
28,697.4 ms. The original fixture remained unchanged. These are actual historical
results, not a guarantee that host policy will permit a future run.


Final offline command used the repository virtual environment and an isolated test
temporary directory: `python -m pytest -q outputs/agentkernel/tests
--basetemp=work/pytest-final-complete -p no:cacheprovider --tb=short`.
`TEMP` and `TMP` pointed to the writable workspace test directory.
Result: **154 passed, 4 deselected in 51.02 seconds**. The four deselected tests are
native compiler/TSan integration tests. `git diff --check` found no whitespace errors.
No changes were pushed and no pull request was created.
