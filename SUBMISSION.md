# AgentKernel — Concurrency Bug Hunter

## Submission fields

**Recommended track:** Coding and Agentic Engineering.

**Tagline:** Model-generated concurrency repairs, tested before you trust them.

**Working application:** https://agentkernel-control.abuzzleaf32.chatgpt.site/ — owner-private. This URL alone does not provide judge access. Arrange authorized judge access or supply the runnable test build; never disclose the owner's Nebius API key or private Site service token.

**Public repository:** publication pending. The previously supplied `hariharaans2025-ctrl/agentkernel` URL returned 404 during the submission check. Publish the sanitized source archive under a public repository and verify its README and MIT license are visible before copying its URL into Devpost.

**Public video:** recording and YouTube publication pending. Use DEMO_SCRIPT.md; target 2 minutes 50 seconds.

## Inspiration

Concurrency fixes are difficult to assess by reading a patch. A model can remove the visible deadlock while introducing a data race, breaking a shared-state invariant, or skipping useful work. AgentKernel treats a repair proposal as the start of an experiment: build it, run the original tests, stress it, check its semantics, and inspect ThreadSanitizer evidence.

## What it does

AgentKernel connects a C/C++ codebase through an explicit contract: editable source files, protected support files, build commands, original tests and required verification. Users select a model or a bounded adaptive route, review the maximum inference charge, and start a repair. The console records the canonical patch, response, tokens, latency, cost and each verification gate. Results and patches can be exported for review.

The adaptive v2 route starts with a locally fine-tuned specialist, then uses NVIDIA Nemotron Super and Ultra through Nebius Token Factory when the prior attempt is rejected or invalid. It stops at the first fully verified candidate. An infrastructure failure or unknown outcome stops the route. Single-model Nano, Super, Ultra and Qwen repair routes are also available. The historical Nano-triage benchmark is a separate frozen experiment, not the deployed v2 route.

The private ChatGPT plugin exposes eight tools to inspect codebases and runs, prepare a repair review, start an approved request, connect a public repository, and cancel a queued request. Approval reviews expire and are single use. The workspace agent must be running for new jobs.

## How it works and where Nebius is used

The Python controller calls the real Nebius Token Factory chat-completions API with configured NVIDIA Nemotron model IDs. Contree SDK provides disposable Nebius Sandbox workspaces using `agentkernel-clang:20261003122908`. All target C/C++ compilation and execution happen in that remote environment. The optional specialist performs model inference on the local NVIDIA GPU; the React console and its persistent queue are hosted on Sites, outside Nebius.

The model proposes source edits. AgentKernel constructs and applies a canonical patch to a disposable source copy, preserves protected files, and requires compilation, original tests, 100 stress executions, semantic checks and three TSan executions. The controller rejects failures and records interrupted calls separately without automatic replay. API credentials stay in the private workspace environment.

## Measured results

The final matched specialist pilot used two frozen synthetic test programs excluded from training and checkpoint selection:

| Route | Verified repairs | Tokens including failed attempts | Hosted inference cost |
| --- | --- | --- | --- |
| Base specialist | 0 / 2 | 1,075 | $0 |
| Fine-tuned specialist | 1 / 2 | 1,041 | $0 |
| Adaptive v2 | 1 / 2 | 13,304 | $0.0129878 |

The barrier deadlock remained unresolved. This comparison does not establish that adaptive routing is cheaper or better: it used more tokens without increasing the verified count on these two programs. Local electricity was not measured. Sandbox beta was confirmed free for the development account.

A separate website-triggered inventory repair passed every gate using one fine-tuned model call, 502 tokens, zero hosted fallback calls, and 91.61 seconds end to end. This demonstrates the product flow; it is not an additional unseen benchmark result.

The account-independent validation snapshot recorded 431 passing tests, no failures and three excluded live-account tests in Nebius Sandbox. The ChatGPT protocol and approval boundary have six passing tests. Type checking and the production frontend build passed. Refer to the release manifest for dates and scope rather than treating these checks as a fresh paid model benchmark.

### Adaptive v4 (30 October, live Nemotron Ultra + Nebius Sandbox)

v4 replaces the fixed Super→Ultra ladder. That ladder was measured on 29 October: it reached the same 6/8 as Ultra-only at 29% higher cost, and Super verified 0/8.

**The cause of Super's 0/8.** Super's failures were traced to a reply-format defect: unescaped quotes under a strict JSON grammar. v4 therefore has three parts:

- a plain-text line-block reply contract
- a deterministic router, which sends cases to Ultra until cheaper tiers are calibrated
- one **evidence-directed correction**, made only when execution rejects a candidate: Ultra receives the failed patch plus its stress, semantics and TSan evidence

**Live results.** These cover eight development-seen synthetic cases; full detail is in `ADAPTIVE_V4_LIVE.md`.

| Run | Result |
| --- | --- |
| Frozen pilot | 5/8 verified, vs 6/8 for Ultra-only. v4 solved audit_3, which no v3 route solved. It lost two cases to integration defects, now fixed. |
| Post-fix check on those two cases | 2/2 verified. On aggregate_3, a rejected Ultra candidate (92/100 stress, TSan failed) was **recovered by the evidence-directed correction**: 100/100 stress and 3/3 TSan. |
| Local dashboard (Model Lab) | audit_3 verified, $0.0014. |

Total new inference: 15 calls, $0.0295. The full remote test suite passed in Nebius Sandbox.

**Limits.** These results are not unseen or statistical evidence. rendezvous_3 remains unsolved by every route.

## Challenges and lessons

Small response caps can truncate repairs. A patch can appear successful under stress while failing a semantic oracle or TSan. The useful output is therefore a measured verification outcome, including failures, rather than model confidence. Unknown paid-call outcomes retain budget reservations, and reference or manually written repairs never count as model successes.

## Improvements during the build

The project evolved from a rule-based routing skeleton into repository onboarding, strict patch contracts, remote verification, preserved comparisons, token/cost limits, a fine-tuned specialist, the hosted console, and a private ChatGPT tool interface. Evidence dates show development during September and October 2026. If any earlier component predates the hackathon submission period, disclose that component and its exact changes in the final entry; do not invent a prior-history claim.

## Feedback on Nebius and NVIDIA tooling

Token Factory's compatible inference interface made it practical to compare several Nemotron tiers behind the same controller. Explicit model availability and pricing checks helped bound calls. Sandbox snapshots provided an isolated Linux compiler and sanitizer environment for Windows development. Large uploads were unreliable on the development mobile connection; splitting validation uploads into batches allowed the full test suite to complete. Clearer guidance on model-specific response/thinking settings, usage after interrupted calls, and Sandbox beta billing would improve reproducibility.

## Limitations and next steps

The evaluated programs are small synthetic cases. Private GitHub authentication, automatic merging, and fully unattended cloud hosting of the workspace agent are not implemented. The optional trained specialist needs compatible CUDA hardware and separately restored base weights. Production rollout would need broader repository evaluation, maintained judge/tester access, and application-specific semantic contracts. Verification is mandatory and does not prove absence of unobserved bugs.

## Submission requirements checked 29 October 2026

The official event requires a working application with an NVIDIA open-source model on Nebius, a selected track, project description, accessible demo/test build, public licensed source repository, public YouTube demo under three minutes, and platform feedback. Judges need free, unrestricted testing access through the judging period. Submission deadline: **30 October 2026, 10:30 p.m. IST**. See https://nebiusglobalaihackathon.devpost.com/ and https://nebiusglobalaihackathon.devpost.com/rules.

**Pending external deliverables:** publish source, record/publish the video, establish judge access, complete team/eligibility fields, and review/submit the Devpost entry. The archives do not constitute an entry and no Devpost submission has been made.
