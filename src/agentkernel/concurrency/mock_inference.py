"""Explicit scripted demo responses, not a reasoning model or evaluation ground truth."""
import difflib
import json

from agentkernel.core.models import RoutingDecision, TaskRequest


def mock_concurrency_response(task: TaskRequest, routing: RoutingDecision) -> str:
    context = task.metadata["concurrency_context"]
    campaign = context["baseline"]
    if task.metadata["phase"] == "triage":
        patterns = context.get("fingerprints", [])
        return json.dumps({"dominant_failure": patterns[0]["pattern"] if patterns else "unknown",
                           "failed_runs": campaign["failed_runs"], "pass_runs": campaign["total_runs"] - campaign["failed_runs"],
                           "representative_runs": [run["run_id"] for run in campaign["representative_runs"]],
                           "confidence": 0.8, "requires_deeper_reasoning": campaign["failed_runs"] > 0})
    diffs: list[str] = []
    for name, source in context["sources"].items():
        changed = source
        if "pthread_mutex_t *first = id == 1 ? &a : &b;" in source:
            changed = changed.replace("pthread_mutex_t *first = id == 1 ? &a : &b;", "pthread_mutex_t *first = &a;")
            changed = changed.replace("pthread_mutex_t *second = id == 1 ? &b : &a;", "pthread_mutex_t *second = &b;")
            changed = changed.replace("    pthread_barrier_wait(&ready);\n", "")
            changed = changed.replace("    pthread_mutex_lock(first);", "    pthread_barrier_wait(&ready);\n    pthread_mutex_lock(first);")
        elif "counter++;" in source and "static pthread_mutex_t counter_lock" in source:
            changed = changed.replace("    counter++;", "    pthread_mutex_lock(&counter_lock);\n    counter++;\n    pthread_mutex_unlock(&counter_lock);")
        if changed != source:
            diffs.append("".join(difflib.unified_diff(source.splitlines(True), changed.splitlines(True),
                                                     fromfile="a/" + name, tofile="b/" + name)))
    return json.dumps({"diagnosis": "Scripted demonstration hypothesis based on a recognized fixture shape.",
                       "root_cause": "Conflicting lock order or an unprotected counter increment.",
                       "confidence": 0.8, "patch": "".join(diffs),
                       "reasoning_summary": "Mock candidate; real execution must determine acceptance.",
                       "expected_effect": "Consistent lock ordering or serialized shared updates.",
                       "risk_notes": ["Scripted mock; not a claim about general model repair capability."]})
