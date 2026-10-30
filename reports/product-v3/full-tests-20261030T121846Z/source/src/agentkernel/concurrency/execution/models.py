from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RunClassification(str, Enum):
    PASS = "PASS"
    CRASH = "CRASH"
    TIMEOUT = "TIMEOUT"
    POSSIBLE_DEADLOCK = "POSSIBLE_DEADLOCK"
    RACE_DETECTED = "RACE_DETECTED"
    SANITIZER_FAILURE = "SANITIZER_FAILURE"
    ASSERTION_FAILURE = "ASSERTION_FAILURE"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


class ExecutionRun(BaseModel):
    run_id: str
    start_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    duration_ms: float
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    crashed: bool
    sanitizer_detected: bool
    classification: RunClassification
    metadata: dict[str, Any] = Field(default_factory=dict)
