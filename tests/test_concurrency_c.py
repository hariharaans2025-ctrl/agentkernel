from agentkernel.concurrency.analyzer.classifier import classify
from agentkernel.concurrency.analyzer.trace_parser import parse_timeline
from agentkernel.concurrency.instrumentation.sanitizer import SanitizerConfig, parse_sanitizer
from agentkernel.concurrency.sandbox.base import CommandResult


def test_tsan_findings() -> None:
    text = "WARNING: ThreadSanitizer: data race\nWrite of size 4 at 0xabc by thread T1:\n#0 main.c:12\nPrevious read by thread T2"
    finding = parse_sanitizer(text)[0]
    assert finding.type == "data_race"
    assert finding.file == "main.c" and finding.line == 12
    assert (finding.thread_a, finding.thread_b) == ("T1", "T2")
    assert finding.memory_location == "0xabc"
    assert finding.raw_summary == text
    assert classify(CommandResult(command=["app"], exit_code=0, stderr=text), "").value == "RACE_DETECTED"


def test_sanitizer_environment_failure_is_not_clean() -> None:
    text = "FATAL: ThreadSanitizer: unexpected memory mapping"
    assert parse_sanitizer(text)[0].type == "sanitizer_failure"
    assert classify(CommandResult(command=["app"], exit_code=66, stderr=text), "").value == "SANITIZER_FAILURE"
    assert "-fsanitize=thread" in SanitizerConfig().flags


def test_explicit_trace_only() -> None:
    events = parse_timeline("T1 lock(accounts)\nT2 LOCK log\nT1 WAIT log\nT2 wait(accounts)\nrandom comment")
    assert len(events) == 4
    assert events[0].event == "LOCK" and events[-1].resource == "accounts"
    assert parse_timeline("this might be a deadlock") == []
