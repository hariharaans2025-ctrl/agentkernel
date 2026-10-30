import asyncio
import sys
from pathlib import Path

from agentkernel.concurrency.campaign.manager import StressCampaignManager
from agentkernel.concurrency.models import ConcurrencyTask, VerificationConfig
from agentkernel.concurrency.sandbox.local import LocalSandboxBackend
from agentkernel.concurrency.verification.concurrency_verifier import ConcurrencyVerifier


def test_real_verification_baseline_and_regression(tmp_path: Path) -> None:
    task = ConcurrencyTask(task_id="v", workspace=tmp_path, source_files=["main.c"],
                           build_command=[sys.executable, "-c", "pass"],
                           run_command=[sys.executable, "-c", "print('bad')"], stress_runs=1,
                           max_runtime_seconds=5, verification_config=VerificationConfig(stress_runs=2))
    async def run() -> None:
        async with LocalSandboxBackend() as sandbox:
            baseline = await StressCampaignManager().run(task, sandbox)
            assert baseline.failed_runs == 1
            task.run_command = [sys.executable, "-c", "print('PASS')"]
            verified = await ConcurrencyVerifier().verify_workspace(task, sandbox, baseline)
            assert verified.passed and verified.passed_runs == 2
            clean = await StressCampaignManager().run(task, sandbox)
            task.run_command = [sys.executable, "-c", "print('wrong')"]
            regression = await ConcurrencyVerifier().verify_workspace(task, sandbox, clean)
            assert not regression.passed and regression.regressions
    asyncio.run(run())


def test_required_tests_cannot_be_omitted(tmp_path: Path) -> None:
    task = ConcurrencyTask(task_id="v", workspace=tmp_path, source_files=["main.c"],
                           build_command=[sys.executable, "-c", "pass"], run_command=[sys.executable, "-c", "print('PASS')"],
                           max_runtime_seconds=5, verification_config=VerificationConfig(stress_runs=1, required_original_tests=True))
    async def run() -> None:
        async with LocalSandboxBackend() as sandbox:
            verified = await ConcurrencyVerifier().verify_workspace(task, sandbox)
        assert not verified.passed
        assert "Original test requirements failed" in verified.regressions
    asyncio.run(run())
