from pathlib import Path

from .events import TelemetryEvent


class TelemetryRecorder:
    def __init__(self) -> None:
        self._events: list[TelemetryEvent] = []

    @property
    def events(self) -> tuple[TelemetryEvent, ...]:
        return tuple(event.model_copy(deep=True) for event in self._events)

    def record(self, event: TelemetryEvent) -> None:
        self._events.append(event.model_copy(deep=True))

    def export_jsonl(self, path: str | Path) -> Path:
        """Overwrite path with a snapshot of all recorded events."""
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8") as handle:
            for event in self._events:
                handle.write(event.model_dump_json() + "\n")
        return destination
