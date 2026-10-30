from datetime import datetime, timezone

from ..analyzer.classifier import classify
from ..models import ConcurrencyTask
from ..sandbox.base import SandboxBackend
from .models import ExecutionRun, RunClassification


class ExecutionRunner:
    async def run(self, task: ConcurrencyTask, sandbox: SandboxBackend, run_id: str,
                  environment: dict[str, str] | None = None) -> ExecutionRun:
        started = datetime.now(timezone.utc)
        result = await sandbox.run_command(task.run_command, timeout=task.max_runtime_seconds,
                                          environment={**task.environment, **(environment or {})})
        kind = classify(result, task.expected_behavior)
        return ExecutionRun(
            run_id=run_id, start_time=started, duration_ms=result.duration_ms, exit_code=result.exit_code,
            stdout=result.stdout, stderr=result.stderr, timed_out=result.timed_out,
            crashed=kind == RunClassification.CRASH,
            sanitizer_detected=kind in {RunClassification.RACE_DETECTED, RunClassification.SANITIZER_FAILURE},
            classification=kind, metadata=result.metadata,
        )
