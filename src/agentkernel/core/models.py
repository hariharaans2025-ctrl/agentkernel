from typing import Any

from pydantic import BaseModel, Field

from .enums import ExecutionStatus, InferenceTier, ProviderType, RiskLevel, TaskDifficulty


class TaskRequest(BaseModel):
    task_id: str = Field(min_length=1)
    task_type: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    privacy_sensitive: bool = False
    max_cost_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    max_latency_ms: int | None = Field(default=None, ge=0)


class RoutingDecision(BaseModel):
    task_id: str
    difficulty: TaskDifficulty
    risk: RiskLevel
    confidence: float = Field(ge=0, le=1)
    selected_tier: InferenceTier
    selected_provider: ProviderType
    requires_external_knowledge: bool
    reason: str


class InferenceResult(BaseModel):
    task_id: str
    provider: ProviderType
    tier: InferenceTier
    output_text: str
    status: ExecutionStatus
    latency_ms: float = Field(ge=0, allow_inf_nan=False)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    estimated_cost_usd: float = Field(ge=0, allow_inf_nan=False)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionResult(BaseModel):
    routing: RoutingDecision
    inference: InferenceResult
