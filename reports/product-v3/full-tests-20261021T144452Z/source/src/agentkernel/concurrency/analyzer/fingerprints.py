import hashlib
import json

from pydantic import BaseModel, Field

from ..campaign.models import CampaignResult
from ..instrumentation.sanitizer import parse_sanitizer
from .trace_parser import TimelineEvent, parse_timeline


class LockGraph(BaseModel):
    edges: list[tuple[str, str]] = Field(default_factory=list)
    cycle: list[str] = Field(default_factory=list)


class ConcurrencyFingerprint(BaseModel):
    fingerprint_id: str
    pattern: str
    threads: list[str] = Field(default_factory=list)
    lock_orders: list[tuple[str, str]] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    occurrences: int = 1
    representative_runs: list[str] = Field(default_factory=list)
    evidence: dict[str, object] = Field(default_factory=dict)


def lock_graph(events: list[TimelineEvent]) -> LockGraph:
    held: dict[str, set[str]] = {}
    edges: set[tuple[str, str]] = set()
    for event in events:
        locks = held.setdefault(event.thread, set())
        if event.event in {"LOCK", "WAIT"}:
            edges.update((lock, event.resource) for lock in locks)
        if event.event == "LOCK":
            locks.add(event.resource)
        elif event.event == "UNLOCK":
            locks.discard(event.resource)
    adjacency: dict[str, set[str]] = {}
    for a, b in edges:
        adjacency.setdefault(a, set()).add(b)
    # Iterative DFS visits each vertex once, including deep or branching logs.
    completed: set[str] = set()
    cycle: list[str] = []
    for node in sorted(adjacency):
        if node in completed:
            continue
        path = [node]
        active = {node: 0}
        stack = [iter(sorted(adjacency.get(node, set())))]
        while stack:
            neighbor = next(stack[-1], None)
            if neighbor is None:
                completed.add(path[-1])
                active.pop(path.pop())
                stack.pop()
            elif neighbor in active:
                cycle = path[active[neighbor]:] + [neighbor]
                break
            elif neighbor not in completed:
                active[neighbor] = len(path)
                path.append(neighbor)
                stack.append(iter(sorted(adjacency.get(neighbor, set()))))
        if cycle:
            break
    return LockGraph(edges=sorted(edges), cycle=cycle)


def fingerprints(campaign: CampaignResult) -> list[ConcurrencyFingerprint]:
    grouped: dict[str, ConcurrencyFingerprint] = {}
    for run in campaign.runs:
        if run.classification.value == "PASS":
            continue
        events = parse_timeline(run.stdout)
        graph = lock_graph(events)
        findings = parse_sanitizer(run.stderr)
        if graph.cycle:
            pattern = "cyclic_lock_wait" if run.timed_out else "inconsistent_lock_order"
        elif any(finding.type == "data_race" for finding in findings):
            pattern = "sanitizer_race"
        elif run.crashed:
            pattern = "crash_under_concurrency"
        elif run.timed_out:
            pattern = "timeout_unknown"
        else:
            pattern = run.classification.value.lower()
        evidence = {"edges": graph.edges, "cycle": graph.cycle,
                    "finding_locations": [(finding.type, finding.file, finding.line) for finding in findings]}
        key = hashlib.sha256(json.dumps([pattern, evidence], sort_keys=True).encode()).hexdigest()[:16]
        if key in grouped:
            grouped[key].occurrences += 1
            if len(grouped[key].representative_runs) < 3:
                grouped[key].representative_runs.append(run.run_id)
        else:
            grouped[key] = ConcurrencyFingerprint(
                fingerprint_id=key, pattern=pattern, threads=sorted({event.thread for event in events}),
                lock_orders=graph.edges, confidence=0.9 if graph.cycle or findings else 0.5,
                representative_runs=[run.run_id], evidence=evidence,
            )
    return list(grouped.values())
