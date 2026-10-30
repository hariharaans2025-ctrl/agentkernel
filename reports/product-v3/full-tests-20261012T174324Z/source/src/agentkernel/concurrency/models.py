from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator


class SemanticCheck(BaseModel):
    name: str = Field(min_length=1)
    build_command: list[str] = Field(min_length=1)
    run_command: list[str] = Field(min_length=1)
    expected_stdout: str = 'SEMANTIC_PASS'
    required: bool = True

    @field_validator('build_command', 'run_command')
    @classmethod
    def valid_command(cls, value):
        if any(not arg or '\x00' in arg for arg in value):
            raise ValueError('Trusted semantic commands require nonempty argv')
        return value


class VerificationConfig(BaseModel):
    required_build_success: bool = True
    stress_runs: int = Field(default=100, ge=1, le=10000)
    allowed_deadlocks: int = Field(default=0, ge=0)
    allowed_races: int = Field(default=0, ge=0)
    allowed_crashes: int = Field(default=0, ge=0)
    required_original_tests: bool = False
    original_test_commands: list[list[str]] = Field(default_factory=list)
    sanitizer_enabled: bool = False
    sanitizer_required: bool = False
    sanitizer_runs: int = Field(default=3, ge=1, le=1000)
    sanitizer_compiler: str | None = None
    semantic_checks: list[SemanticCheck] = Field(default_factory=list)


class ConcurrencyTask(BaseModel):
    """Commands and environment must be supplied by a trusted human/configuration."""
    task_id: str = Field(min_length=1)
    workspace: Path
    source_files: list[str] = Field(min_length=1)
    support_files: list[str] = Field(default_factory=list)
    build_command: list[str] = Field(min_length=1)
    binary_path: str = "app"
    run_command: list[str] = Field(min_length=1)
    max_runtime_seconds: float = Field(default=2, gt=0, le=300, allow_inf_nan=False)
    compile_timeout_seconds: float = Field(default=30, gt=0, le=600, allow_inf_nan=False)
    stress_runs: int = Field(default=10, ge=1, le=10000)
    environment: dict[str, str] = Field(default_factory=dict)
    expected_behavior: str = "PASS"
    expected_bug_category: str = "unknown"
    verification_config: VerificationConfig = Field(default_factory=VerificationConfig)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("build_command", "run_command")
    @classmethod
    def nonempty_command(cls, value: list[str]) -> list[str]:
        if any(not part or "\x00" in part for part in value):
            raise ValueError("Command arguments must be nonempty and contain no NULs")
        return value
