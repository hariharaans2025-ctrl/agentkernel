import asyncio
import sys
from pathlib import Path

import pytest

from agentkernel.concurrency.compile.compiler import CCompiler
from agentkernel.concurrency.models import ConcurrencyTask
from agentkernel.concurrency.sandbox.local import LocalSandboxBackend, safe_path


@pytest.mark.parametrize(("code", "success", "timed_out"), [
    ("print('built')", True, False), ("raise SystemExit(2)", False, False),
    ("import time; time.sleep(5)", False, True),
])
def test_compile_process_outcomes(tmp_path: Path, code: str, success: bool, timed_out: bool) -> None:
    task = ConcurrencyTask(task_id="test", workspace=tmp_path, source_files=["main.c"],
                           build_command=[sys.executable, "-c", code], run_command=["./app"],
                           compile_timeout_seconds=0.5 if timed_out else 5)
    async def run() -> None:
        async with LocalSandboxBackend() as sandbox:
            result = await CCompiler().compile(task, sandbox)
        assert result.success is success
        assert result.timed_out is timed_out
        assert result.duration_ms > 0
    asyncio.run(run())


def test_copy_cleanup_and_output_caps(tmp_path: Path) -> None:
    (tmp_path / "main.c").write_text("original")
    async def run() -> None:
        async with LocalSandboxBackend(output_limit=100) as sandbox:
            await sandbox.upload_project(tmp_path, ["main.c"])
            root = sandbox.workspace
            assert root is not None
            (root / "main.c").write_text("changed")
            result = await sandbox.run_command([sys.executable, "-c", "print('x'*10000)"], timeout=3)
            assert len(result.stdout) <= 100
            assert result.metadata["output_truncated"]
            invalid = await sandbox.run_command(["agentkernel-no-such-executable-123"], timeout=1)
            assert invalid.exit_code is None
            assert "error" in invalid.metadata
        assert not root.exists()
        assert (tmp_path / "main.c").read_text() == "original"
    asyncio.run(run())


@pytest.mark.parametrize("path", ["../oops", "a/../../x", "/tmp/x", "C:\\temp\\x", "a:stream", "\\\\host\\share"])
def test_unsafe_workspace_paths(tmp_path: Path, path: str) -> None:
    with pytest.raises(ValueError):
        safe_path(tmp_path, path)
