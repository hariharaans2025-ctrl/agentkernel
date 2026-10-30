import asyncio
import json
from types import SimpleNamespace

import pytest

from agentkernel.concurrency.sandbox.nebius import NebiusSandboxBackend


class Image:
    uuid = "remote-snapshot"
    exit_code = 0
    def __init__(self):
        self.files = {}
        self.calls = []
        self.fail = False

    async def run(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if self.fail:
            raise RuntimeError("service down")
        self.stdout = json.dumps({"exit_code": -9, "timed_out": True,
            "stdout": "before timeout", "stderr": "", "duration_ms": 2000,
            "metadata": {"execution_backend": "nebius"}})
        return self

    async def apply_files(self, *, files):
        self.files.update(files)
        return self

    async def read(self, path):
        return self.files[path]


def backend():
    image = Image()
    async def use(ref):
        return image
    return NebiusSandboxBackend(client=SimpleNamespace(images=SimpleNamespace(use=use))), image


def test_remote_timeout_and_environment_isolation(monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "do-not-upload-this-secret")
    async def run():
        box, image = backend()
        async with box:
            result = await box.run_command(["./app"], timeout=2, environment={"SEED": "3"})
            assert result.timed_out and result.exit_code == -9
            spec = json.loads(image.calls[-1][1]["args"][-1])
            assert spec["environment"] == {"SEED": "3"}
            assert image.calls[-1][1]["disposable"] is False
            assert "do-not-upload-this-secret" not in json.dumps(image.calls)
    asyncio.run(run())


def test_remote_failure_has_no_local_fallback():
    async def run():
        box, image = backend()
        async with box:
            image.fail = True
            with pytest.raises(ValueError, match="no local fallback"):
                await box.run_command(["gcc", "main.c"], timeout=2)
    asyncio.run(run())


def test_upload_patch_remote_read_and_cleanup(tmp_path):
    (tmp_path / "main.c").write_text("old\n")
    async def run():
        box, image = backend()
        async with box:
            staging = box.workspace
            await box.upload_project(tmp_path, ["main.c"])
            result = await box.apply_patch("--- a/main.c\n+++ b/main.c\n@@ -1 +1 @@\n-old\n+new\n", ["main.c"])
            assert result.success
            assert await box.read_file("main.c") == "new\n"
            assert image.files["/workspace/main.c"] == b"new\n"
            assert (tmp_path / "main.c").read_text() == "old\n"
        assert not staging.exists()
    asyncio.run(run())


@pytest.mark.parametrize("name", ["../outside", ".env", ".git/config", "C:/secret"])
def test_forbidden_uploads(tmp_path, name):
    async def run():
        box, _ = backend()
        async with box:
            with pytest.raises(ValueError):
                await box.upload_project(tmp_path, [name])
    asyncio.run(run())


def test_credentials_required_no_fallback(monkeypatch):
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    monkeypatch.delenv("NEBIUS_PROJECT_ID", raising=False)
    with pytest.raises(ValueError, match="local fallback is disabled"):
        asyncio.run(NebiusSandboxBackend().create_workspace())
