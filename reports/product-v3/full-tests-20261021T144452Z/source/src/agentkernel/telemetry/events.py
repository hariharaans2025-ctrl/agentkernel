from datetime import datetime, timezone
from uuid import uuid4
from typing import Any, Literal

from pydantic import BaseModel, Field

from agentkernel.core.enums import ExecutionStatus, InferenceTier, ProviderType, TaskDifficulty
from agentkernel.core.models import RoutingDecision


class TelemetryEvent(BaseModel):
    event_type: Literal["attempt"] = "attempt"
    execution_id: str | None = None
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    route: RoutingDecision
    provider: ProviderType
    tier: InferenceTier
    difficulty: TaskDifficulty
    confidence: float = Field(ge=0, le=1)
    latency_ms: float = Field(ge=0, allow_inf_nan=False)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    estimated_cost_usd: float | None = Field(ge=0, allow_inf_nan=False)
    status: ExecutionStatus
    metadata: dict[str, Any] = Field(default_factory=dict)
    attempt_number: int = Field(default=1, ge=1)
    model: str | None = None
    verification_passed: bool | None = None
    verification_reason: str | None = None
    cumulative_cost: float | None = Field(default=0, ge=0)
    cumulative_latency: float = Field(default=0, ge=0)
    escalated_after_attempt: bool = False


class ExecutionTelemetryEvent(BaseModel):
    event_type: Literal["execution"] = "execution"
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    execution_id: str
    task_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    success: bool
    number_of_attempts: int = Field(ge=0)
    starting_tier: InferenceTier
    final_tier: InferenceTier | None
    total_cost: float | None = Field(ge=0)
    total_latency: float = Field(ge=0)
    stopped_reason: str
    metadata: dict[str, Any] = Field(default_factory=dict)
