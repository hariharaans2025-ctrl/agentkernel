from agentkernel.core.enums import ExecutionStatus, InferenceTier
from agentkernel.core.models import AttemptRecord, InferenceResult, TaskRequest, VerificationResult
from .base import Verifier


class MockVerifier(Verifier):
    """Simulation only: a configured PASS does not establish task correctness."""

    def __init__(self, *, default_pass: bool = False) -> None:
        self.default_pass = default_pass

    async def verify(self, task: TaskRequest, inference: InferenceResult,
                     attempt_history: list[AttemptRecord]) -> VerificationResult:
        evidence = {"mock": True, "tier": inference.tier.value,
                    "previous_attempts": len(attempt_history)}
        if inference.status == ExecutionStatus.FAILED:
            return VerificationResult(passed=False, reason="Inference failed; no successful output to verify.",
                                      evidence=evidence, verifier_name="mock_verifier")
        plan = task.metadata.get("verification_plan")
        if plan is not None and (not isinstance(plan, dict) or any(
            key not in {tier.value for tier in InferenceTier} or type(value) is not bool
            for key, value in plan.items()
        )):
            return VerificationResult(passed=False, reason="Invalid verification_plan: use tier names and boolean outcomes.",
                                      evidence=evidence, verifier_name="mock_verifier")
        passed = plan.get(inference.tier.value, self.default_pass) if plan is not None else self.default_pass
        source = "verification plan" if plan is not None and inference.tier.value in plan else "default mock policy"
        return VerificationResult(
            passed=passed, score=1.0 if passed else 0.0,
            reason=f"Deterministic mock {source}: {'PASS' if passed else 'FAIL'} (not real verification).",
            evidence={**evidence, "source": source, "configured_outcome": passed}, verifier_name="mock_verifier",
        )
