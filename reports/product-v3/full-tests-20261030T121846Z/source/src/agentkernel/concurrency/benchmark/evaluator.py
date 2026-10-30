from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from agentkernel.providers.base import InferenceProvider
from agentkernel.telemetry.recorder import TelemetryRecorder

from ..app import ConcurrencyBugHunter, ConcurrencyPolicy
from .loader import discover_tasks, load_task
from .metrics import summarize

MODES = ("nano-only", "super-only", "ultra-only", "adaptive")


async def evaluate(root: Path, *, policy: ConcurrencyPolicy | None = None, compiler: str | None = None,
                   static: bool = False, stress_runs: int | None = None, verification_runs: int | None = None,
                   provider: InferenceProvider | None = None, telemetry: TelemetryRecorder | None = None,
                   modes: tuple[str, ...] = MODES, progress: Callable[[str], None] | None = None) -> dict[str, object]:
    directories = discover_tasks(root)
    if not directories:
        raise ValueError("No task.json benchmarks found")
    if not modes or any(mode not in MODES for mode in modes):
        raise ValueError("Unsupported evaluation mode")
    # Validate all trusted configurations before beginning any execution.
    tasks = [load_task(path, compiler=compiler, static=static, stress_runs=stress_runs,
                       verification_runs=verification_runs) for path in directories]
    report: dict[str, object] = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Nebius Sandbox compilation/execution; model mode and measurement provenance are recorded per result.",
        "limitations": "Scripted mock comparisons validate orchestration only, not model quality or cost savings. Passing runs are not proof of correctness.",
        "configuration": {"baseline_runs_override": stress_runs, "verification_runs_override": verification_runs,
                          "tasks": [task.model_dump(mode="json", exclude={"environment"}) for task in tasks]},
        "modes": {}}
    for mode in modes:
        mode_policy = (policy or ConcurrencyPolicy()).model_copy(update={"mode": mode})
        jobs = []
        for task in tasks:
            if progress:
                progress(f"{mode}: {task.task_id}")
            job = await ConcurrencyBugHunter(provider, telemetry, mode_policy).run(task)
            jobs.append(job)
            if job.status == "execution_blocked":
                report["stopped_reason"] = "host_execution_policy_blocked"
                report["modes"][mode] = {"metrics": summarize(jobs), "jobs": [item.model_dump(mode="json") for item in jobs]}
                return report
        report["modes"][mode] = {"metrics": summarize(jobs), "jobs": [job.model_dump(mode="json") for job in jobs]}
    return report
