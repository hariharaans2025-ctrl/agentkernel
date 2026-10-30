import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from agentkernel.concurrency.app import ConcurrencyBugHunter, ConcurrencyPolicy
from agentkernel.concurrency.benchmark.loader import load_task
from agentkernel.concurrency.models import ConcurrencyTask, VerificationConfig
from agentkernel.concurrency.mock_inference import mock_concurrency_response
from agentkernel.concurrency.repair.patch_applier import UnifiedDiffApplier
from agentkernel.concurrency.repair.patch_parser import parse_repair, validation_details
from agentkernel.concurrency.repair.source_edits import EditError
from agentkernel.providers.mock_nebius import MockNebiusProvider


def response(edits, **extra):
    return json.dumps(dict(diagnosis="Candidate for execution testing", root_cause="Blocking synchronization",
        confidence=0.9, expected_effect="Complete without blocking", risk_notes=[], edits=edits, **extra))


def edit(search, replacement, file="main.c"):
    return dict(file=file, search=search, replacement=replacement)


@pytest.mark.parametrize("old,new", [
    ('printf("old\\n");\n', 'printf("new\\n");\n'),
    ('first\nlast', 'first\nchanged'),
    ('first\nlast', 'first\nchanged\n'),
    ('first\nlast\n', 'first\nchanged'),
])
def test_generated_diff_roundtrips_exact_content_and_eof(tmp_path, old, new):
    (tmp_path / "main.c").write_text(old, newline="")
    proposal = parse_repair(response([edit(old, new)]), {"main.c": old})
    assert UnifiedDiffApplier().apply(tmp_path, proposal.patch, ["main.c"]).success
    assert (tmp_path / "main.c").read_text() == new


def test_multiple_original_blocks_and_files_apply_atomically(tmp_path):
    sources = {"main.c": "one\ntwo\nthree\n", "other.h": "#define X 1\n"}
    for name, source in sources.items():
        (tmp_path / name).write_text(source)
    proposal = parse_repair(response([edit("three", "THREE"), edit("one", "ONE"),
        edit("#define X 1", "#define X 2", "other.h")]), sources)
    assert UnifiedDiffApplier().apply(tmp_path, proposal.patch, list(sources)).success
    assert (tmp_path / "main.c").read_text() == "ONE\ntwo\nTHREE\n"
    assert (tmp_path / "other.h").read_text() == "#define X 2\n"


@pytest.mark.parametrize("edits,sources,code", [
    ([edit("missing", "new")], {"main.c": "original"}, "edit_search_not_found"),
    ([edit("aaa", "new")], {"main.c": "aaaa"}, "edit_search_ambiguous"),
    ([edit("old", "old")], {"main.c": "old"}, "edit_no_change"),
    ([edit("ab", "x"), edit("bc", "y")], {"main.c": "abc"}, "edit_overlap"),
    ([edit("old", "new"), edit("new", "final")], {"main.c": "old"}, "edit_search_not_found"),
    ([edit('printf("x\\\\n");', 'replacement')], {"main.c": 'printf("x\\n");'}, "edit_search_not_found"),
])
def test_rejects_ambiguous_stale_overlapping_and_double_escaped_edits(edits, sources, code):
    snapshot = dict(sources)
    with pytest.raises(EditError) as caught:
        parse_repair(response(edits), sources)
    assert caught.value.code == code and sources == snapshot
    detail = validation_details(caught.value)[0]
    assert detail["type"] == code and detail["hint"]


@pytest.mark.parametrize("name", ["../main.c", "/tmp/main.c", "C:/main.c", "sub/../main.c", "x\n.c", ".env", "test.py"])
def test_rejects_unsafe_edits_even_if_present_in_context(name):
    with pytest.raises(EditError, match="allowlisted"):
        parse_repair(response([edit("old", "new", name)]), {name: "old"})


def test_no_source_and_mixed_response_fail_closed():
    with pytest.raises(EditError):
        parse_repair(response([edit("x", "y")]))
    with pytest.raises(ValueError):
        parse_repair(response([edit("x", "y")], patch="--- a/main.c\n"), {"main.c": "x"})


def test_invalid_edits_correct_once_then_execute_with_original_evidence(tmp_path):
    (tmp_path / "main.c").write_text("print('FAIL')\n")
    task = ConcurrencyTask(task_id="edits", workspace=tmp_path, source_files=["main.c"],
        build_command=[sys.executable, "-c", "pass"], run_command=[sys.executable, "main.c"],
        max_runtime_seconds=5, stress_runs=1, verification_config=VerificationConfig(stress_runs=2))
    calls = []
    def model(request, route):
        if request.metadata["phase"] == "triage":
            return mock_concurrency_response(request, route)
        calls.append(request.prompt)
        return response([edit("stale source" if len(calls) == 1 else "print('FAIL')", "print('PASS')")])
    result = asyncio.run(ConcurrencyBugHunter(MockNebiusProvider(model),
        policy=ConcurrencyPolicy(max_super_repairs=1, allow_contract_retry=True)).run(task))
    assert result.status == "verified" and result.route == ["NANO", "SUPER", "SUPER"]
    assert "edit_search_not_found" in calls[1] and "Copy search blocks" in calls[1]
    assert result.repairs[0]["proposal"]["patch"].startswith("--- a/main.c\n")
    assert (tmp_path / "main.c").read_text() == "print('FAIL')\n"


@pytest.mark.parametrize("body,code", [
    ("@@\n int n = 0;\n", "missing_hunks"),
    ("@@ -1 +1 @@\n-int n = 999;\n+int n = 1;\n", "context_mismatch"),
])
def test_recorded_failure_shapes_have_actionable_hints(tmp_path, body, code):
    (tmp_path / "main.c").write_text("int n = 0;\n")
    applied = UnifiedDiffApplier().apply(tmp_path, "--- a/main.c\n+++ b/main.c\n" + body, ["main.c"])
    assert not applied.success and applied.error_code == code and applied.repair_hint
    assert (tmp_path / "main.c").read_text() == "int n = 0;\n"


def test_smoke_rejects_diff_headers_without_hunks():
    from agentkernel.core.models import TaskRequest
    from agentkernel.core.enums import InferenceTier
    from agentkernel.concurrency.analyzer.routing import ConcurrencyRouter
    from agentkernel.concurrency.smoke import RepairContractVerifier
    from agentkernel.providers.local_rtx import LocalRTXProvider
    from agentkernel.runtime.kernel import AgentKernel
    from agentkernel.telemetry.recorder import TelemetryRecorder
    payload = json.loads(response([edit("x", "y")]))
    del payload["edits"]
    payload["patch"] = "--- a/main.c\n+++ b/main.c\n@@\n-x\n+y\n"
    task = TaskRequest(task_id="bad-diff", task_type="repair", prompt="repair", metadata={
        "phase": "repair", "concurrency_context": {"sources": {"main.c": "x\n"}}})
    result = asyncio.run(AgentKernel(ConcurrencyRouter(InferenceTier.SUPER), LocalRTXProvider(),
        MockNebiusProvider(lambda *args: json.dumps(payload)), TelemetryRecorder(), RepairContractVerifier()).execute(task))
    assert not result.success and result.stopped_reason == "invalid_model_output"
    assert len(result.attempts) == 2
    assert result.attempts[0].verification_evidence["patch_validation"]["error_code"] == "missing_hunks"


@pytest.mark.integration
def test_native_barrier_false_fix_fails_then_exact_edits_pass(tmp_path):
    compiler = os.getenv("AK_TEST_CC")
    if not compiler:
        pytest.skip("Set AK_TEST_CC for real native verification")
    benchmark = Path(__file__).parents[1] / "benchmarks/deadlock_001"
    task = load_task(benchmark, compiler=compiler, static=os.name == "nt", stress_runs=1, verification_runs=10)
    original = (benchmark / "main.c").read_text()
    snapshot = (benchmark / "main.c").read_bytes()
    calls = []
    def model(request, route):
        if request.metadata["phase"] == "triage":
            return mock_concurrency_response(request, route)
        calls.append(request.prompt)
        # First response repeats the historical semantic error despite valid formatting.
        edits = [edit("pthread_mutex_t *first = id == 1 ? &a : &b;", "pthread_mutex_t *first = &a;"),
                 edit("pthread_mutex_t *second = id == 1 ? &b : &a;", "pthread_mutex_t *second = &b;")]
        if len(calls) > 1:
            edits += [edit("    pthread_barrier_wait(&ready);\n", ""),
                      edit("    pthread_mutex_lock(first);", "    pthread_barrier_wait(&ready);\n    pthread_mutex_lock(first);")]
        return response(edits)
    result = asyncio.run(ConcurrencyBugHunter(MockNebiusProvider(model), temporary_parent=tmp_path).run(task))
    destination = os.getenv("AK_PATCH_QUALITY_REPORT")
    if destination:
        Path(destination).write_text(result.model_dump_json(indent=2), encoding="utf-8")
    if result.status == "execution_blocked":
        pytest.skip("Host policy blocked execution; no bypass or retry")
    assert result.status == "verified", result.model_dump_json()
    assert result.route == ["NANO", "SUPER", "SUPER"]
    assert result.repairs[0]["patch"]["success"]
    assert result.repairs[0]["verification"]["deadlock_count"] == 10
    assert result.verification["passed_runs"] == 10 and result.verification["failed_runs"] == 0
    assert "deadlock_count" in calls[-1]
    assert (benchmark / "main.c").read_bytes() == snapshot
