from agentkernel.core.enums import InferenceTier, ProviderType, RiskLevel, TaskDifficulty
from agentkernel.core.models import RoutingDecision, TaskRequest
from agentkernel.router.base import Router


class ConcurrencyRouter(Router):
    def __init__(self, fixed_tier: InferenceTier | None = None) -> None:
        self.fixed_tier = fixed_tier

    async def route(self, task: TaskRequest) -> RoutingDecision:
        context = task.metadata.get("concurrency_context", {})
        if self.fixed_tier is not None:
            tier, reason = self.fixed_tier, f"Fixed-tier evaluation policy: {self.fixed_tier.value}."
        elif task.metadata.get("phase") == "triage":
            tier, reason = InferenceTier.NANO, "NANO summarizes compressed evidence; deterministic tooling already classifies clear failures."
        else:
            patterns = context.get("fingerprints", [])
            complex_locks = any(len(pattern.get("lock_orders", [])) > 2 for pattern in patterns)
            high_risk = context.get("high_risk", False)
            tier = InferenceTier.ULTRA if complex_locks or high_risk else InferenceTier.SUPER
            reason = ("ULTRA: high risk or more than two observed lock-order edges." if tier == InferenceTier.ULTRA else
                      "SUPER: reproducible execution failure with normalized evidence and no previous repair; primary repair tier.")
        return RoutingDecision(task_id=task.task_id, difficulty=TaskDifficulty.HARD,
                               risk=RiskLevel.HIGH if tier == InferenceTier.ULTRA else RiskLevel.MEDIUM,
                               confidence=0.85, selected_tier=tier, selected_provider=ProviderType.NEBIUS,
                               requires_external_knowledge=False, reason=reason)
