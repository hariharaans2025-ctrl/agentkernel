from pydantic import BaseModel, Field

from ..execution.models import ExecutionRun


class CampaignResult(BaseModel):
    task_id: str
    runs: list[ExecutionRun] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    duration_ms: float = 0
    requested_runs: int | None = None

    @property
    def failed_runs(self) -> int:
        return len(self.runs) - self.counts.get("PASS", 0)

    @property
    def infrastructure_failures(self) -> int:
        return sum(bool(run.metadata.get("error")) for run in self.runs)

    @property
    def execution_blocked(self) -> bool:
        return any(run.metadata.get("execution_policy_blocked", False) for run in self.runs)

    def compact(self) -> dict[str, object]:
        failing = [run for run in self.runs if run.classification.value != "PASS"]
        return {"total_runs": len(self.runs), "failed_runs": self.failed_runs,
                "infrastructure_failures": self.infrastructure_failures,
                "requested_runs": self.requested_runs, "execution_blocked": self.execution_blocked,
                "counts": self.counts, "duration_ms": self.duration_ms,
                "representative_runs": [{"run_id": run.run_id, "classification": run.classification.value,
                                         "exit_code": run.exit_code, "timed_out": run.timed_out,
                                         "metadata": run.metadata,
                                         "stdout": run.stdout[:2000], "stderr": run.stderr[:2000]}
                                        for run in failing[:3]]}
