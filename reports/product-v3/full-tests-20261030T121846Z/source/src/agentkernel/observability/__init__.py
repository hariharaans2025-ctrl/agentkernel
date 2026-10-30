"""Backend-neutral scoped tracing; payloads are allowlisted and redacted."""
import os
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from .base import ObservabilityBackend, SpanHandle
from .noop import NoOpObserver
from .safety import safe_metadata

_context: ContextVar[tuple[ObservabilityBackend, SpanHandle | None] | None] = ContextVar("agentkernel_trace", default=None)


async def nonfatal(awaitable):
    try:
        return await awaitable
    except Exception:
        return None


def configured_observer() -> ObservabilityBackend:
    mode = os.getenv("AGENTKERNEL_OBSERVABILITY", "none").lower()
    if mode == "none":
        return NoOpObserver()
    if mode == "langsmith":
        from .langsmith_observer import LangSmithObserver
        return LangSmithObserver()
    raise ValueError("AGENTKERNEL_OBSERVABILITY must be none or langsmith")


@dataclass
class Observation:
    backend: ObservabilityBackend
    handle: SpanHandle | None
    metadata: dict = field(default_factory=dict)

    def update(self, **metadata):
        self.metadata.update(safe_metadata(metadata))

    async def feedback(self, **values):
        for key, value in values.items():
            await nonfatal(self.backend.record_feedback(self.handle, key, value))


@asynccontextmanager
async def trace(name: str, backend: ObservabilityBackend, **metadata):
    handle = await nonfatal(backend.start_trace(name, safe_metadata(metadata)))
    token = _context.set((backend, handle))
    observed = Observation(backend, handle)
    try:
        yield observed
    except BaseException as exc:
        await nonfatal(backend.end_span(handle, observed.metadata, type(exc).__name__))
        raise
    else:
        await nonfatal(backend.end_span(handle, observed.metadata))
    finally:
        _context.reset(token)


@asynccontextmanager
async def span(name: str, *, run_type="chain", **metadata):
    active = _context.get()
    if active is None:
        yield Observation(NoOpObserver(), None)
        return
    backend, parent = active
    handle = await nonfatal(backend.start_span(name, parent, safe_metadata(metadata), run_type))
    token = _context.set((backend, handle or parent))
    observed = Observation(backend, handle)
    try:
        yield observed
    except BaseException as exc:
        await nonfatal(backend.end_span(handle, observed.metadata, type(exc).__name__))
        raise
    else:
        await nonfatal(backend.end_span(handle, observed.metadata))
    finally:
        _context.reset(token)
