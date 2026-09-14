from time import perf_counter

from agentkernel.core.enums import ExecutionStatus, ProviderType
from agentkernel.core.models import ExecutionResult, InferenceResult, TaskRequest
from agentkernel.providers.base import InferenceProvider
from agentkernel.router.base import Router
from agentkernel.telemetry.events import TelemetryEvent
from agentkernel.telemetry.recorder import TelemetryRecorder


class AgentKernel:
    def __init__(self, router: Router, local_provider: InferenceProvider,
                 nebius_provider: InferenceProvider, telemetry: TelemetryRecorder) -> None:
        self.router = router
        self.providers = {ProviderType.LOCAL_RTX: local_provider, ProviderType.NEBIUS: nebius_provider}
        self.telemetry = telemetry

    async def execute(self, task: TaskRequest) -> ExecutionResult:
        routing = await self.router.route(task)
        start = perf_counter()
        try:
            inference = await self.providers[routing.selected_provider].generate(task, routing)
            if (inference.task_id != task.task_id or inference.provider != routing.selected_provider
                    or inference.tier != routing.selected_tier):
                raise ValueError("Provider result does not match the requested route")
        except Exception as exc:
            inference = InferenceResult(
                task_id=task.task_id, provider=routing.selected_provider, tier=routing.selected_tier,
                output_text="Provider execution failed.", status=ExecutionStatus.FAILED,
                latency_ms=(perf_counter() - start) * 1000, input_tokens=0, output_tokens=0,
                estimated_cost_usd=0,
                metadata={"error_type": type(exc).__name__, "usage_unknown": True},
            )
        self.telemetry.record(TelemetryEvent(
            task_id=task.task_id, route=routing, provider=inference.provider, tier=inference.tier,
            difficulty=routing.difficulty, confidence=routing.confidence,
            latency_ms=inference.latency_ms, input_tokens=inference.input_tokens,
            output_tokens=inference.output_tokens, estimated_cost_usd=inference.estimated_cost_usd,
            status=inference.status,
        ))
        return ExecutionResult(routing=routing, inference=inference)
