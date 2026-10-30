import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from agentkernel.concurrency.app import ConcurrencyBugHunter, ConcurrencyJobResult
from agentkernel.concurrency.benchmark.loader import discover_tasks, load_task
from agentkernel.concurrency.benchmark.metrics import summarize
from agentkernel.concurrency.compile.compiler import CCompiler
from agentkernel.concurrency.campaign.manager import StressCampaignManager
from agentkernel.concurrency.models import ConcurrencyTask, VerificationConfig
from agentkernel.concurrency.sandbox.local import LocalSandboxBackend

ROOT = Path(__file__).parents[1] / "benchmarks"


def test_suite_has_five_distinct_races_and_deadlocks() -> None:
    tasks = [load_task(path) for path in discover_tasks(ROOT)]
    assert len(tasks) == 10
    assert sum(task.expected_bug_category == "race" for task in tasks) == 5
    assert sum(task.expected_bug_category == "deadlock" for task in tasks) == 5
    assert len({(task.workspace / "main.c").read_text() for task in tasks}) == 10
    assert all(task.verification_config.sanitizer_required for task in tasks if task.expected_bug_category == "race")


@pytest.mark.parametrize("name", ["../escape.c", "C:/escape.c", "reference.patch", ".env"])
def test_loader_rejects_escape_and_evaluation_leaks(tmp_path: Path, name: str) -> None:
    data = json.loads((ROOT / "deadlock_001/task.json").read_text())
    data["source_files"] = [name]
    (tmp_path / "task.json").write_text(json.dumps(data))
    if "/" not in name:
        (tmp_path / name).write_text("do not expose")
    with pytest.raises(ValueError):
        load_task(tmp_path)


def test_false_fix_metrics_and_mock_measurement_provenance() -> None:
    job = ConcurrencyJobResult(task="test", status="unresolved", cost_usd=1,
        model_calls={"SUPER": 2}, repairs=[
            {"proposal": {"diagnosis": "cause"}, "patch": {"success": True},
             "verification": {"passed": False, "failed_runs": 5}},
            {"proposal": {"diagnosis": "cause"}, "patch": {"success": False}},
        ])
    summary = summarize([job])
    # Applied-and-evaluated denominator excludes the patch rejection.
    assert summary["false_fixes"] == 1 and summary["false_fix_rate"] == 1
    assert summary["patches_rejected"] == 1 and summary["verified_repairs"] == 0
    assert summary["cost_usd"] is None and summary["inference_measurement"] == "simulated"
    assert summary["average_model_calls"] == 2
    assert summarize([])["false_fix_rate"] is None


def test_missing_required_sanitizer_cannot_be_verified(tmp_path: Path) -> None:
    (tmp_path / "main.c").write_text("fixture")
    task = ConcurrencyTask(task_id="required", workspace=tmp_path, source_files=["main.c"],
        build_command=[sys.executable, "-c", "pass"], run_command=[sys.executable, "-c", "print('PASS')"],
        stress_runs=1, max_runtime_seconds=5,
        verification_config=VerificationConfig(stress_runs=1, sanitizer_required=True))
    # Python cannot accept -fsanitize=thread; this uses real subprocess failure.
    result = asyncio.run(ConcurrencyBugHunter().run(task))
    assert result.status == "tooling_unavailable" and not result.route
    assert result.baseline["sanitizer"]["status"] == "unavailable"


@pytest.mark.integration
def test_all_c_fixtures_compile_and_deadlocks_reproduce() -> None:
    compiler = os.getenv("AK_TEST_CC")
    if not compiler:
        pytest.skip("Set AK_TEST_CC to gcc/clang")
    async def run() -> None:
        for folder in discover_tasks(ROOT):
            task = load_task(folder, compiler=compiler, static=os.name == "nt", stress_runs=1)
            async with LocalSandboxBackend() as sandbox:
                await sandbox.upload_project(task.workspace, task.source_files + task.support_files)
                build = await CCompiler().compile(task, sandbox)
                if build.metadata.get("execution_policy_blocked"):
                    pytest.skip("Host execution policy blocks the compiler")
                assert build.success, build.stderr
                campaign = await StressCampaignManager().run(task, sandbox)
                if campaign.execution_blocked:
                    pytest.skip("Host execution policy blocks generated native programs")
                if task.expected_bug_category == "deadlock":
                    assert campaign.runs[0].timed_out
    asyncio.run(run())


@pytest.mark.integration
def test_real_tsan_counter_repair() -> None:
    compiler = os.getenv("AK_TEST_TSAN_CC")
    if not compiler:
        pytest.skip("Set AK_TEST_TSAN_CC only on a supported ThreadSanitizer host")
    task = load_task(ROOT / "race_001", compiler=compiler)
    result = asyncio.run(ConcurrencyBugHunter().run(task))
    if result.status == "execution_blocked":
        pytest.skip("Host execution policy blocks generated native programs")
    assert result.baseline["sanitizer"]["campaign"]["counts"].get("RACE_DETECTED", 0) > 0
    assert result.status == "verified"
    assert result.verification["passed_runs"] == 100
    assert result.verification["evidence"]["sanitizer"]["status"] == "passed"
