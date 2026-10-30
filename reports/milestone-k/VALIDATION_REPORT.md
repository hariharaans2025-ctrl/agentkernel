# Milestone K — real inference and observability validation

**September 20 follow-up:** the LangSmith connectivity blocker below has been
resolved. The US endpoint was correct; the private workspace ID was wrong.
The API returned workspace `32214fa7-08df-4fdc-9588-3972af0de5b9`, matching the user's
dashboard URL, and the private configuration was corrected. The dashboard URL's ID
was confirmed as a workspace ID by the API; it is distinct from the returned
organization ID.

Successful authentication exposed a missing `parent_run_id` in child-span PATCH
requests. The adapter now preserves parent identity on updates and retries only
404 readbacks briefly while accepted traces become available (three retries with
0.5/1/2-second waits, within the existing flush deadline). Three focused offline
observability checks passed after these fixes.

A live **metadata-only** check confirmed two server-visible spans with the correct
parent relationship and submitted one `ultra_used=false` feedback item. Root:
`9c5ae6a6-5b75-4304-85e0-192f8ebed594`, name `LangSmithConnectivityVerified`, project
`concurrency-bug-hunter`. [Confirmed result](langsmith-confirmed.json).
No Nebius inference, C execution, original job replay or benchmark was performed
in this follow-up. The unresolved repair outcome and historical failures below
remain unchanged; the full fixture trace has not been revalidated live.

Validation session: September 19–20, 2026. Existing AgentKernel repository extended;
the original runtime, mock provider, local backend, compiler, verifier and fixtures
remain in place.

**Outcome: the one authorized real end-to-end attempt conclusively failed.**
Real baseline execution and Nano triage worked. Super and Ultra returned repair
proposals, but every diff was rejected before application. No repaired program was
compiled or execution-verified. LangSmith returned HTTP 403. Live testing stopped
after this attempt; no full benchmark was run.

## A. Offline validation

**173 passed, 7 deselected, 0 failed in 58.19 seconds.** The 154 earlier offline
tests still pass alongside 19 new checks. Four native integration tests and three
new live-account tests are excluded by default. No live tests were selected as part
of this suite.

The new checks cover transient retries, permanent failures without escalation,
catalog handling, nullable usage, usage retained with unusable completions, bounded
JSON correction, private configuration loading, safe validation diagnostics,
LangSmith hierarchy/readback/feedback/redaction, and nonfatal trace delivery errors.
A full offline flow exercises real Python subprocesses with mock model and tracing
transports, including failed Super verification followed by Ultra; it does not
represent real C/model/remote-LangSmith validation.

Command used from the enclosing workspace, with a fresh temporary directory:

```powershell
$env:TEMP = (Resolve-Path work/test-temp).Path
$env:TMP = $env:TEMP
.\outputs\agentkernel\.venv\Scripts\python.exe -m pytest -q outputs/agentkernel/tests --basetemp=work/pytest-k-final-all -p no:cacheprovider --tb=short
```

## B. Token Factory catalog

Live authentication and catalog discovery succeeded. The account returned these
exact configured IDs; capitalization matters and no model was silently substituted.

| Tier | Available model ID |
|---|---|
| Nano | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` |
| Super | `nvidia/nemotron-3-super-120b-a12b` |
| Ultra | `nvidia/Nemotron-3-Ultra-550b-a55b` |

[Configured catalog result](catalog-configured.json). The earlier `catalog.json`
records the initial discovery before the blank model settings were populated.

## C. Tiny real Nano smoke

**Passed:** real inference returned JSON validated against the supplied counts and
representative run ID. The supplied 100-run/91-pass/9-timeout example was synthetic;
this smoke did not execute a program.

| Model | Input tokens | Output tokens | Measured latency | Transport retries | Finish |
|---|---:|---:|---:|---:|---|
| Nano (exact ID above) | 275 | 339 | 4,870.83 ms | 0 | stop |

Request ID: `08b82a8399d6d58079ac40575c518980`. Cost is unknown (`null`).
LangSmith delivery failed with HTTP 403.
[JSON result](nano-smoke.json), [JSONL telemetry](nano-smoke.jsonl).

## D. Small real Super smoke

**Failed:** baseline compilation succeeded and all three real runs were classified
`POSSIBLE_DEADLOCK`, with opposite lock waits and timeouts. Nano triage passed.
The first Super response failed the repair contract. Its one correction attempt
returned an unusable API response (`malformed_response`). No patch was applied.

| Call | Input tokens | Output tokens | Measured latency | Transport retries | Finish |
|---|---:|---:|---:|---:|---|
| Nano triage | 692 | 634 | 8,170.52 ms | 0 | stop |
| Super initial | 1,343 | 2,160 | 13,008.00 ms | 0 | stop |
| Super correction | unknown | unknown | 22,209.46 ms | 0 | unknown |

The historical correction response did not retain usage or a finish reason in its
report. Those values were not reconstructed or invented. Before the end-to-end
attempt, failure handling was improved to preserve valid usage from unusable
completions, safe field/type diagnostics were added, and the repair prompt was
given the explicit JSON schema. Focused offline checks passed before proceeding.
The separate Super smoke was not repeated.

All model IDs are the exact tier IDs in B; all costs are `null`. Request IDs and
complete measured fields are in [the JSON result](super-smoke.json) and
[JSONL telemetry](super-smoke.jsonl). LangSmith again returned HTTP 403.

## E. One real end-to-end fixture

Fixture: `benchmarks/deadlock_001/main.c`. Real LLVM-MinGW/Clang compilation with
pthreads and static linking succeeded. All **3 baseline runs timed out with
`POSSIBLE_DEADLOCK`**; the deterministic fingerprint was `cyclic_lock_wait`.
There were no baseline infrastructure failures or host-policy blocks in this run.

Route: **Nano → Super → Super → Ultra**. Nano triage passed. Ultra was reached by
the existing policy after two rejected Super repairs; it was not forced. Prior
proposals and patch rejection evidence were carried into later attempts.

| Attempt | Input tokens | Output tokens | Measured latency | Transport retries | Result |
|---|---:|---:|---:|---:|---|
| Nano | 713 | 460 | 5,925.78 ms | 0 | Triage validated |
| Super 1 | 1,669 | 2,852 | 16,669.84 ms | 0 | Diff rejected: File has no hunks |
| Super 2 | 3,163 | 2,485 | 11,050.93 ms | 0 | Diff rejected: Patch context does not match original source |
| Ultra | 3,902 | 2,978 | 9,007.01 ms | 0 | Diff rejected: Patch context does not match original source |

All four API responses reported `finish_reason=stop`; exact model and request IDs
are recorded per attempt in the report. Total returned usage for this job:
**9,447 input tokens and 8,775 output tokens**. Total measured inference latency:
**42,653.56 ms** including catalog checks. Local compilation/campaign execution:
**7,266.40 ms**. Job elapsed time before trace flushing: **49,977.80 ms**.
Cost remains `null` because authoritative pricing was not configured.

Three repair JSON proposals were parsed; **zero diffs were accepted**. The safe
applier did not rewrite hunks or use fuzzy matching. **Zero post-patch verification
runs occurred.** Execution failures after repair and verification pass rate are
therefore **not measured**, rather than zero failures or a passing result. The
original fixture is unchanged. Final status: `unresolved`; stop reason:
`ultra_failed`; the four-attempt budget was exhausted.

Static review of the rejected proposals also shows a remaining logic issue: each
keeps the two-party barrier while holding mutex A, preventing the second worker
from reaching that barrier. This is source inspection, not a result from executing
any proposed patch. Model claims that this change eliminates deadlock are unverified.

Artifacts: [full job result and rejected diffs](end-to-end.json),
[JSONL telemetry](end-to-end.jsonl), [approved transfer scope](payload-review.json).

The end-to-end command used the existing fixture configuration (3 baseline runs,
100 configured verification runs) and default four inference attempts:

```powershell
$compilerK = (Resolve-Path work/toolchain/llvm-mingw-20260908-ucrt-x86_64/bin/clang.exe).Path
.\outputs\agentkernel\.venv\Scripts\python.exe -m agentkernel.cli concurrency run outputs/agentkernel/benchmarks/deadlock_001 --env-file outputs/agentkernel/.env --inference-mode real --compiler $compilerK --static --json-output outputs/agentkernel/reports/milestone-k/end-to-end.json --telemetry-jsonl outputs/agentkernel/reports/milestone-k/end-to-end.jsonl
```

## F. LangSmith validation

**Live tracing did not work.** Project: `concurrency-bug-hunter`. Endpoint used:
`https://api.smith.langchain.com`. Requests returned `langsmith_http_403`;
the end-to-end report records **0 submitted spans, 0 observed spans and 0 submitted
feedback items**. Root ID allocated locally:
`87a9597e-f6e1-4cd2-8e96-551c1b16319b`. This is not a confirmed remote trace link.
A separate metadata-only recheck after the user's configuration check also failed:
[probe result](langsmith-probe.json).

The implemented hierarchy is a job root with baseline compile/stress, fingerprint,
Nano/Super, patch and verification spans as each stage executes; Ultra has its own
scope containing diagnosis/application/verification. HTTP-mocked offline tests
confirmed parent relationships, server readback logic and deterministic feedback.
**No hierarchy was observed in the live LangSmith account.** JSONL telemetry remains
available independently. There were no authentication retries within a failed flush.

## G. Remaining blockers and boundaries

1. **Repair quality and diff formatting:** no accepted real repair was produced.
   Further work requires better exact-source diff generation and a candidate that
   handles the barrier correctly. The user-requested stop condition prevents more
   live repair attempts in this milestone.
2. **LangSmith access:** HTTP 403 remains unresolved. The private key, endpoint
   region, workspace selection and write permissions need to be checked; the HTTP
   status alone does not establish which setting is wrong.
3. **Platform scope:** native Windows ThreadSanitizer remains unavailable. Existing
   WinError 4551 handling remains nonretryable; no host security setting was changed.
4. **Cost and quality conclusions:** pricing is unavailable; no cost savings,
   adaptive superiority, Ultra-equivalent quality or benchmark superiority is
   established by this single unresolved fixture.

The secret audit checked repository source, tests, reports and staged blobs against
configured secret values and common credential formats. It found no matches;
`.env` is ignored and untracked, and the fixture hash matches the approved source.
[Audit result and scope limitations](secret-audit.json). API keys are not included
in the report, inference payload contents, telemetry or trace metadata.

Changes and artifacts are local; no commit or push was performed in this milestone.
Tavily remains disabled. No full benchmark, llm-d, Toloka, learned routing or
dashboard work was started.

> Concurrency Bug Hunter does not ask an LLM whether its fix is correct.
> It repeatedly tries to make the fix fail.
