from abc import ABC, abstractmethod

from agentkernel.core.models import AttemptRecord, InferenceResult, TaskRequest, VerificationResult


class Verifier(ABC):
    @abstractmethod
    async def verify(self, task: TaskRequest, inference: InferenceResult,
                     attempt_history: list[AttemptRecord]) -> VerificationResult:
        """Verify the current inference with prior completed attempts as context."""
