import os
from time import perf_counter

from agentkernel.core.enums import ExecutionStatus, InferenceTier, ProviderType
from agentkernel.core.models import InferenceResult, RoutingDecision, TaskRequest
from agentkernel.local.base import LocalBackendError, LocalBackendStatus, LocalInferenceBackend
from agentkernel.local.ollama_backend import OllamaBackend
from .base import InferenceProvider

SYSTEM_PROMPT = (
    "You are a lightweight engineering reasoning model running locally as part of AgentKernel.\n"
    "Give a concise proposed diagnosis or next action for the supplied task.\n"
    "Do not claim that commands were executed unless execution evidence is provided."
)


class LocalRTXProvider(InferenceProvider):
    def estimate_cost_usd(self, tier: InferenceTier) -> float:
        return 0.0

    def __init__(self, backend: LocalInferenceBackend | None = None, *, mock: bool | None = None) -> None:
        self._backend = backend
        self._mock = mock

    def _mock_enabled(self) -> bool:
        if self._mock is not None:
            return self._mock
        value = os.getenv("AGENTKERNEL_LOCAL_MOCK", "true").strip().lower()
        if value not in {"true", "false"}:
            raise LocalBackendError("AGENTKERNEL_LOCAL_MOCK must be true or false.")
        return value == "true"

    def _get_backend(self) -> LocalInferenceBackend:
        if self._backend is not None:
            return self._backend
        name = os.getenv("AGENTKERNEL_LOCAL_BACKEND", "ollama").strip().lower()
        if name != "ollama":
            raise LocalBackendError("Unsupported AGENTKERNEL_LOCAL_BACKEND. Use ollama for real inference.")
        return OllamaBackend()

    async def health_check(self) -> LocalBackendStatus:
        """Probe the real backend even when inference defaults to mock mode."""
        try:
            return await self._get_backend().health_check()
        except LocalBackendError as exc:
            return LocalBackendStatus(available=False,
                                      backend=os.getenv("AGENTKERNEL_LOCAL_BACKEND", "ollama"),
                                      configured_model=os.getenv("AGENTKERNEL_LOCAL_MODEL") or None,
                                      error=str(exc))

    async def generate(self, task: TaskRequest, routing: RoutingDecision) -> InferenceResult:
        if routing.selected_provider != ProviderType.LOCAL_RTX or routing.selected_tier != InferenceTier.LOCAL:
            raise ValueError("LocalRTXProvider requires a LOCAL / LOCAL_RTX route")
        start = perf_counter()
        try:
            if self._mock_enabled():
                return self._generate_mock(task)
            response = await self._get_backend().generate(task.prompt, SYSTEM_PROMPT)
        except LocalBackendError as exc:
            return InferenceResult(
                task_id=task.task_id, provider=ProviderType.LOCAL_RTX, tier=InferenceTier.LOCAL,
                output_text=str(exc), status=ExecutionStatus.FAILED,
                latency_ms=(perf_counter() - start) * 1000, input_tokens=0, output_tokens=0,
                estimated_cost_usd=0.0,
                metadata={"execution_mode": "real", "location": "local", "execution_location": "local",
                          "backend": os.getenv("AGENTKERNEL_LOCAL_BACKEND", "ollama"),
                          "model": os.getenv("AGENTKERNEL_LOCAL_MODEL") or None,
                          "error_type": type(exc).__name__, "usage_unknown": True,
                          "latency_source": "wall_clock"},
            )
        return InferenceResult(
            task_id=task.task_id, provider=ProviderType.LOCAL_RTX, tier=InferenceTier.LOCAL,
            output_text=response.output_text, status=ExecutionStatus.SUCCESS,
            latency_ms=response.latency_ms,
            input_tokens=response.input_tokens if response.input_tokens is not None else 0,
            output_tokens=response.output_tokens if response.output_tokens is not None else 0,
            estimated_cost_usd=0.0,
            metadata={**response.metadata, "execution_mode": "real", "location": "local",
                      "execution_location": "local", "model": response.model,
                      "input_tokens_available": response.input_tokens is not None,
                      "output_tokens_available": response.output_tokens is not None},
        )

    def _generate_mock(self, task: TaskRequest) -> InferenceResult:
        output = f"LOCAL_RTX_MOCK_RESPONSE: Proposed fix for task {task.task_id}"
        return InferenceResult(
            task_id=task.task_id, provider=ProviderType.LOCAL_RTX, tier=InferenceTier.LOCAL,
            output_text=output, status=ExecutionStatus.MOCK, latency_ms=15,
            input_tokens=max(1, (len(task.prompt) + 3) // 4),
            output_tokens=max(1, (len(output) + 3) // 4), estimated_cost_usd=0,
            metadata={"simulated": True, "latency_source": "fixed simulation",
                      "execution_mode": "mock", "location": "local", "execution_location": "local",
                      "backend": "mock", "model": None},
        )
