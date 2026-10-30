import asyncio
import os
import shutil
import signal
import tempfile
from pathlib import Path, PureWindowsPath
from time import perf_counter
from typing import Any

from .base import CommandResult, SandboxBackend


def safe_path(root: Path, relative: str) -> Path:
    parts = relative.replace("\\", "/").split("/")
    if (not relative or Path(relative).is_absolute() or PureWindowsPath(relative).drive
            or any(part in {"", ".", ".."} or ":" in part for part in parts)):
        raise ValueError(f"Unsafe workspace path: {relative}")
    target = root.joinpath(*parts)
    cursor = root
    for part in parts:
        cursor /= part
        if cursor.is_symlink() or (hasattr(cursor, "is_junction") and cursor.is_junction()):
            raise ValueError("Links are forbidden in disposable project paths")
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("Path escapes workspace")
    return target


class LocalSandboxBackend(SandboxBackend):
    """File isolation for trusted fixtures, NOT containment for hostile native code."""
    def __init__(self, *, temporary_parent: Path | None = None, output_limit: int = 65536) -> None:
        self.parent = temporary_parent
        self.output_limit = output_limit
        self.workspace: Path | None = None
        self._temporary: tempfile.TemporaryDirectory[str] | None = None

    async def create_workspace(self) -> Path:
        if self.workspace is not None:
            raise RuntimeError("Workspace already created")
        self._temporary = tempfile.TemporaryDirectory(prefix="agentkernel-", dir=self.parent)
        self.workspace = Path(self._temporary.name).resolve()
        return self.workspace

    def _root(self) -> Path:
        if self.workspace is None:
            raise RuntimeError("Create a workspace first")
        return self.workspace

    async def upload_project(self, source: Path, files: list[str]) -> None:
        for filename in files:
            src, dst = safe_path(source.resolve(), filename), safe_path(self._root(), filename)
            if not src.is_file() or src.stat().st_size > 2_000_000:
                raise ValueError("Project file missing or exceeds 2 MB")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    async def read_file(self, path: str) -> str:
        file = safe_path(self._root(), path)
        if file.stat().st_size > 2_000_000:
            raise ValueError("File exceeds read limit")
        return file.read_text(encoding="utf-8")

    async def apply_patch(self, patch: str, allowed_files: list[str]) -> Any:
        # Late import keeps patching optional until milestone F.
        from ..repair.patch_applier import UnifiedDiffApplier
        return UnifiedDiffApplier().apply(self._root(), patch, allowed_files)

    async def run_command(self, command: list[str], *, timeout: float,
                          environment: dict[str, str] | None = None) -> CommandResult:
        if not command or any(not isinstance(part, str) or not part or "\x00" in part for part in command):
            raise ValueError("Expected a trusted argv list")
        if timeout <= 0:
            raise ValueError("Timeout must be positive")
        root = self._root()
        # Do not inherit API keys or unrelated secrets into the process.
        env = {key: value for key, value in os.environ.items()
               if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "LANG"}}
        env.update(environment or {})
        argv = list(command)
        if argv[0].startswith("./"):
            executable = safe_path(root, argv[0][2:])
            if os.name == "nt" and not executable.exists() and executable.with_suffix(".exe").exists():
                executable = executable.with_suffix(".exe")
            argv[0] = str(executable)
        started = perf_counter()
        result = CommandResult(command=command)
        buffers = [bytearray(), bytearray()]
        truncated = [False, False]
        async def drain(stream: asyncio.StreamReader, index: int) -> None:
            while chunk := await stream.read(4096):
                room = max(0, self.output_limit - len(buffers[index]))
                buffers[index].extend(chunk[:room])
                truncated[index] |= len(chunk) > room
        process: asyncio.subprocess.Process | None = None
        readers: list[asyncio.Task[None]] = []
        async def terminate() -> None:
            if process is None:
                return
            if os.name == "nt":
                killer = await asyncio.create_subprocess_exec(
                    str(Path(os.environ.get("SYSTEMROOT", "C:/Windows")) / "System32/taskkill.exe"),
                    "/PID", str(process.pid), "/T", "/F",
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                await killer.wait()
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if process.returncode is None:
                process.kill()
            await process.wait()
        try:
            process = await asyncio.create_subprocess_exec(
                *argv, cwd=root, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                start_new_session=os.name != "nt")
            assert process.stdout is not None and process.stderr is not None
            readers = [asyncio.create_task(drain(process.stdout, 0)), asyncio.create_task(drain(process.stderr, 1))]
            async with asyncio.timeout(timeout):
                await process.wait()
                await asyncio.gather(*readers)
            result.exit_code = process.returncode
        except TimeoutError:
            result.timed_out = True
            await terminate()
            result.exit_code = process.returncode if process else None
        except OSError as exc:
            result.metadata["error"] = type(exc).__name__
            result.metadata["errno"] = exc.errno
            result.metadata["winerror"] = getattr(exc, "winerror", None)
            result.metadata["execution_policy_blocked"] = getattr(exc, "winerror", None) == 4551
            buffers[1].extend(b"Executable unavailable or process could not start.")
        except asyncio.CancelledError:
            await terminate()
            raise
        finally:
            for reader in readers:
                if not reader.done():
                    reader.cancel()
            await asyncio.gather(*readers, return_exceptions=True)
        result.stdout = buffers[0].decode("utf-8", errors="replace")
        result.stderr = buffers[1].decode("utf-8", errors="replace")
        result.metadata["output_truncated"] = any(truncated)
        result.duration_ms = (perf_counter() - started) * 1000
        return result

    async def destroy(self) -> None:
        if self._temporary is not None:
            self._temporary.cleanup()
        self.workspace = None
        self._temporary = None

    async def __aenter__(self) -> "LocalSandboxBackend":
        await self.create_workspace()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.destroy()
