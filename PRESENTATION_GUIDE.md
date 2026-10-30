# AgentKernel — Presentation Guide

**Project:** AgentKernel / Concurrency Bug Hunter  
**Purpose:** Your speaking notes and technical reference while presenting.  
**Evidence checked:** 30 October 2026. Recorded runs keep their original dates.  
**Best positioning:** A coding agent that proposes concurrency repairs and independently tests whether they deserve to be accepted.

---

## 1. Start with this short pitch

> AgentKernel helps developers repair concurrency bugs in C and C++ code. NVIDIA Nemotron proposes a patch through Nebius Token Factory. Then an independent verifier builds and tests that patch in Nebius Sandbox. We accept it only after the original tests, 100 stress executions, semantic checks, and three ThreadSanitizer executions pass. Every attempt keeps its patch, token usage, cost, latency and execution evidence.

**Sentence to remember:** “The model proposes; execution decides whether we accept the repair.”

## 2. What problem are we solving?

Concurrent programs can behave differently depending on how threads are scheduled. A program working once does not mean that its synchronization is correct.

| Term | Simple explanation | Example |
| --- | --- | --- |
| Thread | One path of work running alongside others | Several workers reserving stock |
| Deadlock | Threads wait for each other and cannot proceed | Worker A holds lock 1 and waits for lock 2; worker B does the reverse |
| Data race | Conflicting accesses to shared memory lack the required synchronization | One thread writes a counter while another reads it without a lock or suitable atomic access |
| Semantic invariant | A rule that must remain true | Exactly 500 items may be reserved; stock must never go negative |
| False-fix candidate | A proposed repair that fails independent verification | It stops hanging but breaks the required inventory result |

An AI patch can look plausible while missing a reader, weakening an invariant, or deleting useful work. AgentKernel makes those failures visible instead of accepting the model's confidence as evidence.

## 3. What the developer does

1. Connect a public GitHub repository or use a configured workspace example.
2. Provide a repository contract: editable files, protected files, build/run commands, original tests and semantic checks.
3. Select a model or adaptive route and review its source scope and maximum inference charge.
4. Start the repair. The controller captures the input and requests a model-generated change.
5. Inspect the patch and every verification gate.
6. Download the patch and evidence for review. The project does not merge it automatically.

**Important scope:** An arbitrary codebase is not automatically supported just by pasting its URL. It needs a usable build/test contract and appropriate semantic checks.

## 4. Architecture: explain each part in one line

| Component | Responsibility | Where it runs |
| --- | --- | --- |
| Hosted console | Codebases, model selection, cost review, runs and evidence | Private Sites application |
| Persistent queue | Holds requests and the latest workspace snapshot | Hosted D1 database |
| Connection agent | Polls the queue and coordinates work | Developer's computer |
| Repair controller | Enforces source scope, routing, budgets and response contracts | Python backend |
| NVIDIA Nemotron | Generates fresh repair proposals | Nebius Token Factory inference API |
| Sandbox backend | Uploads source and runs target code in isolation | Nebius Sandbox through Contree SDK |
| Verifier | Decides whether all required checks passed | Controller coordinating remote execution |
| ChatGPT plugin | Tools for inspecting codebases/runs and starting an approved request | Private Site MCP interface |

The optional fine-tuned specialist runs inference on the local NVIDIA GPU. **Target C/C++ compilation and execution remain remote.** The UI is hosted on Sites; do not say that the entire application is deployed on Nebius AI Cloud.

The computer and connection agent must remain online for new jobs. The hosted console can display saved results while the agent is offline.

## 5. The cloud adaptive workflow

This describes the **measured cloud experiment**, not every historical route:

```text
Capture original source and protected tests
                  |
        Observe the remote baseline
                  |
        Nemotron Super repair call
                  |
  Validate response -> construct canonical patch
                  |
       Apply in an isolated sandbox
                  |
          Full independent verification
             /                 \
          PASS              Known failure
           |                    |
      Accept and stop     Permitted Ultra fallback
                                |
                         New patch + full verification
                                |
                         Accept or leave unresolved
```

Invalid output can also escalate under the existing bounded policy. Unknown usage, provider interruptions and verifier infrastructure failures stop the route without automatic replay. Confidence alone does not authorize escalation.

**Canonical patch:** The controller's standard diff, constructed from the model's validated edits. Parsing a patch successfully does not mean that it is correct.

### Keep these versions separate

| Version or experiment | Route | What you can claim |
| --- | --- | --- |
| Hosted adaptive v2 | Local fine-tuned specialist → Super → Ultra | Product flow exists; local and hosted usage must be distinguished |
| Measured cloud v3 / `fast` | Super → Ultra | Fresh Token Factory calls and matched comparison results below |
| Candidate reuse experiment | Reuse an identical-input proposal → fresh verifier | Avoided repeated inference on one known case; not new model repair ability |
| Adaptive v4 prototype | New edit contract, conservative router, richer failure evidence, snapshot branching | New code and offline tests; no new live v4 repair-performance result yet |

Do not show a v4 screen or implementation plan and describe the v3 numbers as v4 results.

## 6. Why the verifier is the main product feature

| Gate | What it checks |
| --- | --- |
| Compilation | The changed program actually builds |
| Original tests | Existing required behavior still works |
| 100 stress executions | The candidate survives the configured repeated execution schedules |
| Semantic oracle | Application-specific invariants still hold |
| 3 ThreadSanitizer executions | No data race is reported in the configured instrumented runs |
| Protected-file and hook checks | The candidate has not changed protected files or removed required scheduling hooks |

**All gates are required.** A patch passing 89/100 stress runs is rejected. A patch passing 100/100 stress runs can still fail TSan.

Passing these tests is bounded experimental evidence. It does not prove correctness for every possible thread schedule or guarantee production safety. TSan is primarily a race detector; it is not a general proof of deadlock freedom.

## 7. Your strongest concrete demo story

Use the fresh inventory cloud run:

`reports/cloud-adaptive/20261029T165615Z/`

1. Multiple threads reserve stock while other threads read it.
2. Super generates a new patch through Token Factory.
3. That patch passes original tests, **100/100 stress runs**, and semantics.
4. **All three TSan runs detect a race.** AgentKernel rejects the patch.
5. The route calls Ultra and verifies its new proposal.
6. Ultra's repair passes the required build, original tests, 100 stress runs, semantics and all three TSan runs.

| Actual measurement | Value |
| --- | --- |
| Fresh cloud model calls | 2 |
| Total model tokens, including the failed attempt | 3,348 |
| Hosted inference spend | $0.0028022 |
| Model inference time, combined | 3.32 seconds |
| Candidate verification time, combined | 35.97 seconds |
| End-to-end time | 58.66 seconds |
| Cached proposal / local specialist used | Neither |
| Final outcome | Verified after Ultra fallback |

**Explain the timing:** End-to-end time includes baseline work, setup, transport and controller work as well as model inference and candidate verification. Do not call 58.66 seconds “model latency.”

**Explain `false_fix: true`:** In this route result it records the rejected intermediate Super candidate. The final Ultra candidate passed verification. It is not permission to hide the first failure or claim the final patch failed.

## 8. The fair comparison: know these numbers

Frozen comparison: **8 existing synthetic program designs × 3 routes = 24 jobs**, with **32 real cloud calls**. Total measured hosted inference cost: **$0.0409148**.

| Route | Verified | Calls | Total tokens | Hosted inference cost | Median end to end |
| --- | --- | --- | --- | --- | --- |
| Super-only | 0/8 | 8 | 12,496 | $0.0043578 | 18.38 s |
| Ultra-only | 6/8 | 8 | 13,055 | $0.015955 | 40.78 s |
| Cloud adaptive, Super → Ultra | 6/8 | 16 | 25,743 | $0.020602 | 43.55 s |

Adaptive stopped at Super on **zero** cases. Ultra recovered **six** cases; **two** remained unresolved. There were **zero Ultra calls after an already verified Super result** and no infrastructure-unknown outcomes in this comparison.

### How to explain the result honestly

> “Adaptive recovered six failures of the Super-only pipeline, but it matched Ultra-only's verified count while using more tokens, cost and time. This tells us that always trying Super first is not an efficient policy for this suite. The next prototype improves the cheaper-tier interface and makes model selection depend on calibrated evidence.”

**Do not say:** “Adaptive beats every model,” “we proved statistical superiority,” or “this works on all production codebases.” Eight synthetic designs and one run per arm do not establish those claims.

Some Super failures involved response-format and line-mapping problems. That is a result for the tested pipeline/configuration, not proof that Super cannot repair these bugs with any prompting strategy.

### What a judge can inspect

- Frozen settings and file hashes: `reports/cloud-comparison/20261029T170003Z/protocol.json`
- Results: `reports/cloud-comparison/20261029T170003Z/REPORT.md`
- Independent acceptance audit: `reports/cloud-comparison/20261029T170003Z/audit.json`
- Offline viewer: `reports/cloud-comparison/20261029T170003Z/SCORECARD.html`
- Per-case directories contain model responses, patches and raw verifier evidence.

This cloud comparison used neither reference repairs in prompts nor cached proposals. It did not change prompts, caps, fixtures or routing after seeing outcomes. The cases are existing synthetic designs; do not describe them as guaranteed unseen by development or model pretraining.

## 9. What is new in v4?

Claude's implementation report describes a new opt-in prototype with:

- A plain-text line-block edit format intended to avoid JSON quote-escaping failures.
- Strict source identity, file-scope, line-range and scheduling-hook checks.
- A deterministic router using concurrency features, capacity and development calibration.
- Full failed-candidate evidence for fallback, including patch, compilation, stress, semantics and TSan reports.
- Lossless deduplication of repeated failure records rather than blind truncation.
- Isolated branches of an uploaded sandbox snapshot to avoid unnecessary setup/upload work.

**Current status:** The implementation report records 24 focused offline tests and a 111-test regression selection. These are not live model-success measurements. The report also states that v4's live orchestrator has not been exercised, the execution wiring for the paid pilot is unfinished, and dashboard/MCP integration is not done. Performance targets remain untested.

With no qualifying v4 calibration, the router selects Ultra directly. Do not present that default as a demonstrated accuracy or cost advantage.

Read `ADAPTIVE_V4_IMPLEMENTATION.md` before presenting newer changes; this guide is a dated snapshot, not an automatic status monitor.

## 10. Three-minute presentation sequence

| Time | What to show | What to explain |
| --- | --- | --- |
| 0:00–0:20 | Overview | State the concurrency problem and short pitch |
| 0:20–0:40 | Codebase contract | Show editable source versus protected tests and cost review |
| 0:40–1:25 | Recorded fresh inventory cloud run | Walk through Super's TSan failure and Ultra's verified recovery |
| 1:25–1:50 | Patch and metrics | Explain two calls, 3,348 tokens, cost and separate latency phases |
| 1:50–2:20 | Frozen comparison scorecard | Show all three arms, including where adaptive is more expensive |
| 2:20–2:40 | Route/code architecture | Explain mandatory verification, bounded escalation and evidence preservation |
| 2:40–3:00 | Conclusion | State what works, what remains unresolved, and why calibrated routing is next |

Label saved runs as **recorded real execution evidence**. Do not describe opening a saved result as starting a new live inference call. If you run a fresh repair during a presentation, review its cost first and allow for actual latency.

## 11. Likely judging questions

### “What makes this different from asking an LLM to fix code?”

The model is only the proposal generator. AgentKernel controls the editable scope, constructs the patch, independently runs the required checks, rejects observed failures, and preserves the evidence and actual resource usage.

### “Why did you choose Nebius?”

Token Factory provides hosted Nemotron inference behind the controller. Nebius Sandbox provides the isolated Linux environment for compilers, tests and sanitizers. The same controller can record model usage and execution outcomes together.

### “Does adaptive reduce cost?”

That is a design objective, not the result of the latest eight-case comparison. It cost more than Ultra-only there. The observed failure motivates fixing the cheaper-tier contract and calibrating when to skip that tier.

### “Why not always use Ultra?”

Ultra-only is a strong baseline and was more efficient in this suite. Adaptive routing earns its complexity only if a cheaper tier solves enough cases to offset its failures and overhead. We measure that instead of assuming it.

### “Is the small model bad?”

The measured Super pipeline returned several invalid or misaligned edits. That includes interface failures. We cannot separate general model ability from every aspect of this prompting/configuration using this small comparison alone.

### “Does a verified result guarantee the bug is gone?”

No. It means all configured independent checks passed. Broader schedules, workloads and production invariants still require evaluation.

### “Are the low dollar figures the total infrastructure cost?”

No. They are recorded hosted inference charges. Sandbox beta was confirmed free for the development account. Local electricity, engineering time and other hosting costs were not measured as an all-in dollar total.

### “How do you prevent test leakage?”

Protect original tests and semantic oracles from modification. Keep reference repairs outside prompts and example retrieval. Freeze the evaluation protocol. Reference repairs establish that solutions exist; they do not count as model successes. Future v4 evaluation needs new held-out designs because the current cases are development-seen now.

### “What happens if the network fails after a paid call?”

The outcome stays unknown when usage or completion is uncertain. Its budget reservation remains held. The controller does not automatically repeat the request or count it as a success.

### “Can I use it from ChatGPT?”

The private Site exposes eight tools for status, codebases, results, repair preparation, approved start, repository connection and queued cancellation. A paid repair review is time-limited and single use. The plugin's installed state was checked; successful use still requires a healthy authenticated connection. The workspace agent must be online for new work.

### “What is not finished?”

Production-scale validation, private GitHub authentication, automatic merging, fully unattended cloud hosting of the workspace agent, and v4 live evaluation/integration. Submission and judge-access requirements must be checked separately.

## 12. Before presenting

- Open the console and confirm the agent heartbeat if you intend to request new work.
- Keep the inventory run, patch, verifier evidence and scorecard ready.
- Know which route you are showing: deployed v2, measured cloud v3, or unvalidated v4 prototype.
- Keep credentials, `.env` files and service tokens off screen.
- Ensure judges can access the provided demo or test build; the existing hosted Site is private.
- Confirm any public repository/video links separately. A local archive is not a Devpost submission.
- If a question goes beyond the measurements, say what is unknown rather than inventing a result.

## Closing line

> AgentKernel makes concurrency repair measurable: fresh model proposals, independent cloud execution, and evidence for accepting or rejecting each patch. Our next milestone is proving that a calibrated adaptive policy can retain repair quality with less cost and latency.
