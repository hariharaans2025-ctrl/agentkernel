# Patch quality repair — September 23, 2026

The repair pipeline now generates diff structure deterministically from exact source
edits. It no longer asks the model to calculate hunk offsets and counts. Existing
unified-diff responses remain accepted through the strict applier.

## Changes

- Preferred response: diagnosis fields plus `edits`, each containing an allowlisted
  C/header filename, unique original search text and replacement text.
- Match all blocks against original source before generating a patch. Reject missing,
  ambiguous, overlapping, unchanged or unsafe edits without changing any file.
- Generate canonical diffs with correct headers/counts and EOF markers. Keep the
  existing source-context/path checks and disposable application boundary.
- Add targeted error codes/hints, including double-escaping and original-source
  guidance. Retry feedback preserves previous failures and the total attempt budget.
- Explain why barriers, joins and condition waits can still block after enforcing
  a common mutex order. Do not treat model confidence or diff validity as verification.
- Validate Super smoke patch applicability in a disposable copy without executing it.

## Real native regression

Executed the existing `deadlock_001` C/pthreads fixture with LLVM-MinGW/Clang on the
current Windows host. The original fixture was not modified. No Nebius inference,
Nebius sandbox or LangSmith network call was made in this validation.

| Stage | Measured outcome |
|---|---|
| Original baseline | 1 run classified POSSIBLE_DEADLOCK |
| Scripted candidate 1: common lock order, barrier still inside critical section | Diff accepted; all 10 runs deadlocked |
| Scripted candidate 2: common lock order, barrier before lock acquisition | Diff accepted; all 10 runs passed; 0 observed verification failures |

The route was Nano → Super → Super with **scripted mock inference** and **real C
compilation/execution**. Failure evidence from the first candidate reached the next
attempt. The second patch passed the configured verification campaign; this is not
a proof that concurrency failures are impossible.

[Full measured report](native-regression.json) · [Verified scripted candidate diff](candidate.patch)

Final offline suite: **196 passed, 8 deselected, 0 failed in 58.71 seconds**.
The 8 excluded tests comprise 5 native integration checks and 3 live-account checks.
The new native integration test was selected separately and passed (1 passed in
48.19 seconds). Offline coverage additionally checks
C string escaping, missing final newlines, multi-file edits, unsafe paths,
overlapping/ambiguous edits, correction feedback and malformed legacy hunks.

[Secret audit](secret-audit.json) passed: no configured-key or common credential
pattern matches in scanned repository files/staged blobs, `.env` remains ignored
and untracked, and the original fixture still matches its approved SHA-256.

## Limits

No new paid model request was made. Improved live Nemotron repair success is not yet
measured. The prompt encourages correct synchronization analysis, but model-generated
logic still requires real compilation and execution verification. The native test
uses 10 verification runs, not the fixture's default 100. No full benchmark was run.
Nebius sandbox access remains blocked by account permissions and is separate from
this repair-quality change.
