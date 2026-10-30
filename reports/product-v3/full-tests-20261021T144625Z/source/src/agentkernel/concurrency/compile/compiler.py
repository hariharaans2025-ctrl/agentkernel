from abc import ABC, abstractmethod

from ..models import ConcurrencyTask
from ..sandbox.base import SandboxBackend
from .models import CompileResult


class Compiler(ABC):
    @abstractmethod
    async def compile(self, task: ConcurrencyTask, sandbox: SandboxBackend,
                      extra_flags: list[str] | None = None) -> CompileResult: ...


class CCompiler(Compiler):
    async def compile(self, task: ConcurrencyTask, sandbox: SandboxBackend,
                      extra_flags: list[str] | None = None) -> CompileResult:
        command = [task.build_command[0], *(extra_flags or []), *task.build_command[1:]]
        result = await sandbox.run_command(command, timeout=task.compile_timeout_seconds, environment=task.environment)
        return CompileResult(**result.model_dump(), success=result.exit_code == 0 and not result.timed_out)
