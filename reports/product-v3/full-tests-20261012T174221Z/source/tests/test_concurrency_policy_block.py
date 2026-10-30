import asyncio
from pathlib import Path

from agentkernel.concurrency.app import ConcurrencyBugHunter
from agentkernel.concurrency.benchmark.metrics import summarize
from agentkernel.concurrency.app import ConcurrencyJobResult
from agentkernel.concurrency.campaign.manager import StressCampaignManager
from agentkernel.concurrency.campaign.models import CampaignResult
from agentkernel.concurrency.compile.models import CompileResult
from agentkernel.concurrency.execution.models import ExecutionRun
from agentkernel.concurrency.models import ConcurrencyTask, VerificationConfig
from agentkernel.concurrency.sandbox.base import CommandResult
from agentkernel.concurrency.sandbox.local import LocalSandboxBackend
from agentkernel.concurrency.verification.concurrency_verifier import ConcurrencyVerifier
from agentkernel.core.models import TaskRequest, VerificationResult
from agentkernel.providers.local_rtx import LocalRTXProvider
from agentkernel.providers.mock_nebius import MockNebiusProvider
from agentkernel.router.rule_router import RuleBasedRouter
from agentkernel.runtime.kernel import AgentKernel
from agentkernel.telemetry.recorder import TelemetryRecorder


def task(tmp_path: Path) -> ConcurrencyTask:
    return ConcurrencyTask(task_id="blocked", workspace=tmp_path, source_files=["main.c"],
        build_command=["compiler"], run_command=["./app"], stress_runs=100,
        verification_config=VerificationConfig(stress_runs=100))


def failed_run(*, blocked: bool = False) -> ExecutionRun:
    return ExecutionRun(run_id="1", duration_ms=1, exit_code=None, stdout="", stderr="process could not start",
        timed_out=False, crashed=False, sanitizer_detected=False, classification="UNKNOWN_FAILURE",
        metadata={"error": "OSError", "execution_policy_blocked": blocked})


def test_host_block_stops_campaign_without_retry(tmp_path) -> None:
    class Runner:
        calls = 0
        async def run(self, *args):
            self.calls += 1
            return failed_run(blocked=True)
    runner = Runner()
    campaign = asyncio.run(StressCampaignManager(runner=runner).run(task(tmp_path), None))
    assert runner.calls == 1 and campaign.requested_runs == 100
    assert campaign.execution_blocked and campaign.infrastructure_failures == 1


def test_infrastructure_failure_is_not_false_fix_or_regression(tmp_path) -> None:
    class Compiler:
        async def compile(self, *args):
            return CompileResult(command=["compiler"], success=True, exit_code=0)
    class Campaigns:
        async def run(self, *args, **kwargs):
            return CampaignResult(task_id="blocked", runs=[failed_run()], counts={"UNKNOWN_FAILURE": 1})
    baseline = CampaignResult(task_id="baseline", runs=[], counts={})
    result = asyncio.run(ConcurrencyVerifier(Compiler(), Campaigns()).verify_workspace(task(tmp_path), None, baseline))
    assert not result.passed and result.infrastructure_failures == 1
    assert result.observed_program_failures == 0 and not result.regressions
    job = ConcurrencyJobResult(task="blocked", repairs=[{"patch": {"success": True}, "verification": result.model_dump()}])
    assert summarize([job])["false_fixes"] == 0
    assert summarize([job])["verification_infrastructure_failures"] == 1


def test_nonretryable_verifier_stops_runtime() -> None:
    class PolicyVerifier:
        async def verify(self, *args):
            return VerificationResult(passed=False, retryable=False, reason="Host policy denied execution", verifier_name="test")
    result = asyncio.run(AgentKernel(RuleBasedRouter(), LocalRTXProvider(), MockNebiusProvider(),
        TelemetryRecorder(), PolicyVerifier()).execute(TaskRequest(task_id="t", task_type="test", prompt="test failure")))
    assert len(result.attempts) == 1 and result.stopped_reason == "verification_not_retryable"


def test_blocked_compile_never_reaches_models(monkeypatch, tmp_path) -> None:
    calls = []
    async def blocked(self, command, **kwargs):
        calls.append(command)
        return CommandResult(command=command, metadata={"error": "OSError", "winerror": 4551, "execution_policy_blocked": True})
    monkeypatch.setattr(LocalSandboxBackend, "run_command", blocked)
    (tmp_path / "main.c").write_text("/* trusted test */")
    result = asyncio.run(ConcurrencyBugHunter().run(task(tmp_path)))
    assert len(calls) == 1 and result.status == "execution_blocked" and result.route == []


def test_os_policy_error_is_structured(monkeypatch) -> None:
    async def denied(*args, **kwargs):
        error = OSError(22, "policy blocked")
        error.winerror = 4551
        raise error
    monkeypatch.setattr(asyncio, "create_subprocess_exec", denied)
    async def run():
        async with LocalSandboxBackend() as sandbox:
            return await sandbox.run_command(["trusted-program"], timeout=1)
    result = asyncio.run(run())
    assert result.metadata["execution_policy_blocked"] and result.metadata["winerror"] == 4551


def test_benchmark_stops_all_modes_after_host_policy_denial(monkeypatch) -> None:
    from agentkernel.concurrency.benchmark.evaluator import evaluate
    calls = []
    async def blocked(self, task):
        calls.append(task.task_id)
        return ConcurrencyJobResult(task=task.task_id, status="execution_blocked")
    monkeypatch.setattr(ConcurrencyBugHunter, "run", blocked)
    report = asyncio.run(evaluate(Path(__file__).parents[1] / "benchmarks"))
    assert report["stopped_reason"] == "host_execution_policy_blocked"
    assert len(calls) == 1 and list(report["modes"]) == ["nano-only"]
