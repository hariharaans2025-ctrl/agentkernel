import asyncio
import json
from pathlib import Path

import pytest

from agentkernel.core.enums import ExecutionStatus, InferenceTier
from agentkernel.core.models import AttemptRecord, InferenceResult, RoutingDecision, TaskRequest, VerificationResult
from agentkernel.providers.base import InferenceProvider
from agentkernel.providers.local_rtx import LocalRTXProvider
from agentkernel.providers.mock_nebius import MOCK_PROFILES, MockNebiusProvider
from agentkernel.router.rule_router import RuleBasedRouter
from agentkernel.runtime.kernel import AgentKernel
from agentkernel.telemetry.events import TelemetryEvent
from agentkernel.telemetry.recorder import TelemetryRecorder
from agentkernel.verification.base import Verifier
from agentkernel.verification.mock_verifier import MockVerifier


class RecordingProvider(InferenceProvider):
    def __init__(self, delegate: InferenceProvider) -> None:
        self.delegate = delegate
        self.tasks: list[TaskRequest] = []

    def estimate_cost_usd(self, tier: InferenceTier) -> float | None:
        return self.delegate.estimate_cost_usd(tier)

    async def generate(self, task: TaskRequest, routing: RoutingDecision) -> InferenceResult:
        self.tasks.append(task.model_copy(deep=True))
        return await self.delegate.generate(task, routing)


def request(plan: dict[str, bool] | None = None, *, prompt: str = "ImportError") -> TaskRequest:
    return TaskRequest(task_id="escalation", task_type="ci", prompt=prompt,
                       metadata={"verification_plan": plan} if plan is not None else {})


@pytest.mark.parametrize(("prompt", "plan", "tiers", "success", "reason"), [
    ("ImportError", {"LOCAL": True}, ["LOCAL"], True, "verification_passed"),
    ("ImportError", {"NANO": True}, ["LOCAL", "NANO"], True, "verification_passed"),
    ("ImportError", {"SUPER": True}, ["LOCAL", "NANO", "SUPER"], True, "verification_passed"),
    ("ImportError", {}, ["LOCAL", "NANO", "SUPER", "ULTRA"], False, "ultra_failed"),
    ("Deprecated API", {}, ["SUPER", "ULTRA"], False, "ultra_failed"),
    ("Race condition", {}, ["ULTRA"], False, "ultra_failed"),
    ("Test failure", {"ULTRA": True}, ["NANO", "SUPER", "ULTRA"], True, "verification_passed"),
])
def test_escalation_ladder(prompt: str, plan: dict[str, bool], tiers: list[str], success: bool, reason: str) -> None:
    recorder = TelemetryRecorder()
    kernel = AgentKernel(RuleBasedRouter(), LocalRTXProvider(), MockNebiusProvider(), recorder)
    result = asyncio.run(kernel.execute(request(plan, prompt=prompt)))
    assert [attempt.tier.value for attempt in result.attempts] == tiers
    assert result.success is success
    assert result.stopped_reason == reason
    assert result.final_tier.value == tiers[-1]
    assert result.final_output == result.inference.output_text == result.attempts[-1].output_text
    assert len(recorder.events) == len(tiers)
    assert [event.escalated_after_attempt for event in recorder.events] == [True] * (len(tiers) - 1) + [False]
    assert len(recorder.execution_events) == 1
    summary = recorder.execution_events[0]
    assert summary.success is success
    assert summary.starting_tier.value == tiers[0]
    assert summary.final_tier == result.final_tier
    assert summary.number_of_attempts == len(tiers)
    assert summary.stopped_reason == reason
    assert {event.execution_id for event in recorder.all_events} == {result.metadata["execution_id"]}


def test_failure_evidence_and_full_history_preserve_original() -> None:
    remote = RecordingProvider(MockNebiusProvider())
    original = request({"SUPER": True})
    original.metadata["repository"] = "example-repo"
    snapshot = original.model_copy(deep=True)
    result = asyncio.run(AgentKernel(RuleBasedRouter(), LocalRTXProvider(), remote, TelemetryRecorder()).execute(original))
    assert original == snapshot
    for index, enriched in enumerate(remote.tasks, start=1):
        previous = result.attempts[index - 1]
        assert "ORIGINAL TASK\nImportError" in enriched.prompt
        assert "PREVIOUS ATTEMPT" in enriched.prompt
        assert "VERIFICATION RESULT" in enriched.prompt
        assert previous.verification_reason in enriched.prompt
        assert previous.output_text in enriched.prompt
        assert "Use the previous failure as evidence." in enriched.prompt
        assert "Do not repeat the same unsupported approach." in enriched.prompt
        assert "ATTEMPT HISTORY" in enriched.prompt
        for earlier in result.attempts[:index]:
            assert earlier.output_text in enriched.prompt
            assert f"Attempt {earlier.attempt_number}: {earlier.tier.value}" in enriched.prompt
        assert "<InferenceTier" not in enriched.prompt
        assert enriched.prompt.count("ORIGINAL TASK") == 1
        assert enriched.metadata["repository"] == "example-repo"
        assert enriched.metadata["failure_evidence"]["attempt_number"] == index


@pytest.mark.parametrize(("budget", "count", "reason"), [
    (0, 1, "budget_exceeded"), (0.0001, 2, "budget_exceeded"),
    (0.0006, 3, "verification_passed"),
])
def test_budget_stops_before_call(budget: float, count: int, reason: str) -> None:
    remote = RecordingProvider(MockNebiusProvider())
    recorder = TelemetryRecorder()
    task = request({"SUPER": True})
    task.max_cost_usd = budget
    result = asyncio.run(AgentKernel(RuleBasedRouter(), LocalRTXProvider(), remote, recorder).execute(task))
    assert len(result.attempts) == count
    assert len(remote.tasks) == count - 1
    assert result.stopped_reason == reason
    assert result.total_cost_usd <= budget
    assert recorder.events[-1].escalated_after_attempt is False


def test_initial_budget_can_block_all_calls() -> None:
    task = request(prompt="Race condition")
    task.max_cost_usd = 0
    remote = RecordingProvider(MockNebiusProvider())
    recorder = TelemetryRecorder()
    result = asyncio.run(AgentKernel(RuleBasedRouter(), LocalRTXProvider(), remote, recorder).execute(task))
    assert not remote.tasks
    assert result.attempts == []
    assert result.final_tier is None
    assert result.inference is None
    assert result.stopped_reason == "budget_exceeded"
    assert not recorder.events
    assert recorder.execution_events[0].number_of_attempts == 0


def test_budget_uses_provider_configured_estimate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(MOCK_PROFILES, InferenceTier.NANO, (80, 64, 0.25))
    task = request({"NANO": True})
    task.max_cost_usd = 0.01
    result = asyncio.run(AgentKernel(RuleBasedRouter(), LocalRTXProvider(), MockNebiusProvider(), TelemetryRecorder()).execute(task))
    assert len(result.attempts) == 1
    assert result.stopped_reason == "budget_exceeded"


def test_latency_counts_verifier_wall_time_not_mock_latency(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [0.0]
    monkeypatch.setattr("agentkernel.runtime.kernel.perf_counter", lambda: now[0])
    class SlowVerifier(MockVerifier):
        async def verify(self, task: TaskRequest, inference: InferenceResult,
                         attempt_history: list[AttemptRecord]) -> VerificationResult:
            now[0] += 0.05
            return await super().verify(task, inference, attempt_history)
    task = request()
    task.max_latency_ms = 40
    recorder = TelemetryRecorder()
    result = asyncio.run(AgentKernel(RuleBasedRouter(), LocalRTXProvider(), MockNebiusProvider(),
                                     recorder, SlowVerifier()).execute(task))
    assert len(result.attempts) == 1
    assert result.stopped_reason == "latency_limit_exceeded"
    assert result.total_latency_ms == 15  # inference-only aggregate
    assert result.metadata["wall_elapsed_ms"] == 50  # includes verification
    assert not recorder.events[0].escalated_after_attempt


def test_synthetic_latency_does_not_spend_wall_time_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agentkernel.runtime.kernel.perf_counter", lambda: 0.0)
    task = request({"SUPER": True})
    task.max_latency_ms = 1
    result = asyncio.run(AgentKernel(RuleBasedRouter(), LocalRTXProvider(), MockNebiusProvider(), TelemetryRecorder()).execute(task))
    assert result.success
    assert result.total_latency_ms == 295


@pytest.mark.parametrize("limit", [1, 2, 3, 4, 100])
def test_max_attempts_bounds_loop(limit: int) -> None:
    result = asyncio.run(AgentKernel(RuleBasedRouter(), LocalRTXProvider(), MockNebiusProvider(),
                                     TelemetryRecorder(), max_attempts=limit).execute(request()))
    assert len(result.attempts) == min(limit, 4)
    assert result.stopped_reason == ("max_attempts_reached" if limit < 4 else "ultra_failed")


def test_environment_max_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTKERNEL_MAX_ATTEMPTS", "2")
    result = asyncio.run(AgentKernel(RuleBasedRouter(), LocalRTXProvider(), MockNebiusProvider(), TelemetryRecorder()).execute(request()))
    assert len(result.attempts) == 2


@pytest.mark.parametrize("value", ["0", "-1", "text", "1.5"])
def test_invalid_max_attempts(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("AGENTKERNEL_MAX_ATTEMPTS", value)
    with pytest.raises(ValueError, match="positive integer"):
        AgentKernel(RuleBasedRouter(), LocalRTXProvider(), MockNebiusProvider(), TelemetryRecorder())


def test_totals_and_jsonl_summary(tmp_path: Path) -> None:
    recorder = TelemetryRecorder()
    result = asyncio.run(AgentKernel(RuleBasedRouter(), LocalRTXProvider(), MockNebiusProvider(), recorder).execute(request({"SUPER": True})))
    assert result.total_cost_usd == pytest.approx(sum(attempt.estimated_cost_usd for attempt in result.attempts))
    assert result.total_cost_usd == 0.0006
    assert result.total_latency_ms == sum(attempt.latency_ms for attempt in result.attempts) == 295
    assert [event.cumulative_latency for event in recorder.events] == [15, 95, 295]
    assert [event.cumulative_cost for event in recorder.events] == [0, 0.0001, 0.0006]
    rows = [json.loads(line) for line in recorder.export_jsonl(tmp_path / "events.jsonl").read_text().splitlines()]
    assert [row["event_type"] for row in rows] == ["attempt", "attempt", "attempt", "execution"]
    assert rows[-1]["total_cost"] == result.total_cost_usd
    assert rows[-1]["total_latency"] == result.total_latency_ms
    assert [row["attempt_number"] for row in rows[:-1]] == [1, 2, 3]
    assert [row["verification_passed"] for row in rows[:-1]] == [False, False, True]


def test_old_jsonl_attempt_still_parses() -> None:
    recorder = TelemetryRecorder()
    asyncio.run(AgentKernel(RuleBasedRouter(), LocalRTXProvider(), MockNebiusProvider(), recorder).execute(request({"LOCAL": True})))
    old = recorder.events[0].model_dump()
    for key in ("event_type", "execution_id", "attempt_number", "model", "verification_passed",
                "verification_reason", "cumulative_cost", "cumulative_latency", "escalated_after_attempt"):
        del old[key]
    assert TelemetryEvent.model_validate(old).attempt_number == 1


class BrokenVerifier(Verifier):
    async def verify(self, task: TaskRequest, inference: InferenceResult,
                     attempt_history: list[AttemptRecord]) -> VerificationResult:
        raise RuntimeError("broken checker")


def test_verifier_error_fails_closed_and_propagates() -> None:
    result = asyncio.run(AgentKernel(RuleBasedRouter(), LocalRTXProvider(), MockNebiusProvider(),
                                     TelemetryRecorder(), BrokenVerifier(), max_attempts=2).execute(request()))
    assert not result.success
    assert result.attempts[0].verification_status == "FAILED"
    assert "Verifier raised an error" in result.attempts[1].input_prompt
    assert "RuntimeError" in result.attempts[1].input_prompt


def test_provider_failure_cannot_be_verified_as_pass() -> None:
    class BrokenProvider(LocalRTXProvider):
        async def generate(self, task: TaskRequest, routing: RoutingDecision) -> InferenceResult:
            raise RuntimeError("failed generation")
    result = asyncio.run(AgentKernel(RuleBasedRouter(), BrokenProvider(), MockNebiusProvider(),
                                     TelemetryRecorder(), MockVerifier(default_pass=True)).execute(request()))
    assert len(result.attempts) == 2
    assert result.attempts[0].status == ExecutionStatus.FAILED
    assert result.attempts[0].verification_status == "FAILED"
    assert "RuntimeError" in result.attempts[1].input_prompt
    assert result.success


@pytest.mark.parametrize("plan", [{"LOCAL": "false"}, {"TYPO": True}, []])
def test_invalid_mock_plan_fails_closed(plan: object) -> None:
    task = request()
    task.metadata["verification_plan"] = plan
    result = asyncio.run(AgentKernel(RuleBasedRouter(), LocalRTXProvider(), MockNebiusProvider(),
                                     TelemetryRecorder(), MockVerifier(default_pass=True), max_attempts=1).execute(task))
    assert not result.success
    assert "Invalid verification_plan" in result.attempts[0].verification_reason


def test_verifier_receives_original_task_and_prior_history() -> None:
    class InspectingVerifier(MockVerifier):
        async def verify(self, task: TaskRequest, inference: InferenceResult,
                         attempt_history: list[AttemptRecord]) -> VerificationResult:
            assert task.prompt == "ImportError"
            assert len(attempt_history) == (0 if inference.tier == InferenceTier.LOCAL else 1)
            if attempt_history:
                assert attempt_history[0].verification_status == "FAILED"
            return await super().verify(task, inference, attempt_history)
    result = asyncio.run(AgentKernel(RuleBasedRouter(), LocalRTXProvider(), MockNebiusProvider(),
                                     TelemetryRecorder(), InspectingVerifier()).execute(request({"NANO": True})))
    assert result.success
