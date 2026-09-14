from abc import ABC, abstractmethod

from agentkernel.core.models import InferenceResult, RoutingDecision, TaskRequest


class InferenceProvider(ABC):
    @abstractmethod
    async def generate(self, task: TaskRequest, routing: RoutingDecision) -> InferenceResult:
        """Generate a result for the selected route."""
