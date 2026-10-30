from collections.abc import Callable

from agentkernel.core.enums import ExecutionStatus, InferenceTier, ProviderType
from agentkernel.core.models import InferenceResult, RoutingDecision, TaskRequest
from .base import InferenceProvider

# MOCK VALUES — DO NOT USE FOR FINAL BENCHMARK RESULTS.
# tier: simulated latency ms, generated tokens, flat estimated call cost USD
MOCK_PROFILES: dict[InferenceTier, tuple[float, int, float]] = {
    InferenceTier.NANO: (80, 64, 0.0001),
    InferenceTier.SUPER: (200, 128, 0.0005),
    InferenceTier.ULTRA: (500, 256, 0.0020),
}


class MockNebiusProvider(InferenceProvider):
    def __init__(self, response_factory: Callable[[TaskRequest, RoutingDecision], str] | None = None) -> None:
        self.response_factory = response_factory

    def estimate_cost_usd(self, tier: InferenceTier) -> float:
        return MOCK_PROFILES[tier][2]

    async def generate(self, task: TaskRequest, routing: RoutingDecision) -> InferenceResult:
        if routing.selected_provider != ProviderType.NEBIUS or routing.selected_tier not in MOCK_PROFILES:
            raise ValueError("MockNebiusProvider requires a NEBIUS Nano, Super, or Ultra route")
        latency, tokens, cost = MOCK_PROFILES[routing.selected_tier]
        return InferenceResult(
            task_id=task.task_id, provider=ProviderType.NEBIUS, tier=routing.selected_tier,
            output_text=(self.response_factory(task, routing) if self.response_factory else
                         f"NEBIUS_{routing.selected_tier.value}_MOCK_RESPONSE: Proposed fix for task {task.task_id}"),
            status=ExecutionStatus.MOCK, latency_ms=latency,
            input_tokens=max(1, (len(task.prompt) + 3) // 4), output_tokens=tokens,
            estimated_cost_usd=cost,
            metadata={"simulated": True, "execution_mode": "mock", "latency_source": "fixed simulation", "tokens_source": "synthetic estimate"},
        )
