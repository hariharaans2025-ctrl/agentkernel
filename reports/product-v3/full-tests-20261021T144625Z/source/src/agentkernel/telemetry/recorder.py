from pathlib import Path
import json
from pydantic import BaseModel

from .events import ExecutionTelemetryEvent, TelemetryEvent
from .redaction import redact


class TelemetryRecorder:
    def __init__(self) -> None:
        self._events: list[BaseModel] = []

    @property
    def events(self) -> tuple[TelemetryEvent, ...]:
        """Backward-compatible view containing attempt events only."""
        return tuple(event.model_copy(deep=True) for event in self._events if isinstance(event, TelemetryEvent))

    @property
    def execution_events(self) -> tuple[ExecutionTelemetryEvent, ...]:
        return tuple(event.model_copy(deep=True) for event in self._events if isinstance(event, ExecutionTelemetryEvent))

    @property
    def all_events(self) -> tuple[BaseModel, ...]:
        return tuple(event.model_copy(deep=True) for event in self._events)

    def record(self, event: BaseModel) -> None:
        self._events.append(event.model_copy(deep=True))

    def export_jsonl(self, path: str | Path) -> Path:
        """Overwrite path with a snapshot of all recorded events."""
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8") as handle:
            for event in self._events:
                handle.write(json.dumps(redact(event.model_dump(mode="json")), ensure_ascii=False, separators=(",", ":")) + "\n")
        return destination
