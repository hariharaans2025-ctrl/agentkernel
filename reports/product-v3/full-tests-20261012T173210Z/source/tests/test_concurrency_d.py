from agentkernel.concurrency.analyzer.fingerprints import fingerprints, lock_graph
from agentkernel.concurrency.analyzer.trace_parser import parse_timeline
from agentkernel.concurrency.campaign.models import CampaignResult
from agentkernel.concurrency.execution.models import ExecutionRun


def test_cycle_and_unlock() -> None:
    graph = lock_graph(parse_timeline("T1 LOCK A\nT2 LOCK B\nT1 WAIT B\nT2 WAIT A"))
    assert graph.edges == [("A", "B"), ("B", "A")]
    assert graph.cycle == ["A", "B", "A"]
    assert not lock_graph(parse_timeline("T1 LOCK A\nT1 UNLOCK A\nT1 LOCK B")).edges


def test_fingerprint_grouping() -> None:
    runs = [ExecutionRun(run_id=str(i), duration_ms=10, exit_code=None,
                         stdout="T1 LOCK A\nT2 LOCK B\nT1 WAIT B\nT2 WAIT A", stderr="",
                         timed_out=True, crashed=False, sanitizer_detected=False, classification="POSSIBLE_DEADLOCK")
            for i in range(4)]
    grouped = fingerprints(CampaignResult(task_id="x", runs=runs))
    assert len(grouped) == 1 and grouped[0].occurrences == 4
    assert grouped[0].pattern == "cyclic_lock_wait"
    assert len(grouped[0].representative_runs) == 3


def test_race_normalization_ignores_addresses() -> None:
    runs = [ExecutionRun(run_id=str(i), duration_ms=10, exit_code=66, stdout="",
                         stderr=f"WARNING: ThreadSanitizer: data race at 0x{i}abc\nmain.c:4",
                         timed_out=False, crashed=False, sanitizer_detected=True, classification="RACE_DETECTED")
            for i in range(2)]
    grouped = fingerprints(CampaignResult(task_id="race", runs=runs))
    assert len(grouped) == 1 and grouped[0].pattern == "sanitizer_race"
