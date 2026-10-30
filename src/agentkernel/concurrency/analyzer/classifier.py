from ..execution.models import RunClassification as Kind
from ..sandbox.base import CommandResult


def classify(result: CommandResult, expected: str) -> Kind:
    text = result.stderr + "\n" + result.stdout
    if "ThreadSanitizer: data race" in text:
        return Kind.RACE_DETECTED
    if "Sanitizer" in text and any(word in text for word in ("WARNING:", "ERROR:", "FATAL:")):
        return Kind.SANITIZER_FAILURE
    if result.timed_out:
        return Kind.POSSIBLE_DEADLOCK if "WAIT" in text else Kind.TIMEOUT
    if result.exit_code is not None and (result.exit_code < 0 or result.exit_code >= 0x80000000):
        return Kind.CRASH
    if "assertion" in text.lower() or "Assertion" in text:
        if result.exit_code != 0:
            return Kind.ASSERTION_FAILURE
    if result.exit_code == 0 and (not expected or expected in result.stdout) and not result.metadata.get("output_truncated"):
        return Kind.PASS
    return Kind.UNKNOWN_FAILURE
