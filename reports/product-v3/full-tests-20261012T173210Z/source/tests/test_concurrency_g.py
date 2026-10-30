import asyncio
import difflib
import json
import os
from pathlib import Path

import pytest

from agentkernel.core.enums import InferenceTier
from agentkernel.core.models import TaskRequest
from agentkernel.concurrency.analyzer.routing import ConcurrencyRouter
from agentkernel.concurrency.app import ConcurrencyBugHunter, ConcurrencyPolicy
from agentkernel.concurrency.models import ConcurrencyTask
from agentkernel.concurrency.mock_inference import mock_concurrency_response
from agentkernel.concurrency.repair.patch_parser import parse_repair
from agentkernel.concurrency.verification.repair_verifier import TriageVerifier
from agentkernel.providers.local_rtx import LocalRTXProvider
from agentkernel.providers.mock_nebius import MockNebiusProvider
from agentkernel.runtime.kernel import AgentKernel
from agentkernel.telemetry.recorder import TelemetryRecorder

BENCHMARK = Path(__file__).parents[1] / "benchmarks/deadlock_001"


def test_nano_contract_retry_once() -> None:
    calls = []
    def response(task: TaskRequest, route: object) -> str:
        calls.append(task.prompt)
        return "malformed" if len(calls) == 1 else mock_concurrency_response(task, route)
    task = TaskRequest(task_id="triage", task_type="concurrency", prompt="summarize",
                       metadata={"phase": "triage", "concurrency_context": {
                           "baseline": {"total_runs": 1, "failed_runs": 1, "representative_runs": []}}})
    result = asyncio.run(AgentKernel(ConcurrencyRouter(), LocalRTXProvider(), MockNebiusProvider(response),
                                     TelemetryRecorder(), TriageVerifier(), max_attempts=2,
                                     tier_schedule=(InferenceTier.NANO, InferenceTier.NANO)).execute(task))
    assert result.success and len(calls) == 2
    assert "Malformed triage" in calls[1]


def test_super_default_ultra_for_complex_evidence() -> None:
    task = TaskRequest(task_id="repair", task_type="concurrency", prompt="repair", metadata={"phase": "repair"})
    assert asyncio.run(ConcurrencyRouter().route(task)).selected_tier == InferenceTier.SUPER
    task.metadata["concurrency_context"] = {"high_risk": True}
    assert asyncio.run(ConcurrencyRouter().route(task)).selected_tier == InferenceTier.ULTRA


def test_repair_rejects_model_commands() -> None:
    with pytest.raises(ValueError):
        parse_repair(json.dumps({"commands": ["rm -rf /"], "patch": "echo hi"}))


@pytest.mark.integration
def test_real_c_deadlock_repaired_and_ultra_has_evidence(tmp_path: Path) -> None:
    compiler = os.getenv("AK_TEST_CC")
    if not compiler:
        pytest.skip("Set AK_TEST_CC to a gcc/clang executable")
    data = json.loads((BENCHMARK / "task.json").read_text())
    task = ConcurrencyTask(workspace=BENCHMARK, **data)
    task.build_command[0] = compiler
    if os.name == "nt":
        task.build_command.insert(1, "-static")
    snapshot = (BENCHMARK / "main.c").read_bytes()
    calls = []
    def response(request: TaskRequest, routing: object) -> str:
        calls.append(request)
        output = mock_concurrency_response(request, routing)
        if request.metadata["phase"] == "repair" and routing.selected_tier == InferenceTier.SUPER:
            proposal = json.loads(output)
            proposal["patch"] = proposal["patch"].replace("static pthread_barrier_t ready;", "not the original context")
            # An invalid context is deterministic failure evidence for both SUPER attempts.
            proposal["patch"] = proposal["patch"].replace("int id = (int)(intptr_t)arg;", "int id = 999;")
            output = json.dumps(proposal)
        return output
    recorder = TelemetryRecorder()
    app = ConcurrencyBugHunter(MockNebiusProvider(response), recorder, temporary_parent=tmp_path)
    result = asyncio.run(app.run(task))
    if result.status == "execution_blocked":
        pytest.skip("Host Application Control blocked the generated program; native integration is unavailable")
    if result.status != "verified":
        pytest.fail(json.dumps({"status": result.status, "repairs": result.repairs}, indent=2))
    assert result.route == ["NANO", "SUPER", "SUPER", "ULTRA"]
    assert "Patch rejected" in calls[-1].prompt
    assert result.verification["passed_runs"] == 100
    assert result.baseline["failed_runs"] == task.stress_runs
    assert (BENCHMARK / "main.c").read_bytes() == snapshot
    assert recorder.all_events[-1].event_type == "concurrency_job"
    assert not list(tmp_path.iterdir())


@pytest.mark.integration
def test_applied_false_fix_executes_fails_then_ultra_repairs(tmp_path: Path) -> None:
    from agentkernel.concurrency.benchmark.loader import load_task
    from agentkernel.concurrency.benchmark.metrics import summarize
    from agentkernel.concurrency.repair.patch_applier import UnifiedDiffApplier
    compiler = os.getenv("AK_TEST_CC")
    if not compiler:
        pytest.skip("Set AK_TEST_CC to a gcc/clang executable")
    task = load_task(BENCHMARK, compiler=compiler, static=os.name == "nt", stress_runs=1)
    original = (BENCHMARK / "main.c").read_text()
    seen = []
    def response(request: TaskRequest, routing: object) -> str:
        seen.append(request)
        output = mock_concurrency_response(request, routing)
        if request.metadata["phase"] == "repair" and routing.selected_tier == InferenceTier.SUPER:
            proposal = json.loads(output)
            # Build a syntactically valid, applied patch that removes the deadlock
            # but introduces a real functional regression. No verification is mocked.
            scratch = tmp_path / "candidate"
            scratch.mkdir(exist_ok=True)
            (scratch / "main.c").write_text(original)
            assert UnifiedDiffApplier().apply(scratch, proposal["patch"], ["main.c"]).success
            broken = (scratch / "main.c").read_text().replace('puts("PASS");', 'puts("REGRESSION");')
            proposal["patch"] = "".join(difflib.unified_diff(original.splitlines(True), broken.splitlines(True),
                                                           fromfile="a/main.c", tofile="b/main.c"))
            return json.dumps(proposal)
        return output
    result = asyncio.run(ConcurrencyBugHunter(MockNebiusProvider(response),
        policy=ConcurrencyPolicy(max_super_repairs=1)).run(task))
    if result.status == "execution_blocked":
        pytest.skip("Host Application Control blocked the generated program; native integration is unavailable")
    assert result.route == ["NANO", "SUPER", "ULTRA"]
    assert result.repairs[0]["patch"]["success"]
    assert result.repairs[0]["verification"]["failed_runs"] == 100
    assert result.repairs[0]["verification"]["regressions"]
    assert result.status == "verified", result.model_dump_json()
    assert result.verification["passed_runs"] == 100
    assert "REGRESSION" in seen[-1].prompt and "failed_runs" in seen[-1].prompt
    assert summarize([result])["false_fixes"] == 1
    assert (BENCHMARK / "main.c").read_text() == original
