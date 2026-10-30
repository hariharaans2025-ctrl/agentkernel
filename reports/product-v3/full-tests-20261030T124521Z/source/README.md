# AgentKernel

For the packaged product, private website, and ChatGPT plugin, start with [START_HERE.md](START_HERE.md).

AgentKernel is an adaptive inference runtime. **Concurrency Bug Hunter** is its first
application: an execution-aware debugger for C/pthreads programs.

> We don't ask the model whether the patch works. We try to make the patch fail.

AI proposes a candidate; independent compilation, tests and repeated execution decide
whether it passes the configured verification campaign. Successful runs do not prove
that a program is race-free or deadlock-free.

## Model comparison dashboard

On Windows, double-click **Launch Dashboard.cmd**, or run `./Start-Dashboard.ps1`
and open [Model Lab](http://127.0.0.1:8766). Keep using that address rather than
opening `static/index.html` as a file: run controls need the controller API.
On other platforms, run `python -m agentkernel.dashboard.server --root .`.

The dashboard connects to the configured real Nano, Super, and Ultra models.
Choose a fixture and models, then select **Run comparison**. This explicitly starts
paid inference (at most one call per model, no retry or escalation) and remote
sandbox verification using the fixture's configured run count. The comparison
freezes the source; each model gets its own baseline measurement. Super uses the
validated thinking-off setting; other models retain their provider defaults, which
are visible in Evidence. Responses, patches, usage, latency, verification, and
unknown pricing are displayed separately. **Stop after current model** prevents
queued model calls without interrupting the current verification campaign.

The interface and API controller bind only to loopback; credentials stay in the
private `.env`. All fixture compilation and execution remain in Nebius Sandbox.
Saved comparisons live in `reports/dashboard`; interrupted requests are never
automatically replayed. The imported Super example is explicitly a saved response
replay, not a new multi-model benchmark. Its synthetic inference metrics are hidden.

## Runtime architecture

```text
Trusted C/pthreads project -> disposable copy -> build -> stress campaign
  -> deterministic classifications, lock graph, compact fingerprints
  -> Nano triage -> Super repair -> apply diff in a fresh copy
  -> rebuild + original tests + stress campaign + configured ThreadSanitizer
  -> PASS: stop
  -> FAIL: retain evidence -> optional Super retry -> Ultra -> verify again
```

`AgentKernel` owns routing, provider calls, evidence propagation, limits, verification
interfaces and telemetry. `agentkernel.concurrency` owns the compiler, campaigns,
patching, concurrency policy and application. The private hosted console is in sites/agentkernel-console; the earlier local dashboard remains available.

The existing local inference boundary remains:
`AgentKernel -> LocalRTXProvider -> LocalInferenceBackend -> OllamaBackend`.
The concurrency application does not force local inference into its route.

## Install and run

Requires Python 3.11+ for the controller and Nebius Sandbox access. Compilation,
program execution, original tests, and verification campaigns run in remote Linux
snapshots through Contree SDK 0.3.6. There is **no local execution fallback**.

Your private `.env` needs `NEBIUS_API_KEY` and `NEBIUS_PROJECT_ID`. The configured
project is `aiproject-e00z8mw0ggdmwn69nb`. The default execution image is
`python:3.12`, whose GCC compiler was checked remotely. Use Linux compiler names
such as `gcc`, not a Windows compiler path. ThreadSanitizer support still needs a
separate remote validation; a plain GCC build does not establish sanitizer support.

```sh
python -m pip install -e ".[dev]"
# Upload source/tests and execute the suite inside Nebius (no paid model call):
python scripts/push_sandbox.py
# Run a fixture; mock inference is explicit here, execution is still remote:
python -m agentkernel.cli concurrency run benchmarks/deadlock_001 --env-file .env --inference-mode mock
```

Model inference and sandbox execution are separate services. Remote execution may
consume sandbox credits even with mock inference. The controller retains keys and
report files; credentials, `.git`, `.venv`, and local binaries are not uploaded.
The source checkout remains editable locally. Remote commands never inherit the
controller's environment. Pure text patch validation uses temporary local staging;
no compiler or candidate binary runs there.

The deployed source/test snapshot is `agentkernel-project:20260928`; its image ID
and upload manifest are in `reports/nebius-sandbox/migration/deployment.json`.
Each baseline and repair gets a fresh remote workspace. Commands preserve filesystem
snapshots between runs; active instances terminate when each command finishes.
The SDK does not expose snapshot deletion, so stored images follow service retention.

## Commands and reports

```sh
# Save the full job contract (including candidate diffs) and compact telemetry.
python -m agentkernel.cli concurrency run benchmarks/deadlock_001 --json-output reports/deadlock.json --telemetry-jsonl reports/deadlock.jsonl
# JSON only on stdout; smaller campaigns for a smoke check.
python -m agentkernel.cli concurrency run benchmarks/deadlock_001 --stress-runs 1 --verification-runs 10 --json
# Fixed-tier comparison for one task, or all ten fixtures.
python -m agentkernel.cli concurrency run benchmarks/deadlock_001 --mode super-only
python -m agentkernel.cli concurrency benchmark benchmarks --json-output reports/comparison.json
# Explicit network action; checks configured models, makes no inference request.
python -m agentkernel.cli concurrency models
```

`run` exits 0 for `verified` or `baseline_clean`, 1 for an unresolved/build/tooling
failure, and 2 for invalid configuration. `baseline_clean` means no configured failure
was observed, not that a repair occurred. `benchmark` exits 0 when the comparison
finishes even if some tasks remain unresolved; inspect its per-job statuses. Progress
uses stderr, so `--json` stdout stays machine-readable.

The dashboard contract includes `task`, `status`, `route`, `ultra_avoided`, baseline
counts/fingerprints, verification, repair proposals/diffs/hashes, call counts, model
IDs, tokens, latency, nullable cost, inference mode and stop reason. The report keeps
representative evidence rather than every full run. `event_type=concurrency_job`
extends the existing attempt and execution JSONL events. Dispatch by `event_type`;
`TelemetryRecorder.events` remains attempt-only. Export redacts credential fields,
known environment secret values and bearer tokens. Review reports before sharing.

## Trusted task configuration

Each fixture contains `main.c`, optional headers and `task.json`. Commands are argv
lists from trusted configuration, never model-generated command text. The loader pins
the workspace to the selected directory. Only explicitly listed files are copied.
No evaluation reference repairs are shipped or exposed to models.

```json
{
  "task_id": "my_task",
  "source_files": ["main.c"],
  "build_command": ["gcc", "-pthread", "-g", "-O1", "main.c", "-o", "app"],
  "run_command": ["./app"],
  "binary_path": "app",
  "max_runtime_seconds": 2,
  "stress_runs": 3,
  "expected_behavior": "PASS",
  "expected_bug_category": "deadlock",
  "verification_config": {
    "stress_runs": 100,
    "allowed_deadlocks": 0,
    "allowed_races": 0,
    "allowed_crashes": 0,
    "required_original_tests": false,
    "original_test_commands": [],
    "sanitizer_enabled": false,
    "sanitizer_required": false,
    "sanitizer_runs": 3
  }
}
```

A fresh successful build is always required; a stale binary is never accepted even
if `required_build_success` is false. Configured original tests must pass; marking
original tests required with no commands fails verification. Functional assertions
and expected output are the initial oracle. They are limited: this is not formal
verification or protection against a repair that weakens program semantics.

Campaigns use seeded environment perturbations (`AK_SEED`, `AK_WORKERS`, `AK_WORKLOAD`,
`AK_START_DELAY_US`). Fixtures opt into these hints; not every fixture consumes every
hint. `StressSchedule` can be supplied programmatically to vary worker/workload
choices. This is stochastic concurrency stress testing, not exhaustive schedule
exploration. Timelines reflect explicit fixture logs, not reconstructed OS schedules.
Fingerprints and confidence are deterministic heuristics, not calibrated probabilities.

## Safety and execution boundary

`NebiusSandboxBackend` runs compiler and program commands in remote Linux sandboxes.
The historical local backend remains only for isolated test fixtures and is not
selected by the concurrency runtime, repair verifier, or execution smoke path.
Service failures stop execution; they never fall back to the controller machine.

Execution uses argv with no shell, per-command deadlines and bounded stdout/stderr
(default 64 KiB each). API credentials are not inherited by child processes. Patch
paths reject traversal, absolute paths, links and changes outside allowlisted `.c`/
`.h` files. Patches must match exact source context; creation/deletion/rename and shell
instructions are not accepted. Every candidate starts from a fresh fixture copy and
cleanup removes the temporary workspace. The system prompt treats source/comments,
logs and tool output as untrusted data. JSON outputs use validated schemas.

### Repair generation

Repair models now return `edits`: exact `file`, `search`, and `replacement` blocks
alongside the diagnosis, root cause, confidence, expected effect and risk notes.
Every search block must occur exactly once in the original source. Repeated or
overlapping blocks, unknown paths, double-escaped source text and edits based on a
previous candidate are rejected when they fail exact matching. No fuzzy matching or
automatic escape repair is performed.

Python generates the unified diff headers and counts after all edit blocks validate.
Only this canonical diff reaches the existing strict patch applier. Legacy responses
containing a `patch` unified diff remain supported; reports still contain the
canonical `proposal.patch` and its hash. Format corrections remain within the
existing one-correction/total-attempt limits. Rejection evidence includes error
codes and targeted repair hints.

Prompts now address barrier, join and condition-wait dependencies in addition to
mutex ordering. The execution verifier remains the acceptance test: a well-formatted
edit can still introduce a deadlock. The small Super smoke checks applicability in a
disposable workspace but does not compile or execute the candidate.

See [patch quality validation](reports/patch-quality/VALIDATION.md) for a real C
regression in which a validly formatted false fix deadlocks and the corrected
scripted candidate passes 10 configured verification runs. This does not establish
an improvement in live model success rate.

## Real Nebius Token Factory (opt-in)

The real provider uses Nebius's OpenAI-compatible HTTP API. It checks
[`GET /models`](https://docs.tokenfactory.nebius.com/api-reference/models/list-models)
before requesting a configured tier through
[`POST /chat/completions`](https://docs.tokenfactory.nebius.com/api-reference/examples/text-generation).
Missing/unavailable models return structured failures; no silent substitution occurs.

Set environment variables, or copy `.env.example` to the ignored private `.env`
and use `--env-file .env`. Files are loaded only when explicitly requested;
existing environment variables take precedence. The loader treats values literally
and never executes shell expressions.

```powershell
$env:AGENTKERNEL_NEBIUS_MODE = "real"
$env:NEBIUS_API_KEY = "<your key>"
$env:NEBIUS_TOKEN_FACTORY_BASE_URL = "https://api.tokenfactory.nebius.com/v1"
$env:AGENTKERNEL_NEMOTRON_NANO_MODEL = "<exact catalog model ID>"
$env:AGENTKERNEL_NEMOTRON_SUPER_MODEL = "<exact catalog model ID>"
$env:AGENTKERNEL_NEMOTRON_ULTRA_MODEL = "<exact catalog model ID>"
python -m agentkernel.cli concurrency models
```

For a private `.env` setup, discover the account catalog first. Model IDs are
case-sensitive. The command prints the catalog even when blank configured tier IDs
cause its availability check to exit 1; fill those IDs and repeat the check.

```sh
python -m agentkernel.cli nebius models --env-file .env --json
python -m agentkernel.cli concurrency smoke nano --env-file .env --json-output reports/nano-smoke.json
python -m agentkernel.cli concurrency smoke super benchmarks/deadlock_001 --env-file .env --json-output reports/super-smoke.json
python -m agentkernel.cli concurrency run benchmarks/deadlock_001 --env-file .env --inference-mode real --json-output reports/real-deadlock.json --telemetry-jsonl reports/real-deadlock.jsonl
```

On Windows add `--compiler "C:\path\to\clang.exe" --static` to the Super smoke and
end-to-end commands. These commands explicitly spend inference credits. The tiny
Nano check uses synthetic evidence to validate the protocol. The Super check builds
and reproduces the fixture, calls Nano, then validates a Super repair contract; it
checks patch applicability in a temporary copy without compiling or executing it.
Only `run` runs the configured execution verifier. Stop after one end-to-end attempt before expanding
to benchmarks.

Transport retries are limited to two retries for 429, 500/502/503/504 and temporary
network failures, with bounded exponential backoff. Authentication, permissions,
invalid requests and unavailable models are not retried. Each logical HTTP request
has a 120-second deadline. JSON contract failures receive at most one same-tier
correction within the job's existing inference-attempt budget. Patch rejection and
execution failures retain their evidence for the existing repair/escalation policy.
An inference attempt can therefore contain transport retries; both counts are
reported separately.

Per-call reports include returned model ID, request ID, finish reason, transport
retry count, measured latency (including the catalog check), and returned token
usage. Unavailable usage and unconfigured pricing are `null`. Older numeric token
fields remain compatible; use nullable `metadata.model_attempts` for per-call actual
usage. Unusable completions preserve returned usage when it can be parsed.

Set `AGENTKERNEL_NEBIUS_PRICING_JSON` to a JSON object mapping exact model IDs
to `input_per_million` and `output_per_million` USD prices from your pricing
agreement. Without complete usage and configured pricing, cost is `null`.
Set `AGENTKERNEL_NEBIUS_MODE=mock` to return to offline inference.

## LangSmith observability (opt-in)

Set `AGENTKERNEL_OBSERVABILITY=langsmith`, `LANGSMITH_TRACING=true`, a private
`LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, and the correct regional
`LANGSMITH_ENDPOINT`. Set `LANGSMITH_WORKSPACE_ID` when required by the account.
The default observer is a no-op and makes no network requests.

One job produces a root span with baseline compile/stress, fingerprint, Nano,
Super, patch-application and verification children as those stages occur. Ultra
has its own parent span containing its diagnosis, application and verification.
Only bounded allowlisted metrics, IDs and execution-derived boolean feedback are
sent; source files, prompts, patches, environment dumps and raw logs are excluded.
Existing JSONL telemetry is preserved.

The buffered HTTPX adapter uses the documented
[LangSmith tracing API](https://docs.langchain.com/langsmith/trace-with-api) and
[feedback format](https://docs.langchain.com/langsmith/feedback-data-format).
It reads spans back to check their parent relationships before reporting tracing
as confirmed. Delivery failures are reported separately and do not turn an
unverified repair into a successful one. Flush is bounded to 60 seconds and does
not retry authentication failures. This small adapter is intended for smoke runs,
not production-scale tracing throughput.

The September 19 Milestone K run confirmed real Nano inference and exercised real
Super/Ultra inference, but all end-to-end candidate patches were rejected before
verification. A September 20 follow-up corrected the private workspace ID and
child-span updates, then confirmed live delivery of a metadata-only root/child trace
and one feedback item. The original fixture job was not rerun or replayed.
See [the Milestone K validation report](reports/milestone-k/VALIDATION_REPORT.md).
Tavily has a disabled extension interface only; it makes no requests.

## Routing and limits

Adaptive mode starts with Nano's compact triage. Structured output is checked against
observed counts/run IDs, with at most one correction retry. Super handles ordinary
repair; high-risk tasks or more than two observed lock-order edges start repair at
Ultra. Failed repairs carry source, prior proposals, patch results and verification
evidence into later attempts. Confidence alone cannot make a patch pass.

Defaults: two Super repair attempts, one Ultra attempt, four total inference attempts
including triage. Configure `--max-super-repairs`, `--max-ultra-repairs`, and
`--max-attempts` (or `AGENTKERNEL_MAX_ATTEMPTS`). Fixed modes spend the same total call
budget on one tier without Nano triage. No endless regeneration.

`--max-cost-usd` gates each inference using a provider estimate; real Nebius currently
has no safe pre-call estimate and therefore fails closed with
`cost_estimate_unavailable` when a cost budget is supplied. Post-call configured cost
calculation does not imply pre-call budget guarantees. `--max-latency-ms` prevents new
inference attempts after elapsed job time exceeds the limit; it does not cancel an
in-flight inference or campaign. Subprocesses have independent timeouts.

## Benchmarks and metrics

Five deadlocks: opposite mutex order, missing unlock, nested double lock, joining a
worker while holding its needed lock, and a three-lock cycle. Five races: shared
counter, balance update, check-then-act ticket allocation, producer/consumer flag,
and concurrent list insertion. Race verification requires ThreadSanitizer plus a
correct functional result and stress runs.

Comparison modes are Nano-only, Super-only, Ultra-only, adaptive. Reports measure
candidate proposals, verified repairs, false fixes, call counts, execution time and
time to verified repair. A false fix is an applied candidate whose execution exposes
failures or regressions; rejected patches are separately counted. The false-fix rate
uses all schema-valid candidate proposals as denominator and is null when none exist.
`bugs_diagnosed` counts structured diagnoses, not independently proven root causes.

Mock token/latency values are explicitly simulated; aggregate cost is null in mock
comparisons. Different model modes use the same scripted response logic. These
comparisons validate orchestration, **not model quality or adaptive cost savings**.
The eventual research question needs real model calls on supported execution hosts.

## What is real, mocked, and planned

| State | Capability |
|---|---|
| Real, exercised | Nebius remote GCC compilation, uploads, process deadlines, strict patch application and remote test suite |
| Real, exercised | Nebius account catalog, Nano triage and Super/Ultra inference with actual token usage and latency; K repair attempt unresolved |
| Real, exercised | LangSmith metadata-only root/child trace readback and feedback submission after workspace and adapter corrections; full fixture trace still unvalidated |
| Implemented, platform-limited | ThreadSanitizer build/parsing/verification; native Windows cannot run the required race campaign |
| Mocked | Default Nano/Super/Ultra outputs and their synthetic tokens, latency and per-call cost |
| Preserved | LocalRTXProvider/Ollama adapter, rule router, existing CLI, progressive runtime and earlier tests; GPU use not validated here |
| Implemented | NebiusSandboxBackend is the only concurrency execution backend; no local fallback |
| Planned | Frontend, learned routing, llm-d serving, Tavily grounding, GPU validation and real model-quality study |

No Docker, Kubernetes, database, PR automation or full frontend is introduced.

## Existing runtime demo and local backend

The original CLI stays available and uses its mock verifier unless an application
injects another verifier:

```sh
python -m agentkernel.cli --task "ImportError" --verification-plan '{"LOCAL": false, "NANO": false, "SUPER": true}'
```

Its default ladder is LOCAL -> NANO -> SUPER -> ULTRA. An explicit nondecreasing tier
schedule enables bounded retries for applications. All useful prior failure evidence
is preserved. Inference success alone does not establish verification success.

For the preserved Ollama adapter, install/start Ollama separately, choose an already
installed local model, set `AGENTKERNEL_LOCAL_MOCK=false`,
`AGENTKERNEL_LOCAL_BACKEND=ollama`, `AGENTKERNEL_LOCAL_MODEL=<installed name>`, and
optionally `AGENTKERNEL_OLLAMA_URL=http://localhost:11434`. Use
`python -m agentkernel.cli --health`. No model is installed automatically. An HTTP
response does not prove GPU offload; this project does not measure GPU utilization.

## Tests

```sh
python scripts/push_sandbox.py
# An alternate prepared Linux image can be selected explicitly:
python scripts/push_sandbox.py --image agentkernel-clang:20261003122908
```

The controller freezes and hashes an explicit source allowlist, collects the full
test inventory, and runs every account-independent test in Nebius. It overrides
the usual `integration` exclusion and enables GCC and Clang ThreadSanitizer inside
the prepared remote image. No compiler or repository program runs on the host.
No paid model calls are made by this validation command.

Each run writes immutable source hashes, per-test outcomes, command evidence,
and JUnit reports under `reports/product-v3/full-tests-<timestamp>`. The summary
distinguishes passed, failed, skipped, and deselected tests and flags any missing
outcome. Credentials, model weights, private historical reports, and virtual
environments are excluded from the upload.

The three live-account checks (`nebius` and `langsmith`) remain separately
deselected. They require the owner's credentials; one is a paid Nano smoke test.
Real GPU validation also requires a separate GPU host. These exclusions are
listed explicitly in the inventory and never counted as passing tests. See
[IMPLEMENTATION_REPORT.md](IMPLEMENTATION_REPORT.md) for actual validation results
and [reports](reports) for measured execution artifacts.

### Windows policy blocks and report audit

A later native integration run exposed Windows Application Control error 4551. The
application now returns `execution_blocked`, stops the campaign and further repair
calls, and stops the comparison (exit 1). It does not change or bypass host security
settings. Run native integration only on a development host whose policy permits
those programs. Process-start failures are counted as infrastructure failures, not
program regressions or false fixes.

The saved comparison is a historical run before that correction. Its false-fix
rates were withdrawn because the old evidence did not distinguish all infrastructure
failures. Original values are preserved under its audit section. The successful
100-run demo and measured calls remain historical evidence; neither implies that
future native execution is available on this host.

### Super repair response budget

The single paid `deadlock_001` attempt exhausted its 4,096-token output cap on
reasoning and returned no final edit JSON. Super repair requests (including smoke)
now explicitly send `chat_template_kwargs: {"enable_thinking": false}` while
keeping the existing output cap. This control is documented in
[NVIDIA's Super serving example](https://docs.nvidia.com/dynamo/dev/recipes/nemotron-3-super#smoke-test).
It is scoped to the exact Super model and repair phase; other models retain their
existing settings. Disabling reasoning may affect repair quality, which must still
be measured by compilation and execution.

Reports now include requested thinking mode, output cap, reported reasoning-token
count, and an actionable truncation hint. Incomplete answers remain rejected with
no automatic retry. The fixture still requires 100 verification runs. Offline HTTP
tests cover the request and failure handling. A subsequently authorized single live
Super request honored the setting, returned valid edits with zero reasoning tokens,
and its candidate passed the full 100-run fixture campaign. The candidate changes
simultaneous-locking semantics; see the measured result and review limitation in
[the live validation report](reports/patch-quality/paid-super-direct-100/REPORT.md).
No additional paid call was made during the earlier offline debugging step.

### Bounded three-model benchmark

Model Lab now applies a 2,048-output-token cap to each selected model, one request per model, zero retries and no escalation. Selecting Nano, Super and Ultra gives a combined output cap of 6,144 tokens. The provider rejects input message content above 12,000 UTF-8 bytes before sending a completion request; this is an input-size guard, not a tokenizer count. Actual billed input/output tokens are recorded from provider usage. Reasoning tokens are a subset of output usage, not added twice. Super repair requests disable thinking; other models retain their provider defaults.

Technical metrics include input/output/reasoning tokens, output-budget utilization, effective output token rate (including request and catalog overhead), end-to-end time, baseline time/failures, accepted patches, changed lines, candidate build, verification time, deadlocks/races/crashes, infrastructure failures and sanitizer status. Combined metrics aggregate independent attempts; they do not execute an ensemble or establish a statistical model ranking. Missing usage and cost stay unknown, with explicitly named known subtotals in JSON exports. Verification rates are weighted by executed runs and show how many models reached verification.

`deadlock_001` retains its full 100-run verification for each accepted patch. Tests remain remote-only. Run `python scripts/push_sandbox.py` to upload the current changes and validate them in Nebius before live benchmarking.


## Final integration and evaluation gate

See [FINAL_INTEGRATION.md](FINAL_INTEGRATION.md) for the adaptive pipeline, fixture invariants, remote test evidence, bounded spending plan, and judge demo. The final benchmark reports are deliberately `not_run` until an explicit live run. All fixture execution stays in Nebius Sandbox. Start the dashboard with `Start-Dashboard.ps1`; model runs are launched only by an explicit action.
