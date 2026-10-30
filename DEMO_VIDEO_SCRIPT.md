# AgentKernel demo video: two-presenter script (target 2:50)

**Characters**
- **MEERA**: an on-call C engineer with a concurrency bug. Also the skeptic, who asks the questions a judge would ask.
- **HARI**: the builder, who drives the screen.

Run time is about 2:50 at a brisk pace (about 430 spoken words, ~150 wpm). If a take runs past 2:55, cut in this order:
1. MEERA's "It debugged itself from the evidence."
2. The "Why not just use the cheaper model?" exchange.
3. The final "Built on?" question, keeping HARI's answer.

Record the screen and the voices separately if that is easier. Captions are recommended.

## What this script is built to satisfy

Sources:
- the Devpost update "Final stretch — submission checklist"
- the recording "Will It Ship? Inside the Judging Criteria" and its written summary
- "Here's how judging works"
- "How to build a winning project"

| Judges asked for | Where the script delivers it |
| --- | --- |
| A video under 3 minutes, public on YouTube, showing the app actually working | 0:15–0:45 shows a real verified run in the local dashboard |
| Nebius + NVIDIA usage explained **with audio**, not in passing | Spoken at 0:30 and 1:00: "Nemotron Ultra on Nebius Token Factory proposes; Nebius Sandbox executes" |
| The aha moment within 30 seconds of the demo | The verified run is on screen by 0:30 |
| Show which model is doing what | 1:00 names Ultra as the repairer, the router, and the evidence correction |
| A pitch, not a tutorial: problem, who it's for, solution working | The cold open (problem), 0:15 (solution), 2:30 (who and why) |
| Published limitations read as rigor | 2:05 shows the honest scorecard, including our own losses |
| One thing done well beats a big stack | Everything serves one story: an AI patch must prove itself |
| Coding & Agentic track: plan, write, test, iterate | 1:30 shows the agent iterating on real verifier evidence |
| The four equally weighted criteria: Technology, Design, Impact, Idea | Technology 0:45–1:30; Design: the dashboard and evidence page; Impact 2:30; Idea in the cold open |

## Screens to have open before recording

1. **Model Lab**: run `.\Start-Dashboard.ps1` → `http://127.0.0.1:8766`. Select the saved run **audit_3 / ADAPTIVE_V4** (`8792a943…`, verified today).
2. **Evidence page**: https://claude.ai/artifact/3d6q9bXJdDsMv4NsgwQ1VF (share it publicly first). Keep the `#aggregate_3` and `#audit_3` views ready.
3. **GitHub repo**: https://github.com/hariharaans2025-ctrl/agentkernel, showing the README and the MIT badge.
4. Close `.env`, terminals that show keys, and the Sites token prompt. Nothing secret on screen.

> The audit_3 run is a **recorded live run from 30 October**. Say "here's a run from today" rather than pretending to click it live. A fresh live run takes about 40 seconds plus your review of its cost ceiling. Only do one if you budget for it: it spends up to 2 Ultra calls, and your delegated 16-call pilot has 1 call left.

## Script

### 0:00–0:15 · Cold open: the problem (Quality of the Idea)

*Screen: the evidence page header, "A patch is a proposal. Execution decides."*

**MEERA:** My service deadlocked at 2 a.m. An AI tool gave me a patch, and the deadlock was gone. So was the lock protecting our audit counter.

**HARI:** That's the trap. AI concurrency fixes *look* right. AgentKernel makes them prove it.

### 0:15–0:45 · The aha: a verified repair (show it working)

*Screen: Model Lab → audit_3 → Adaptive v4 → the result row reads VERIFIED. Point at the stress count and TSan.*

**HARI:** Here's a run from today on a real bug: commits race with an audit helper that takes the same lock.

**HARI:** **NVIDIA Nemotron Ultra, through Nebius Token Factory,** wrote this patch. Then **Nebius Sandbox** tried to break it:
- a fresh build
- the original tests
- **100 stress runs**
- a semantic check
- **three ThreadSanitizer runs**

All passed. Cost: about a tenth of a cent.

**MEERA:** So you don't trust the model.

**HARI:** We trust execution. The model proposes. The sandbox decides.

### 0:45–1:30 · How it works (Technological Implementation)

*Screen: the evidence page → "The v4 route" diagram. Move along it as HARI speaks.*

**MEERA:** Walk me through it.

**HARI:** Four steps.
1. **The developer declares a contract.** It lists which files the model may edit. Tests and checks are locked.
2. **We reproduce the bug in Nebius Sandbox.**
3. **A deterministic router picks the model.** Cheaper models only go first once data shows they pay off; today that's **Nemotron Ultra**.
4. **The reply is line-numbered plain-text edits.** We turn those into a patch and verify every gate.

**MEERA:** Why not just use the cheaper model?

**HARI:** We measured it. Nemotron Super scored zero out of eight, and most of those failures traced to our JSON reply format: an unescaped quote cut its answers short. We fixed the format before judging the model.

### 1:30–2:05 · The agent iterates (Coding & Agentic track)

*Screen: evidence page → aggregate_3 → Post-fix re-check tab. Point at the 100-run bar.*

**MEERA:** What if the first patch is wrong?

**HARI:** Watch this one. Ultra's first patch passed 92 of 100 stress runs. Those eight red cells are failures, and ThreadSanitizer caught a race. **Rejected.**

**HARI:** So the agent gets *one* more call, carrying the failed patch and the exact verifier evidence. Second patch: **100 out of 100, three of three TSan.** Verified.

**MEERA:** It debugged itself from the evidence.

**HARI:** Plan, write, test, iterate, with no human in the loop.

### 2:05–2:30 · Honest limits (rigor)

*Screen: evidence page → case matrix, then the totals table.*

**MEERA:** Is it better than just using Ultra?

**HARI:** Not proven.
- In our frozen run, v4 verified **five of eight**; Ultra alone verified six.
- Both losses were bugs in *our* code, and fixing them recovered both.
- v4 solved a program no earlier route ever solved.
- One program is still unsolved by everything.

These are eight small synthetic programs, not a statistical claim.

### 2:30–2:50 · Who it's for and the close (Potential Impact)

*Screen: the GitHub repo README, then end on the evidence page header.*

**MEERA:** Who needs this?

**HARI:** Any team reviewing AI-written C and C++ concurrency code. It's the bug class where "it worked once" means nothing. Every repair ships with its patch, its tokens and cost, and the evidence that it survived.

**MEERA:** Built on?

**HARI:** **Nebius Token Factory, Nebius Sandbox and NVIDIA Nemotron.** It's open source under MIT. AgentKernel: the model proposes, execution decides.

## Recording checklist

- [ ] The audio says "NVIDIA Nemotron Ultra", "Nebius Token Factory" and "Nebius Sandbox" clearly. A judge checks for these.
- [ ] The verified run is on screen by **0:30**.
- [ ] Every number spoken matches the evidence:

  | Spoken | Source |
  | --- | --- |
  | 100 stress runs, 3 TSan runs | audit_3 run `8792a943…` |
  | about $0.0014 ("a tenth of a cent") | audit_3 run `8792a943…` |
  | 92/100 → 100/100 | aggregate_3 re-check |
  | 0/8 for Super | v3 comparison |
  | 5/8 vs 6/8 | frozen pilot |

- [ ] Saved runs are called "a run from today", never "running now".
- [ ] No keys, `.env`, Sites token or email inbox on screen.
- [ ] Final length under **3:00**. Leave a margin, because YouTube processing does not change length but the rules are strict.
- [ ] Upload to YouTube as **Public**, then open the link in a signed-out window to check it plays.
- [ ] **Upload early.** Devpost warns that uploads take longer than expected, and nothing may change after 10:00 AM PT / 22:30 IST.

## Devpost items this video depends on

- **Working demo URL:** the checklist asks for one. The hosted console needs your ChatGPT sign-in, and the local dashboard is on your PC. The most judge-accessible link is the **shared evidence page** (read-only, saved real runs), together with the public repo's README run instructions. State plainly in the form that live repairs run from the local dashboard with the user's own Nebius keys.
- **Built With:** Nebius Token Factory, Nebius Sandbox (Contree SDK), NVIDIA Nemotron Ultra and Super, Python, ThreadSanitizer/Clang.
- **Feedback section** (required): Devpost asks what you used each tool for, what worked, what needs work, how onboarding felt, and whether you'd build with it again. `SUBMISSION.md` → "Feedback on Nebius and NVIDIA tooling" has a draft. Add a line on the JSON-schema quote-closure behaviour you hit with Super; it's specific, actionable feedback.
- **Prior work:** the repo's first commits date from 14 September 2026. Confirm that's within the hackathon period, or disclose it.
