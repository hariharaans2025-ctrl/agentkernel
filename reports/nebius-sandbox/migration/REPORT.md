# Nebius execution migration

Project: `aiproject-e00z8mw0ggdmwn69nb`.

Concurrency Bug Hunter now uses NebiusSandboxBackend for baseline compilation,
baseline stress runs, candidate compilation, original tests, verification campaigns,
and the execution smoke path. There is no automatic local execution fallback.
Missing credentials or remote service errors stop the operation.

The source, tests, benchmarks, deployment script, and dependencies are deployed as:

- Tag: `agentkernel-project:20260928t122008z`
- Image ID: `a25e528b-8f3e-4655-a1b8-5d9008d284e8`
- Upload manifest: `../20260928T122008Z/deployment.json` (127 files)
- Audit: `../20260928T122008Z/audit.json` (no configured credential values found)

## Measured remote validation

- GCC was checked inside the remote `python:3.12` image.
- Full default test suite: **209 passed, 8 deselected**, executed inside Nebius.
- `deadlock_001`: remote baseline reproduced the deadlock; saved live Super edits
  applied and rebuilt remotely; **100/100 remote verification runs passed**.
- No verification deadlocks, crashes, or infrastructure failures.
- Rebuild plus verification wall time: approximately 242 seconds, including remote
  operation overhead. Each command runs as a separate remote operation.
- No new paid model request. The inference adapter replayed the previous real
  response; mock inference token/cost fields in the raw job are not new measured
  model usage. Remote sandbox compute is separate from model inference billing.
- Original fixture SHA-256 remained unchanged.

The replayed patch still changes simultaneous-locking semantics, as documented in
the earlier live-model report. ThreadSanitizer was not configured for this fixture;
this is not proof of race freedom or semantic equivalence.

## Operation and boundaries

Run `python scripts/push_sandbox.py` from the repository to upload and test a fresh
remote project snapshot. The script creates a timestamped deployment report and
tag, and makes no model request. Normal concurrency commands now execute remotely;
pass the private `.env` through `--env-file .env` for credentials and project ID.

The local machine remains the API controller and stores the editable checkout and
reports. Temporary text-only staging supports strict diff validation. No compiler,
test suite, or candidate program was executed on the local host for this migration.
The legacy local backend is retained for isolated test fixtures, which were run
inside the remote test container; production concurrency paths do not select it.

API keys and host environment variables are not uploaded or inherited by commands.
Remote instances terminate after each command. Filesystem snapshots remain in the
service according to its retention policy; SDK 0.3.6 has no snapshot deletion API.

Raw execution evidence: `remote-deadlock-100.json`, `remote-events.jsonl`, and
`../20260928T122008Z/tests.json`.
