# AgentKernel

**AgentKernel is an adaptive inference runtime, not a coding assistant.**

AgentKernel is designed to decide how much intelligence a task needs, where inference
should run, when to escalate, whether execution worked, and what it cost. CI repair
is the first intended benchmark application. This milestone implements only the
local architecture: deterministic routing, one simulated provider call, and telemetry.
It does not repair code or verify a proposed fix.

## Run locally

Requires Python 3.11+. From this directory:

```sh
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest
python -m agentkernel.cli --task "ModuleNotFoundError: No module named requests"
python -m agentkernel.cli --task "Deprecated SDK API failure"
python -m agentkernel.cli --task "Race condition between worker threads"
python -m agentkernel.cli --task "Test failure" --privacy-sensitive --telemetry-jsonl telemetry/events.jsonl
```

No GPU, credentials, network service, or `.env` configuration is needed to execute.
Dependency installation requires packages to be available from an index or cache.

## Architecture

```text
Task -> semantic router -> execution tier -> provider -> inference -> telemetry
```

The semantic router is currently a rule-based placeholder, not an LLM. Pydantic
schemas live in `core`; async abstract interfaces isolate routing and provider
implementations. `AgentKernel` injects these dependencies and returns an
`ExecutionResult` containing `routing` and `inference`. It is ready to be called
from a future FastAPI endpoint, but no API or frontend is included.

Heuristics are centralized in `router/rule_router.py`. HARD signals win over MEDIUM
and EASY signals. Simple imports, syntax, and lint issues use LOCAL; routine test
failures use NANO; version conflicts, external knowledge signals, and multiple
Python stack frames use SUPER; concurrency/state issues use ULTRA. Unknown prompts
use NANO with low confidence. Scores and risk levels are heuristic, not calibrated.

Privacy is a **soft preference**: non-hard tasks use LOCAL, while hard tasks retain
ULTRA. This is not a privacy enforcement boundary; revisit before real remote calls.
External knowledge is flagged only, never fetched. `max_cost_usd` and
`max_latency_ms` are validated optional fields but are **not enforced in v1**.

Each completed inference attempt records one event, including ordinary provider
exceptions converted to FAILED results. Routing exceptions and cancellation propagate;
they do not produce completed-inference events. Failed calls use measured elapsed
time and zero usage/cost placeholders with `usage_unknown` metadata on the result.
These zeros do not establish that a failed future real call was free.
The recorder stores snapshots in memory and overwrites the chosen JSONL file with
all events. Events include the full routing decision, UTC time, unique ID, usage,
cost, and status, without storing the task prompt or generated text.

## What is mocked

- LOCAL_RTX returns deterministic placeholder text; no model is loaded.
- Nebius NANO/SUPER/ULTRA return placeholder text with fixed increasing latency,
  output-token estimates, and flat per-call costs. These are not actual model prices.
- Latency is reported synthetically, without sleeping; input tokens use a character
  count estimate. No real tokenizer or GPU measurement is used.
- All successful mock calls have status MOCK, never SUCCESS. A proposed fix is not
  evidence that anything worked.

**MOCK VALUES — DO NOT USE FOR FINAL BENCHMARK RESULTS.**

## Future targets — NOT IMPLEMENTED

- Real NVIDIA RTX inference
- Nebius Token Factory
- Nemotron Nano/Super/Ultra
- Sandbox verification
- Progressive escalation
- Tavily grounding
- llm-d infrastructure routing
- Adaptive learned routing
- CI repair benchmark and GitHub PR integration

No Docker, database, cloud integration, coding agent, or additional framework is
included. Runtime policy and adapters can be replaced independently as later
milestones add real inference and verification.
