import asyncio
import sys
from pathlib import Path

import pytest

from agentkernel.concurrency.analyzer.classifier import classify
from agentkernel.concurrency.campaign.manager import StressCampaignManager
from agentkernel.concurrency.campaign.scheduler import StressSchedule
from agentkernel.concurrency.models import ConcurrencyTask
from agentkernel.concurrency.sandbox.base import CommandResult
from agentkernel.concurrency.sandbox.local import LocalSandboxBackend


@pytest.mark.parametrize(("code", "stdout", "stderr", "timeout", "kind"), [
    (0, "PASS", "", False, "PASS"), (-11, "", "", False, "CRASH"),
    (None, "", "", True, "TIMEOUT"), (None, "T1 WAIT A", "", True, "POSSIBLE_DEADLOCK"),
    (1, "", "assertion failed", False, "ASSERTION_FAILURE"), (0, "wrong", "", False, "UNKNOWN_FAILURE"),
])
def test_classification(code: int | None, stdout: str, stderr: str, timeout: bool, kind: str) -> None:
    result = CommandResult(command=["trusted"], exit_code=code, stdout=stdout, stderr=stderr, timed_out=timeout)
    assert classify(result, "PASS").value == kind


def test_real_repeated_runs(tmp_path: Path) -> None:
    task = ConcurrencyTask(task_id="repeat", workspace=tmp_path, source_files=["main.c"],
                           build_command=["gcc"], run_command=[sys.executable, "-c", "print('PASS')"],
                           stress_runs=3, max_runtime_seconds=5)
    async def run() -> None:
        async with LocalSandboxBackend() as sandbox:
            result = await StressCampaignManager().run(task, sandbox)
        assert result.counts == {"PASS": 3}
        assert result.failed_runs == 0
        assert len({run.run_id for run in result.runs}) == 3
    asyncio.run(run())


def test_seeded_perturbation() -> None:
    schedule = StressSchedule(seed=12)
    assert schedule.environment_for(1) == schedule.environment_for(1)
    assert schedule.environment_for(1) != schedule.environment_for(2)
