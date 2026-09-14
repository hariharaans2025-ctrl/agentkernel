from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field

from agentkernel.core.enums import ExecutionStatus, InferenceTier, ProviderType, TaskDifficulty
from agentkernel.core.models import RoutingDecision


class TelemetryEvent(BaseModel):
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
    estimated_cost_usd: float = Field(ge=0, allow_inf_nan=False)
    status: ExecutionStatus
