import asyncio
from pathlib import Path

from agentkernel.core.models import TaskRequest
from agentkernel.providers.local_rtx import LocalRTXProvider
from agentkernel.providers.mock_nebius import MockNebiusProvider
from agentkernel.router.rule_router import RuleBasedRouter
from agentkernel.runtime.kernel import AgentKernel
from agentkernel.telemetry.events import ExecutionTelemetryEvent, TelemetryEvent
from agentkernel.telemetry.recorder import TelemetryRecorder
from agentkernel.verification.mock_verifier import MockVerifier


def test_jsonl_export(tmp_path: Path) -> None:
    recorder = TelemetryRecorder()
    kernel = AgentKernel(RuleBasedRouter(), LocalRTXProvider(), MockNebiusProvider(), recorder, MockVerifier(default_pass=True))
    for task_id in ("one", "two"):
        asyncio.run(kernel.execute(TaskRequest(task_id=task_id, task_type="ci", prompt="ImportError")))
    path = recorder.export_jsonl(tmp_path / "nested" / "events.jsonl")
    events = [(ExecutionTelemetryEvent if '"event_type":"execution"' in line else TelemetryEvent).model_validate_json(line)
              for line in path.read_text(encoding="utf-8").splitlines()]
    assert events == list(recorder.all_events)
    assert len({event.event_id for event in events}) == 4
    assert all(event.timestamp.tzinfo is not None for event in events)
    recorder.export_jsonl(path)
    assert len(path.read_text(encoding="utf-8").splitlines()) == 4


def test_empty_export(tmp_path: Path) -> None:
    path = TelemetryRecorder().export_jsonl(tmp_path / "empty.jsonl")
    assert path.read_text(encoding="utf-8") == ""
