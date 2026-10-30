import os
import re
from typing import Any


def redact(value: Any) -> Any:
    """Redact credential fields and known environment secret values before export."""
    secret_key = re.compile(r"api[_-]?key|authorization|password|secret|access[_-]?token", re.I)
    secrets = [v for k, v in os.environ.items() if len(v) >= 8 and secret_key.search(k)]
    def clean(item: Any) -> Any:
        if isinstance(item, dict):
            return {k: "[REDACTED]" if secret_key.search(k) else clean(v) for k, v in item.items()}
        if isinstance(item, list):
            return [clean(v) for v in item]
        if isinstance(item, str):
            for secret in secrets:
                item = item.replace(secret, "[REDACTED]")
            return re.sub(r"Bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", item)
        return item
    return clean(value)
