from abc import ABC, abstractmethod

from agentkernel.core.models import InferenceResult, RoutingDecision, TaskRequest
from agentkernel.core.enums import InferenceTier


class InferenceProvider(ABC):
    def estimate_cost_usd(self, tier: InferenceTier) -> float | None:
        """Return a preflight estimate, or None when unknown. Does not run inference."""
        return None

    @abstractmethod
    async def generate(self, task: TaskRequest, routing: RoutingDecision) -> InferenceResult:
        """Generate a result for the selected route."""
