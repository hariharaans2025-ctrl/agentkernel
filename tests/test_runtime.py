import asyncio

import pytest

from agentkernel.core.enums import ExecutionStatus, InferenceTier, ProviderType
from agentkernel.core.models import InferenceResult, RoutingDecision, TaskRequest
from agentkernel.providers.base import InferenceProvider
from agentkernel.providers.local_rtx import LocalRTXProvider
from agentkernel.providers.mock_nebius import MockNebiusProvider
from agentkernel.router.rule_router import RuleBasedRouter
from agentkernel.runtime.kernel import AgentKernel
from agentkernel.telemetry.recorder import TelemetryRecorder


class SpyProvider(InferenceProvider):
    def __init__(self, delegate: InferenceProvider) -> None:
        self.delegate = delegate
        self.calls = 0

    async def generate(self, task: TaskRequest, routing: RoutingDecision) -> InferenceResult:
        self.calls += 1
        return await self.delegate.generate(task, routing)


@pytest.mark.parametrize(("prompt", "provider", "tier"), [
    ("ImportError", ProviderType.LOCAL_RTX, InferenceTier.LOCAL),
    ("Test failure", ProviderType.NEBIUS, InferenceTier.NANO),
    ("Deprecated API", ProviderType.NEBIUS, InferenceTier.SUPER),
    ("Race condition", ProviderType.NEBIUS, InferenceTier.ULTRA),
])
def test_runtime_selects_exactly_one_provider(prompt: str, provider: ProviderType, tier: InferenceTier) -> None:
    recorder = TelemetryRecorder()
    local, remote = SpyProvider(LocalRTXProvider()), SpyProvider(MockNebiusProvider())
    kernel = AgentKernel(RuleBasedRouter(), local, remote, recorder)
    result = asyncio.run(kernel.execute(TaskRequest(task_id="t", task_type="ci", prompt=prompt)))
    assert result.inference.provider == provider
    assert result.inference.tier == tier
    assert result.inference.status == ExecutionStatus.MOCK
    assert (local.calls, remote.calls) == ((1, 0) if provider == ProviderType.LOCAL_RTX else (0, 1))
    assert len(recorder.events) == 1
    assert recorder.events[0].route == result.routing
    assert recorder.events[0].estimated_cost_usd == result.inference.estimated_cost_usd


class BrokenProvider(InferenceProvider):
    async def generate(self, task: TaskRequest, routing: RoutingDecision) -> InferenceResult:
        raise RuntimeError("provider unavailable")


def test_failed_call_records_event() -> None:
    recorder = TelemetryRecorder()
    kernel = AgentKernel(RuleBasedRouter(), BrokenProvider(), MockNebiusProvider(), recorder)
    result = asyncio.run(kernel.execute(TaskRequest(task_id="t", task_type="ci", prompt="ImportError")))
    assert result.inference.status == ExecutionStatus.FAILED
    assert result.inference.metadata["usage_unknown"] is True
    assert len(recorder.events) == 1
    assert recorder.events[0].status == ExecutionStatus.FAILED


def test_mock_tiers_increase_latency_tokens_cost() -> None:
    recorder = TelemetryRecorder()
    kernel = AgentKernel(RuleBasedRouter(), LocalRTXProvider(), MockNebiusProvider(), recorder)
    results = [asyncio.run(kernel.execute(TaskRequest(task_id="t", task_type="ci", prompt=prompt))).inference
               for prompt in ("Test failure", "Deprecated API", "Deadlock")]
    assert results[0].latency_ms < results[1].latency_ms < results[2].latency_ms
    assert results[0].output_tokens < results[1].output_tokens < results[2].output_tokens
    assert results[0].estimated_cost_usd < results[1].estimated_cost_usd < results[2].estimated_cost_usd
