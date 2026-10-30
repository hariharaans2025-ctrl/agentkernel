from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class CommandResult(BaseModel):
    command: list[str]
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: float = 0
    timed_out: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class SandboxBackend(ABC):
    @abstractmethod
    async def create_workspace(self) -> Path: ...

    @abstractmethod
    async def upload_project(self, source: Path, files: list[str]) -> None: ...

    @abstractmethod
    async def run_command(self, command: list[str], *, timeout: float,
                          environment: dict[str, str] | None = None) -> CommandResult: ...

    @abstractmethod
    async def read_file(self, path: str) -> str: ...

    @abstractmethod
    async def apply_patch(self, patch: str, allowed_files: list[str]) -> Any: ...

    @abstractmethod
    async def destroy(self) -> None: ...
