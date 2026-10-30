from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class LocalInferenceResponse(BaseModel):
    output_text: str
    model: str
    latency_ms: float = Field(ge=0, allow_inf_nan=False)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LocalBackendStatus(BaseModel):
    available: bool
    backend: str
    configured_model: str | None = None
    error: str | None = None


class LocalBackendError(RuntimeError):
    """A safe, actionable local backend error suitable for CLI display."""


class LocalInferenceBackend(ABC):
    @abstractmethod
    async def generate(self, prompt: str, system_prompt: str | None = None) -> LocalInferenceResponse:
        """Run local inference and return measured latency and available usage."""

    @abstractmethod
    async def health_check(self) -> LocalBackendStatus:
        """Check whether the configured backend and model are available."""
