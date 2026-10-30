"""Explicit .env loading, without shell evaluation, expansion or implicit discovery."""
import os
import re
from pathlib import Path


def load_env_file(path: Path) -> None:
    if path.stat().st_size > 65536:
        raise ValueError("Environment file exceeds size limit")
    values = {}
    for index, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ValueError(f"Invalid environment file entry at line {index}")
        if not key.startswith(("AGENTKERNEL_", "NEBIUS_", "LANGSMITH_", "TAVILY_")):
            raise ValueError(f"Unsupported environment setting at line {index}")
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f"Unclosed environment value at line {index}")
            value = value[1:-1]
        if "\x00" in value:
            raise ValueError(f"Invalid environment value at line {index}")
        values[key] = value
    # Existing exported values take precedence, including explicit empty values.
    for key, value in values.items():
        os.environ.setdefault(key, value)
