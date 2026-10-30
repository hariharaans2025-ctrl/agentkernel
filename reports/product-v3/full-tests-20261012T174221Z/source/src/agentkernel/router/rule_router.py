import re

from agentkernel.core.enums import InferenceTier, ProviderType, RiskLevel, TaskDifficulty
from agentkernel.core.models import RoutingDecision, TaskRequest
from .base import Router

# All v1 signals live here. Higher difficulty wins when signals overlap.
HARD_SIGNALS = ("race condition", "deadlock", "concurrency", "distributed",
                "memory corruption", "intermittent state", "cross-service")
MEDIUM_SIGNALS = ("failed assertion", "assertionerror", "api error", "api failure",
                  "dependency version conflict", "test failure", "version conflict")
EASY_SIGNALS = ("modulenotfounderror", "importerror", "formatting", "syntax typo",
                "syntaxerror", "lint failure")
EXTERNAL_SIGNALS = ("deprecated", "api changed", "migration", "sdk version", "breaking change")
STACK_FRAME = re.compile(r'^\s*File ".+", line \d+', re.MULTILINE | re.IGNORECASE)


class RuleBasedRouter(Router):
    async def route(self, task: TaskRequest) -> RoutingDecision:
        prompt = task.prompt.lower()
        external = any(signal in prompt for signal in EXTERNAL_SIGNALS)
        frames = len(STACK_FRAME.findall(task.prompt))
        if any(signal in prompt for signal in HARD_SIGNALS):
            difficulty, risk, tier, confidence = TaskDifficulty.HARD, RiskLevel.HIGH, InferenceTier.ULTRA, 0.95
            reason = "Complex state or concurrency signal requires the strongest simulated tier."
        elif any(signal in prompt for signal in MEDIUM_SIGNALS) or external or frames >= 2:
            difficulty, risk, confidence = TaskDifficulty.MEDIUM, RiskLevel.MEDIUM, 0.80
            tier = InferenceTier.SUPER if external or frames >= 2 or "version conflict" in prompt else InferenceTier.NANO
            reason = "Version, API, or multi-frame issue." if tier == InferenceTier.SUPER else "Routine test or assertion failure."
        elif any(signal in prompt for signal in EASY_SIGNALS):
            difficulty, risk, tier, confidence = TaskDifficulty.EASY, RiskLevel.LOW, InferenceTier.LOCAL, 0.93
            reason = "Simple dependency, syntax, or formatting failure suitable for local inference."
        else:
            difficulty, risk, tier, confidence = TaskDifficulty.UNKNOWN, RiskLevel.MEDIUM, InferenceTier.NANO, 0.40
            reason = "No known signal; start with the smallest simulated remote tier."
        if task.privacy_sensitive and difficulty != TaskDifficulty.HARD:
            tier = InferenceTier.LOCAL
            reason += " Privacy preference selects local inference for a non-hard task."
        elif task.privacy_sensitive:
            reason += " Hard-task policy retains ULTRA despite the soft privacy preference."
        return RoutingDecision(
            task_id=task.task_id, difficulty=difficulty, risk=risk, confidence=confidence,
            selected_tier=tier,
            selected_provider=ProviderType.LOCAL_RTX if tier == InferenceTier.LOCAL else ProviderType.NEBIUS,
            requires_external_knowledge=external, reason=reason,
        )
