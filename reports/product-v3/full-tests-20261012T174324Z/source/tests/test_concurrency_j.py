import json
import sys
from pathlib import Path

import pytest

from agentkernel.cli import main
from agentkernel.concurrency.analyzer.fingerprints import lock_graph
from agentkernel.concurrency.analyzer.trace_parser import TimelineEvent


def project(tmp_path: Path, output: str = "PASS") -> Path:
    folder = tmp_path / "fixture"
    folder.mkdir()
    (folder / "main.c").write_text("/* Test fixture */")
    (folder / "task.json").write_text(json.dumps({"task_id": "cli-test", "source_files": ["main.c"],
        "build_command": [sys.executable, "-c", "pass"],
        "run_command": [sys.executable, "-c", f"print({output!r})"], "stress_runs": 1,
        "max_runtime_seconds": 5, "verification_config": {"stress_runs": 1}}))
    return folder


def test_cli_json_and_telemetry(monkeypatch, tmp_path, capsys) -> None:
    folder = project(tmp_path)
    report, events = tmp_path / "report.json", tmp_path / "events.jsonl"
    monkeypatch.setattr(sys, "argv", ["agentkernel", "concurrency", "run", str(folder), "--json",
                                     "--json-output", str(report), "--telemetry-jsonl", str(events)])
    with pytest.raises(SystemExit) as stopped:
        main()
    assert stopped.value.code == 0
    result = json.loads(capsys.readouterr().out)
    assert result == json.loads(report.read_text())
    assert result["status"] == "baseline_clean" and result["route"] == []
    assert json.loads(events.read_text())["event_type"] == "concurrency_job"
    assert (folder / "main.c").read_text() == "/* Test fixture */"


def test_cli_bad_config_structured_error(monkeypatch, tmp_path, capsys) -> None:
    folder = project(tmp_path)
    monkeypatch.setattr(sys, "argv", ["agentkernel", "concurrency", "run", str(folder), "--stress-runs", "0", "--json"])
    with pytest.raises(SystemExit) as stopped:
        main()
    assert stopped.value.code == 2
    assert json.loads(capsys.readouterr().out)["status"] == "error"


def test_cli_models_no_key_no_network(monkeypatch, capsys) -> None:
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", ["agentkernel", "concurrency", "models"])
    with pytest.raises(SystemExit) as stopped:
        main()
    assert stopped.value.code == 1
    assert json.loads(capsys.readouterr().out)["error"] == "missing_api_key"


def test_cli_all_comparison_modes(monkeypatch, tmp_path, capsys) -> None:
    folder = project(tmp_path, output="failure")
    monkeypatch.setattr(sys, "argv", ["agentkernel", "concurrency", "benchmark", str(folder), "--json", "--max-attempts", "2"])
    with pytest.raises(SystemExit) as stopped:
        main()
    assert stopped.value.code == 0
    report = json.loads(capsys.readouterr().out)
    assert set(report["modes"]) == {"nano-only", "super-only", "ultra-only", "adaptive"}
    for mode in report["modes"].values():
        assert mode["metrics"]["verified_repairs"] == 0
        assert mode["metrics"]["cost_usd"] is None
        assert sum(mode["metrics"]["model_calls"].values()) == 2


def test_deep_lock_graph_cycle_without_recursion_limit() -> None:
    events = []
    for i in range(1100):
        events.extend([TimelineEvent(thread=f"T{i}", event="LOCK", resource=str(i)),
                       TimelineEvent(thread=f"T{i}", event="WAIT", resource=str((i + 1) % 1100))])
    assert len(lock_graph(events).cycle) == 1101


def test_false_fix_counts_instrumented_campaign_failure() -> None:
    from agentkernel.concurrency.app import ConcurrencyJobResult
    from agentkernel.concurrency.benchmark.metrics import summarize
    job = ConcurrencyJobResult(task="instrumented", repairs=[{"patch": {"success": True},
        "verification": {"passed": False, "failed_runs": 0,
            "evidence": {"sanitizer": {"campaign": {"failed_runs": 1}}}}}])
    assert summarize([job])["false_fix_rate"] == 1
