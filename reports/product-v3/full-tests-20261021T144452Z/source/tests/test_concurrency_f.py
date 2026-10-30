import asyncio
import difflib
from pathlib import Path

import pytest

from agentkernel.concurrency.repair.patch_applier import UnifiedDiffApplier
from agentkernel.concurrency.sandbox.local import LocalSandboxBackend


def patch(old: str, new: str, name: str = "main.c") -> str:
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), fromfile="a/" + name, tofile="b/" + name))


def test_valid_patch_only_mutates_copy(tmp_path: Path) -> None:
    (tmp_path / "main.c").write_text("int a = 0;\n")
    async def run() -> None:
        async with LocalSandboxBackend() as sandbox:
            await sandbox.upload_project(tmp_path, ["main.c"])
            result = await sandbox.apply_patch(patch("int a = 0;\n", "int a = 1;\n"), ["main.c"])
            assert result.success and result.files_changed == ["main.c"]
            assert len(result.patch_hash) == 64
            assert await sandbox.read_file("main.c") == "int a = 1;\n"
        assert (tmp_path / "main.c").read_text() == "int a = 0;\n"
    asyncio.run(run())


@pytest.mark.parametrize("name", ["../main.c", "/tmp/main.c", "C:/main.c", "sub/../../main.c", ".env", "tests.py"])
def test_patch_rejects_untrusted_paths(tmp_path: Path, name: str) -> None:
    result = UnifiedDiffApplier().apply(tmp_path, patch("x\n", "y\n", name), ["main.c"])
    assert not result.success and result.rejected_paths


def test_context_mismatch_and_multi_file_atomicity(tmp_path: Path) -> None:
    (tmp_path / "main.c").write_text("original\n")
    (tmp_path / "other.c").write_text("other\n")
    diff = patch("original\n", "changed\n") + patch("wrong\n", "changed\n", "other.c")
    result = UnifiedDiffApplier().apply(tmp_path, diff, ["main.c", "other.c"])
    assert not result.success
    assert (tmp_path / "main.c").read_text() == "original\n"
