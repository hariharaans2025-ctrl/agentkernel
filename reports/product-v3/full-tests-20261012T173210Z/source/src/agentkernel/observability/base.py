from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SpanHandle:
    id: str
    name: str
    trace_id: str
    parent_id: str | None
    dotted_order: str


class ObservabilityBackend(ABC):
    async def start_trace(self, name: str, metadata: dict[str, Any]) -> SpanHandle | None:
        return await self.start_span(name, None, metadata)

    @abstractmethod
    async def start_span(self, name: str, parent: SpanHandle | None, metadata: dict[str, Any],
                         run_type: str = "chain") -> SpanHandle | None: ...

    @abstractmethod
    async def end_span(self, span: SpanHandle | None, metadata: dict[str, Any], error: str | None = None) -> None: ...

    @abstractmethod
    async def record_feedback(self, span: SpanHandle | None, key: str, value: bool) -> None: ...

    @abstractmethod
    async def flush(self) -> dict[str, Any]: ...
