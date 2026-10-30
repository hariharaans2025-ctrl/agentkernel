from typing import Any, Literal

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
    estimated_cost_usd: float | None = Field(ge=0, allow_inf_nan=False)
    metadata: dict[str, Any] = Field(default_factory=dict)


class VerificationResult(BaseModel):
    passed: bool
    retryable: bool = True
    score: float | None = Field(default=None, ge=0, le=1)
    reason: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    verifier_name: str


class AttemptRecord(BaseModel):
    attempt_number: int = Field(ge=1)
    tier: InferenceTier
    provider: ProviderType
    model: str | None = None
    input_prompt: str
    output_text: str
    status: ExecutionStatus
    latency_ms: float = Field(ge=0, allow_inf_nan=False)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    estimated_cost_usd: float | None = Field(ge=0, allow_inf_nan=False)
    verification_status: Literal["PASSED", "FAILED"]
    verification_reason: str
    verification_evidence: dict[str, Any] = Field(default_factory=dict)
    verifier_name: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class FailureEvidence(BaseModel):
    failed_tier: InferenceTier
    provider: ProviderType
    previous_output: str
    verification_reason: str
    verification_evidence: dict[str, Any] = Field(default_factory=dict)
    attempt_number: int = Field(ge=1)


class ExecutionResult(BaseModel):
    task_id: str
    success: bool
    final_output: str
    final_tier: InferenceTier | None
    attempts: list[AttemptRecord]
    total_latency_ms: float = Field(ge=0)
    total_cost_usd: float | None = Field(ge=0)
    stopped_reason: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    # Compatibility: initial route and last inference, None if no attempt ran.
    routing: RoutingDecision
    inference: InferenceResult | None
