# Three-model benchmark status — 2026-09-30

Requested: one independent repair attempt each for Nano, Super and Ultra on deadlock_001, plus individual and aggregate technical metrics.

Implemented: technical metrics module, dashboard tables and aggregates, 2,048 output tokens per model (6,144 combined), 12,000 UTF-8 input-content-byte cap per request, no retries or escalation, unchanged 100-run verification. Added remote regression tests for payload caps, oversized-input rejection, missing usage and weighted aggregation.

Live execution is blocked before paid inference. Token Factory model-catalog requests time out during TCP connection; sandbox health times out and two project-upload attempts failed with ContreeTransportError. The public nebius.com website returns HTTP 200 from this computer, while api.tokenfactory.nebius.com resolves to 213.239.161.19 but its HTTPS connection times out. The user reports using a mobile hotspot without a VPN or proxy. This does not establish whether the cause is carrier routing, network filtering or the API service.

No new model completion request was sent. No new output comparison or 100-run candidate campaign exists for this request. Remote tests could not start because upload failed; the earlier 219 passing tests predate these changes. Python syntax was parsed without running benchmark/tests locally. Browser validation was unavailable because browser access was blocked by its URL policy.

Next: restore API connectivity, run the remote test suite, then launch exactly one Nano/Super/Ultra comparison with the bounded settings. Do not automatically retry a paid request with unknown outcome.

## Resolved — 2026-10-03

Connectivity recovered. Remote tests passed: 221 passed, 8 deselected. Completed exactly one request each for Nano, Super and Ultra under the 2,048 output-token cap with no retries. Run 3c1104de-f8ca-4af9-83a5-c4598eacfc25: Nano incomplete response; Super 0/100 verification passes; Ultra 100/100. Aggregate usage: 6,074 input + 4,529 output = 10,603 tokens. See the matching JSON and Markdown reports in this directory.
