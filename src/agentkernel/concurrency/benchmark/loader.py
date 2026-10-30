import json
from pathlib import Path

from ..models import ConcurrencyTask
from ..sandbox.local import safe_path


def load_task(directory: Path, *, compiler: str | None = None, static: bool = False,
              stress_runs: int | None = None, verification_runs: int | None = None) -> ConcurrencyTask:
    """Load a HUMAN-TRUSTED task.json. Its commands execute with host privileges."""
    directory = directory.resolve(strict=True)
    config = safe_path(directory, "task.json")
    if config.stat().st_size > 65536:
        raise ValueError("Task configuration exceeds 64 KiB")
    data = json.loads(config.read_text(encoding="utf-8"))
    data["workspace"] = directory
    if compiler:
        data["build_command"][0] = compiler
    if static and "-static" not in data["build_command"]:
        data["build_command"].insert(1, "-static")
    if stress_runs is not None:
        data["stress_runs"] = stress_runs
    if verification_runs is not None:
        data.setdefault("verification_config", {})["stress_runs"] = verification_runs
    task = ConcurrencyTask.model_validate(data)
    for name in task.source_files + task.support_files:
        path = safe_path(directory, name)
        if not path.is_file():
            raise ValueError("Configured project file does not exist: " + name)
        if path.name.startswith(".env") or "reference" in path.name.lower():
            raise ValueError("Credentials and evaluation reference files must not enter execution/model context")
    safe_path(directory, task.binary_path)
    return task


def discover_tasks(root: Path) -> list[Path]:
    root = root.resolve(strict=True)
    if (root / "task.json").is_file():
        return [root]
    return sorted(path.parent for path in root.glob("*/task.json") if not path.parent.is_symlink())
