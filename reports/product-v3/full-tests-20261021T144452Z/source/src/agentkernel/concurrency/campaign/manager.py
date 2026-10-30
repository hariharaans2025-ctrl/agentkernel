from collections import Counter
from time import perf_counter

from ..execution.runner import ExecutionRunner
from ..models import ConcurrencyTask
from ..sandbox.base import SandboxBackend
from .models import CampaignResult
from .scheduler import StressSchedule
from ..progress import campaign_progress


class StressCampaignManager:
    def __init__(self, runner: ExecutionRunner | None = None, schedule: StressSchedule | None = None) -> None:
        self.runner = runner or ExecutionRunner()
        self.schedule = schedule or StressSchedule()

    async def run(self, task: ConcurrencyTask, sandbox: SandboxBackend, *, runs: int | None = None) -> CampaignResult:
        started = perf_counter()
        count = task.stress_runs if runs is None else runs
        if count < 1 or count > 10000:
            raise ValueError("Campaign requires 1..10000 runs")
        records = []
        for index in range(count):
            run = await self.runner.run(task, sandbox, f"{task.task_id}:{index + 1}", self.schedule.environment_for(index))
            records.append(run)
            campaign_progress(len(records), count)
            if run.metadata.get("execution_policy_blocked"):
                break  # Respect the host's denial; do not retry the blocked binary.
        return CampaignResult(task_id=task.task_id, runs=records,
                              requested_runs=count,
                              counts=dict(Counter(run.classification.value for run in records)),
                              duration_ms=(perf_counter() - started) * 1000)
