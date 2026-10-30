"""Remote-only execution through the pinned Contree SDK; no host fallback."""
import json
import os
import tempfile
from pathlib import Path
from time import perf_counter

from .base import CommandResult, SandboxBackend
from .local import safe_path

# This helper is executed ONLY inside the remote Linux sandbox. The wrapper
# exits successfully even for a timed-out child so the snapshot stays usable.
REMOTE_RUNNER = r"""
import json, os, signal, subprocess, sys, tempfile, time
spec = json.loads(sys.argv[1])
result = {"exit_code": None, "timed_out": False, "metadata": {"execution_backend": "nebius"}}
started = time.monotonic()
with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
    try:
        proc = subprocess.Popen(spec["command"], cwd="/workspace", env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8", **spec["environment"]}, stdout=out, stderr=err, start_new_session=True)
        try:
            proc.wait(timeout=spec["timeout"])
        except subprocess.TimeoutExpired:
            result["timed_out"] = True
        finally:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
        result["exit_code"] = proc.returncode
    except OSError as exc:
        result["metadata"]["error"] = type(exc).__name__
        result["metadata"]["errno"] = exc.errno
    for name, stream in (("stdout", out), ("stderr", err)):
        stream.seek(0)
        data = stream.read(spec["limit"] + 1)
        result["metadata"]["output_truncated"] = result["metadata"].get("output_truncated", False) or len(data) > spec["limit"]
        result[name] = data[:spec["limit"]].decode("utf-8", errors="replace")
result["duration_ms"] = (time.monotonic() - started) * 1000
print(json.dumps(result))
"""


class NebiusSandboxBackend(SandboxBackend):
    def __init__(self, *, temporary_parent=None, output_limit=65536, client=None):
        self.parent = temporary_parent
        self.output_limit = output_limit
        self.client = client
        self.image = None
        self.workspace = None
        self._temporary = None

    async def create_workspace(self):
        if self.workspace is not None:
            raise ValueError("Workspace already created")
        if self.client is None:
            from contree_sdk import Contree
            from contree_sdk.auth import IAMAuth
            from contree_sdk.config import ContreeConfig
            key, project = os.getenv("NEBIUS_API_KEY"), os.getenv("NEBIUS_PROJECT_ID")
            if not key or not project:
                raise ValueError("Nebius execution requires NEBIUS_API_KEY and NEBIUS_PROJECT_ID; local fallback is disabled")
            self.client = Contree(ContreeConfig(auth=IAMAuth(token=key, project_id=project),
                operation_timeout=180, transport_timeout=20))
        try:
            base = await self.client.images.use(os.getenv("AGENTKERNEL_SANDBOX_IMAGE", "python:3.12"))
            self.image = await base.run("mkdir", args=["-p", "/workspace"], disposable=False, timeout=10)
            if self.image.exit_code != 0:
                raise ValueError("Remote workspace creation failed")
        except Exception as exc:
            raise ValueError("Nebius workspace unavailable: " + type(exc).__name__ + "; no local fallback") from None
        # Text-only staging for strict diff validation. Never execute files here.
        self._temporary = tempfile.TemporaryDirectory(prefix="agentkernel-source-", dir=self.parent)
        self.workspace = Path(self._temporary.name).resolve()
        return self.workspace

    async def upload_project(self, source, files):
        if self.workspace is None:
            raise ValueError("Create a workspace first")
        uploads = {}
        for name in files:
            src, dst = safe_path(source.resolve(), name), safe_path(self.workspace, name)
            if any(part.startswith(".env") or part in {".git", ".venv"} for part in Path(name).parts):
                raise ValueError("Credentials and repository internals cannot be uploaded")
            if not src.is_file() or src.stat().st_size > 2_000_000:
                raise ValueError("Project file missing or exceeds 2 MB")
            data = src.read_bytes()
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)
            uploads["/workspace/" + name.replace("\\", "/")] = data
        await self._upload(uploads)

    async def _upload(self, files):
        try:
            self.image = await self.image.apply_files(files=files)
            if self.image.exit_code != 0:
                raise ValueError("Remote upload failed")
        except Exception as exc:
            raise ValueError("Nebius upload failed: " + type(exc).__name__) from None

    async def read_file(self, path):
        safe_path(self.workspace, path)
        data = await self.image.read("/workspace/" + path.replace("\\", "/"))
        if len(data) > 2_000_000:
            raise ValueError("File exceeds read limit")
        return data.decode("utf-8")

    async def apply_patch(self, patch, allowed_files):
        from ..repair.patch_applier import UnifiedDiffApplier
        # Fetch current remote sources so local staging cannot become stale.
        for name in allowed_files:
            safe_path(self.workspace, name).write_text(await self.read_file(name), encoding="utf-8", newline="")
        applied = UnifiedDiffApplier().apply(self.workspace, patch, allowed_files)
        if applied.success:
            await self._upload({"/workspace/" + name: safe_path(self.workspace, name).read_bytes()
                                for name in applied.files_changed})
        return applied

    async def run_command(self, command, *, timeout, environment=None):
        if not command or any(not isinstance(p, str) or not p or "\x00" in p for p in command):
            raise ValueError("Expected a trusted argv list")
        if timeout <= 0 or self.image is None:
            raise ValueError("Remote workspace and positive timeout required")
        spec = {"command": command, "timeout": timeout, "environment": environment or {}, "limit": self.output_limit}
        started = perf_counter()
        try:
            image = await self.image.run("python3", args=["-c", REMOTE_RUNNER, json.dumps(spec)],
                timeout=timeout + 15, disposable=False, truncate_output_at=self.output_limit * 12 + 8192)
            if image.exit_code != 0:
                raise ValueError("Remote execution wrapper failed")
            data = json.loads(image.stdout)
            result = CommandResult(command=command, **data)
            result.metadata.update(remote_image_id=str(image.uuid), transport_wall_ms=(perf_counter()-started)*1000)
            self.image = image
            return result
        except Exception as exc:
            # Never classify API failures as a program crash or silently run locally.
            raise ValueError("Nebius command unavailable: " + type(exc).__name__ + "; no local fallback") from None

    async def destroy(self):
        # SDK run instances terminate with each command. Untagged filesystem
        # snapshots are retained according to the service policy (no delete API).
        self.image = None
        if self._temporary is not None:
            self._temporary.cleanup()
        self.workspace = None
        self._temporary = None

    async def __aenter__(self):
        await self.create_workspace()
        return self

    async def __aexit__(self, *exc):
        await self.destroy()
