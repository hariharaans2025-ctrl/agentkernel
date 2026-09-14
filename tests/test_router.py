import asyncio

import pytest
from pydantic import ValidationError

from agentkernel.core.enums import InferenceTier, TaskDifficulty
from agentkernel.core.models import TaskRequest
from agentkernel.router.rule_router import RuleBasedRouter


@pytest.mark.parametrize(("prompt", "tier"), [
    ("ModuleNotFoundError: No module named requests", InferenceTier.LOCAL),
    ("Race condition between worker threads", InferenceTier.ULTRA),
    ("Failed assertion in test", InferenceTier.NANO),
    ("Dependency version conflict", InferenceTier.SUPER),
    ('File "a.py", line 1\nFile "b.py", line 2', InferenceTier.SUPER),
    ("ImportError caused by distributed deadlock", InferenceTier.ULTRA),
])
def test_routing(prompt: str, tier: InferenceTier) -> None:
    task = TaskRequest(task_id="t", task_type="ci_failure", prompt=prompt)
    route = asyncio.run(RuleBasedRouter().route(task))
    assert route.selected_tier == tier
    assert 0 <= route.confidence <= 1
    assert route == asyncio.run(RuleBasedRouter().route(task))


def test_external_knowledge() -> None:
    route = asyncio.run(RuleBasedRouter().route(TaskRequest(
        task_id="t", task_type="ci_failure", prompt="Deprecated SDK API")))
    assert route.requires_external_knowledge is True


@pytest.mark.parametrize("prompt", ["Test failure", "Deprecated SDK API", "Something unfamiliar"])
def test_privacy_prefers_local(prompt: str) -> None:
    route = asyncio.run(RuleBasedRouter().route(TaskRequest(
        task_id="t", task_type="ci_failure", prompt=prompt, privacy_sensitive=True)))
    assert route.selected_tier == InferenceTier.LOCAL


def test_hard_privacy_is_soft_preference() -> None:
    route = asyncio.run(RuleBasedRouter().route(TaskRequest(
        task_id="t", task_type="ci_failure", prompt="Deadlock", privacy_sensitive=True)))
    assert route.selected_tier == InferenceTier.ULTRA


def test_unknown_fallback() -> None:
    route = asyncio.run(RuleBasedRouter().route(TaskRequest(
        task_id="t", task_type="general", prompt="Something unfamiliar")))
    assert route.difficulty == TaskDifficulty.UNKNOWN
    assert route.confidence == 0.4


def test_negative_budget_rejected() -> None:
    with pytest.raises(ValidationError):
        TaskRequest(task_id="t", task_type="general", prompt="Hi", max_cost_usd=-1)
