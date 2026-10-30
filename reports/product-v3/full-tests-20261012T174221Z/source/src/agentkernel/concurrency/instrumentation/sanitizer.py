import re

from pydantic import BaseModel, Field


class SanitizerConfig(BaseModel):
    enabled: bool = False
    required: bool = False
    flags: list[str] = Field(default_factory=lambda: ["-fsanitize=thread", "-g", "-O1"])
    environment: dict[str, str] = Field(default_factory=lambda: {"TSAN_OPTIONS": "halt_on_error=1:exitcode=66"})


class SanitizerFinding(BaseModel):
    type: str
    severity: str = "error"
    file: str | None = None
    line: int | None = None
    thread_a: str | None = None
    thread_b: str | None = None
    memory_location: str | None = None
    raw_summary: str


def parse_sanitizer(text: str) -> list[SanitizerFinding]:
    findings = []
    for match in re.finditer(r"(?:WARNING|ERROR|FATAL): (ThreadSanitizer|AddressSanitizer): ([^\n]+)", text):
        context = text[match.start():match.start() + 4000]
        location = re.search(r"([^\s()]+\.(?:c|h|cc|cpp)):(\d+)", context)
        threads = re.findall(r"thread (T\d+|main)", context)
        memory = re.search(r"(?:at|of size \d+ at) (0x[0-9a-fA-F]+)", context)
        findings.append(SanitizerFinding(
            type="data_race" if "data race" in match[2] else "sanitizer_failure",
            file=location[1] if location else None, line=int(location[2]) if location else None,
            thread_a=threads[0] if threads else None, thread_b=threads[1] if len(threads) > 1 else None,
            memory_location=memory[1] if memory else None, raw_summary=context,
        ))
    return findings


def runtime_unavailable(text: str) -> bool:
    return any(term in text.lower() for term in ('unexpected memory mapping', 'unsupported vma',
        'failed to mmap', 'personality(', 'threadsanitizer: check failed', 'cannot mmap'))


def instrumented_task(task):
    copy = task.model_copy(deep=True)
    if task.verification_config.sanitizer_compiler:
        copy.build_command[0] = task.verification_config.sanitizer_compiler
    copy.environment.update(SanitizerConfig().environment)
    return copy
