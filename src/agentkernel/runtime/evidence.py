import json

from agentkernel.core.models import AttemptRecord, FailureEvidence, TaskRequest


def build_escalation_task(original: TaskRequest, history: list[AttemptRecord]) -> TaskRequest:
    """Rebuild context from the original and flat history, avoiding nested prompts."""
    previous = history[-1]
    failure = FailureEvidence(
        failed_tier=previous.tier, provider=previous.provider, previous_output=previous.output_text,
        verification_reason=previous.verification_reason,
        verification_evidence=previous.verification_evidence, attempt_number=previous.attempt_number,
    )
    parts = ["ORIGINAL TASK", original.prompt, "", "PREVIOUS ATTEMPT",
             f"Attempt {failure.attempt_number}: {failure.failed_tier.value} / {failure.provider.value}",
             failure.previous_output, "", "VERIFICATION RESULT", failure.verification_reason,
             json.dumps(failure.verification_evidence, ensure_ascii=False, indent=2), "", "ATTEMPT HISTORY"]
    for attempt in history:
        parts.extend([
            f"Attempt {attempt.attempt_number}: {attempt.tier.value} / {attempt.provider.value}",
            f"Inference status: {attempt.status.value}", f"Output: {attempt.output_text}",
            f"Verification: {attempt.verification_status} — {attempt.verification_reason}",
            "Evidence: " + json.dumps(attempt.verification_evidence, ensure_ascii=False, indent=2), "",
        ])
    parts.extend(["INSTRUCTION:", "Use the previous failure as evidence.",
                  "Do not repeat the same unsupported approach.", "Produce an improved diagnosis or answer."])
    if original.metadata.get("phase") == "repair":
        parts.append("Return the ORIGINAL TASK's edit JSON contract. Copy search blocks from its original sources, "
                     "not from any rejected candidate. Address validation_errors or repair_hint before resubmitting. "
                     "If execution failed, revise the synchronization logic as well; valid edit formatting is not proof of correctness.")
    enriched = original.model_copy(deep=True)
    enriched.prompt = "\n".join(parts)
    enriched.metadata["failure_evidence"] = failure.model_dump(mode="json")
    return enriched
