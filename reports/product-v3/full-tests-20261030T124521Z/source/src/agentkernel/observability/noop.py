from .base import ObservabilityBackend


class NoOpObserver(ObservabilityBackend):
    async def start_span(self, name, parent, metadata, run_type="chain"):
        return None

    async def end_span(self, span, metadata, error=None):
        return None

    async def record_feedback(self, span, key, value):
        return None

    async def flush(self):
        return {"backend": "none", "status": "disabled"}
