# AgentKernel demo video: two-presenter script, v4 after fixes (target 2:50)

**Characters**
- **MEERA**: an on-call C engineer with a concurrency bug. Also the skeptic, who asks what a judge would ask.
- **HARI**: the builder, who drives the screen.

Run time is about 2:50 at ~150 wpm (about 420 spoken words). If a take runs past 2:55, cut in this order:
1. MEERA's "It debugged itself."
2. The "Why not the cheaper model?" exchange.
3. The final "Built on?" question, keeping HARI's answer.

## The story in one line

On eight concurrency bugs, once we fixed two bugs in our own code, **v4 verified every program that Nemotron Ultra alone verified, plus one that no earlier route solved, and it rescued a failed patch using its own verifier evidence.**

## Judge requirements this covers

Sources: Devpost "Final stretch" checklist, "Will It Ship?" recording summary, "Here's how judging works", "How to build a winning project".

| Judges asked for | Where |
| --- | --- |
| The app actually working, in a video under 3 minutes | 0:15 shows the verified audit_3 run in the local dashboard |
| Nebius + NVIDIA named **in audio** | 0:25 and 2:35 |
| The aha moment within 30 seconds of the demo | The audit_3 row (rejected, rejected, rejected, **verified**) is on screen by 0:30 |
| Which model does what | 0:50: Ultra repairs, the router decides, the sandbox verifies |
| Pitch: problem, who it's for, solution | Cold open, then 2:30 |
| Limitations published as rigor | 2:05: our two bugs (the amber cells) and rendezvous_3 |
| Coding & Agentic track: plan, write, test, iterate | 1:30: the aggregate_3 rescue |
| Four equally weighted criteria | Idea: cold open. Technology: 0:45–1:30. Design: the matrix and dashboard. Impact: 2:30. |

## Screens to have ready

1. **Evidence page, case matrix**, the screen in this script: https://claude.ai/artifact/3d6q9bXJdDsMv4NsgwQ1VF. Share it publicly first. The same table is in the local dashboard at `http://127.0.0.1:8766/#v4` if you prefer to film only local screens.
2. **Model Lab** (`.\Start-Dashboard.ps1`): the saved run **audit_3 / Adaptive v4** (`8792a943…`), status VERIFIED.
3. **Evidence page → aggregate_3 → "Post-fix re-check" tab**: the 100-run bar.
4. **GitHub**: https://github.com/hariharaans2025-ctrl/agentkernel (README + MIT).
5. Nothing secret on screen: no `.env`, no terminals with keys, no Sites token prompt.

> All runs shown are **recorded live runs from 30 October**. Say "a run from today", not "running now".

## Script

### 0:00–0:15 · Cold open: the problem

*Screen: the evidence page header, "A patch is a proposal. Execution decides."*

**MEERA:** My service deadlocked at 2 a.m. An AI patch made the deadlock disappear, and quietly removed the lock that protected our audit counter.

**HARI:** That's the trap. AI concurrency fixes *look* right. AgentKernel makes them prove it.

### 0:15–0:45 · The aha: audit_3

*Screen: Model Lab, audit_3 / Adaptive v4, VERIFIED. Then cut to the case matrix and point along the audit_3 row.*

**HARI:** Here's that exact bug, from a run today. **NVIDIA Nemotron Ultra, through Nebius Token Factory,** wrote the patch. Then **Nebius Sandbox** tried to break it:
- a fresh build
- the original tests
- **100 stress runs**
- a semantic check
- **three ThreadSanitizer runs**

Verified, for about a tenth of a cent.

**HARI:** Look at this row. Every earlier route, including Ultra on its own, was **rejected**. v4 verified it.

**MEERA:** So you don't trust the model.

**HARI:** We trust execution. The model proposes; the sandbox decides.

### 0:45–1:30 · How v4 works (Technological Implementation)

*Screen: the evidence page, "The v4 route" diagram.*

**MEERA:** What changed in v4?

**HARI:** Three things.
1. **A deterministic router.** Cheaper models only go first once data shows they pay off. Right now, that's **Nemotron Ultra**.
2. **Plain-text line edits instead of JSON.** That kept quotes in C code from breaking the reply.
3. **Every candidate must clear every gate.** There is no majority vote and no self-reported success.

**MEERA:** Why not the cheaper model?

**HARI:** We measured it. Nemotron Super scored zero of eight under our old JSON format, mostly because an unescaped quote cut its answers short. So we fixed the format before judging the model.

### 1:30–2:05 · The agent iterates (Coding & Agentic)

*Screen: evidence page → aggregate_3 → Post-fix re-check. Point at the red cells, then the full bar.*

**MEERA:** And when the first patch is wrong?

**HARI:** This one passed 92 of 100 stress runs; those red cells are failures. ThreadSanitizer also caught a race. **Rejected.**

**HARI:** So Ultra gets *one* more call, carrying the failed patch and the exact verifier evidence. Second patch: **100 of 100, three of three TSan. Verified.**

**MEERA:** It debugged itself.

**HARI:** Plan, write, test, iterate, with no human in the loop.

### 2:05–2:30 · After the fixes: the honest scorecard

*Screen: the case matrix. Point at the "v4 after fixes" column, the two amber cells, then rendezvous_3.*

**MEERA:** So is v4 better than Ultra alone?

**HARI:** Here's the full picture.
- Our first frozen run scored five of eight. These two amber misses were **bugs in our own code**: a parser rule and an input limit.
- We fixed both and re-ran just those two programs. **Both verified.**
- So across the two runs, v4 verified every program Ultra verified, **plus audit_3**: seven of eight.
- rendezvous_3 is still unsolved by every route.

These are eight small development programs, not a statistical claim.

### 2:30–2:50 · Who it's for, and the close (Potential Impact)

*Screen: the GitHub README, then end on the evidence page header.*

**MEERA:** Who needs this?

**HARI:** Any team reviewing AI-written C and C++ concurrency code, where "it worked once" means nothing. Every repair ships with its patch, its cost, and proof it survived.

**MEERA:** Built on?

**HARI:** **Nebius Token Factory, Nebius Sandbox and NVIDIA Nemotron**, open source under MIT. AgentKernel: the model proposes, execution decides.

## Numbers you'll say, and their source

| Spoken | Evidence |
| --- | --- |
| audit_3 verified: 100 stress, 3 TSan, ~$0.0014 | Dashboard run `8792a943…`; frozen pilot `20261030T120841Z` |
| Every earlier route rejected audit_3 | v3 comparison `20261029T170003Z` |
| 92/100 + TSan race → 100/100, 3/3 | aggregate_3 re-check `20261030T122329Z` |
| Super 0/8 under the old JSON format | v3 comparison |
| Frozen pilot 5/8; two misses were our bugs; re-check 2/2 | Pilots `20261030T120841Z` + `20261030T122329Z` |
| "Seven of eight, across the two runs" | 5 from the pilot + 2 from the re-check. Say "across the two runs"; it is not one combined run. |
| Ultra alone: 6/8 | v3 comparison |

## Recording checklist

- [ ] The audio clearly says "NVIDIA Nemotron Ultra", "Nebius Token Factory" and "Nebius Sandbox".
- [ ] The audit_3 matrix row is visible by **0:30**.
- [ ] Say "seven of eight **across the two runs**", never "v4 scored 7/8".
- [ ] Saved runs are "from today", not "running now".
- [ ] No keys, `.env`, tokens or inbox on screen.
- [ ] The final cut is under **3:00**.
- [ ] Upload to YouTube as **Public** and check it while signed out.
- [ ] **Upload early.** Submissions lock at **10:00 AM PT / 22:30 IST**; nothing may change after that.

## Devpost items this video depends on

- **Demo URL:** the shared evidence page plus the repo README. Note that live repairs run from the local dashboard on the user's own Nebius keys.
- **Built With:** Nebius Token Factory, Nebius Sandbox (Contree SDK), NVIDIA Nemotron Ultra and Super, Python, Clang/ThreadSanitizer.
- **Feedback** (required): include the JSON-schema quote problem you hit with Super. That's specific, actionable feedback.
- **Prior work:** the earliest repo commits date from 14 September 2026. Confirm they're within the hackathon period, or disclose them.
