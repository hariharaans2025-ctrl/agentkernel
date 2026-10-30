from abc import ABC, abstractmethod

from agentkernel.core.models import RoutingDecision, TaskRequest


class Router(ABC):
    @abstractmethod
    async def route(self, task: TaskRequest) -> RoutingDecision:
        """Choose one execution tier and provider."""
