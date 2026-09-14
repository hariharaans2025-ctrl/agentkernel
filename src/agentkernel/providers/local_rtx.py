from agentkernel.core.enums import ExecutionStatus, InferenceTier, ProviderType
from agentkernel.core.models import InferenceResult, RoutingDecision, TaskRequest
from .base import InferenceProvider


class LocalRTXProvider(InferenceProvider):
    async def generate(self, task: TaskRequest, routing: RoutingDecision) -> InferenceResult:
        if routing.selected_provider != ProviderType.LOCAL_RTX or routing.selected_tier != InferenceTier.LOCAL:
            raise ValueError("LocalRTXProvider requires a LOCAL / LOCAL_RTX route")
        output = f"LOCAL_RTX_MOCK_RESPONSE: Proposed fix for task {task.task_id}"
        return InferenceResult(
            task_id=task.task_id, provider=ProviderType.LOCAL_RTX, tier=InferenceTier.LOCAL,
            output_text=output, status=ExecutionStatus.MOCK, latency_ms=15,
            input_tokens=max(1, (len(task.prompt) + 3) // 4),
            output_tokens=max(1, (len(output) + 3) // 4), estimated_cost_usd=0,
            metadata={"simulated": True, "latency_source": "fixed simulation"},
        )
