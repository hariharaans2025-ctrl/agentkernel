"""Small opt-in real inference probes. No benchmark loop or synthetic verification."""
import tempfile
from pathlib import Path

from agentkernel.core.enums import ExecutionStatus, InferenceTier
from agentkernel.core.models import TaskRequest, VerificationResult
from agentkernel.observability import configured_observer, span, trace
from agentkernel.providers.local_rtx import LocalRTXProvider
from agentkernel.providers.nebius_token_factory import NebiusTokenFactoryProvider
from agentkernel.runtime.kernel import AgentKernel
from agentkernel.telemetry.recorder import TelemetryRecorder

from .analyzer.fingerprints import fingerprints
from .analyzer.routing import ConcurrencyRouter
from .campaign.manager import StressCampaignManager
from .compile.compiler import CCompiler
from .models import ConcurrencyTask
from .repair.patch_parser import parse_repair, validation_details
from .repair.prompts import SYSTEM_PROMPT, repair_prompt, triage_prompt
from .sandbox.local import safe_path
from .sandbox.nebius import NebiusSandboxBackend
from .verification.repair_verifier import TriageVerifier


class RepairContractVerifier:
    async def verify(self, task, inference, attempt_history):
        if inference.status == ExecutionStatus.FAILED:
            return VerificationResult(passed=False, retryable=inference.metadata.get("retryable", True),
                                      reason="Repair inference unavailable.", evidence={"error": inference.metadata.get("error_code")},
                                      verifier_name="repair_contract_only")
        try:
            if inference.status == ExecutionStatus.FAILED:
                raise ValueError
            sources = task.metadata.get("concurrency_context", {}).get("sources")
            proposal = parse_repair(inference.output_text, sources)
            if sources is not None:
                # Validate actual applicability without compiling or running the candidate.
                from .repair.patch_applier import UnifiedDiffApplier
                with tempfile.TemporaryDirectory(prefix="agentkernel-contract-") as directory:
                    root = Path(directory)
                    for name, source in sources.items():
                        path = safe_path(root, name)
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(source, encoding="utf-8", newline="")
                    applied = UnifiedDiffApplier().apply(root, proposal.patch, list(sources))
                if not applied.success:
                    return VerificationResult(passed=False, reason="Patch rejected: " + (applied.error or "unknown"),
                        evidence={"error_code": "invalid_model_output", "patch_validation": applied.model_dump()},
                        retryable=not (attempt_history and attempt_history[-1].verification_evidence.get("error_code") == "invalid_model_output"),
                        verifier_name="repair_contract_only")
            return VerificationResult(passed=True, reason="Repair contract validated; the candidate has NOT been execution-verified.",
                                      evidence=proposal.model_dump(), verifier_name="repair_contract_only")
        except ValueError as exc:
            return VerificationResult(passed=False, reason="Invalid repair JSON. Return the specified edit contract with exact ORIGINAL source blocks; inspect validation_errors.",
                evidence={"error_code": "invalid_model_output", "validation_errors": validation_details(exc)},
                retryable=not (attempt_history and attempt_history[-1].verification_evidence.get("error_code") == "invalid_model_output"),
                verifier_name="repair_contract_only")


def model_metrics(execution) -> list[dict]:
    return [{"tier": a.tier.value, "model_id": a.model, "status": a.status.value,
             "input_tokens": a.metadata.get("actual_input_tokens"), "output_tokens": a.metadata.get("actual_output_tokens"),
             "latency_ms": a.latency_ms, "retry_count": a.metadata.get("retry_count", 0),
             "request_id": a.metadata.get("request_id"), "finish_reason": a.metadata.get("finish_reason"),
             "cost_usd": a.estimated_cost_usd, "error_code": a.metadata.get("error_code"),
             "reasoning_tokens": a.metadata.get("actual_reasoning_tokens"),
             "requested_max_output_tokens": a.metadata.get("requested_max_output_tokens"),
             "requested_enable_thinking": a.metadata.get("requested_enable_thinking"),
             "error_hint": a.metadata.get("error_hint"),
             "structured_valid": a.verification_status == "PASSED"} for a in execution.attempts]


async def smoke(tier: str, *, task: ConcurrencyTask | None = None, provider=None, observer=None, telemetry=None) -> dict:
    provider = provider or NebiusTokenFactoryProvider()
    observer = observer or configured_observer()
    telemetry = telemetry or TelemetryRecorder()
    report = {"smoke": tier, "status": "not_started", "inference_mode": "real", "calls": [],
              "candidate_execution_verified": False}
    async def call(phase, selected, context, verifier):
        request = TaskRequest(task_id=task.task_id if task else "nano-smoke", task_type="concurrency_" + phase,
            prompt=triage_prompt(context) if phase == "triage" else repair_prompt(context),
            metadata={"phase": phase, "system_prompt": SYSTEM_PROMPT, "concurrency_context": context,
                "structured_output": True, "max_output_tokens": 768 if phase == "triage" else 4096,
                "inference_span_names": {"NANO": "nano_triage", "SUPER": "super_diagnosis"}})
        result = await AgentKernel(ConcurrencyRouter(selected), LocalRTXProvider(), provider, telemetry, verifier,
                                   max_attempts=2, tier_schedule=(selected,)).execute(request)
        report["calls"].extend(model_metrics(result))
        return result
    try:
        async with trace("NanoSmokeTest" if tier == "nano" else "SuperSmokeTest", observer,
                         task_id=task.task_id if task else "nano-smoke", synthetic_evidence=tier == "nano") as root:
            if tier == "nano":
                context = {"baseline": {"total_runs": 100, "failed_runs": 9,
                    "counts": {"PASS": 91, "TIMEOUT": 9},
                    "representative_runs": [{"run_id": "example:1", "classification": "TIMEOUT"}]},
                    "fingerprints": [{"pattern": "cyclic_lock_wait", "lock_orders": [["A", "B"], ["B", "A"]]}],
                    "synthetic_evidence": True}
                triage = await call("triage", InferenceTier.NANO, context, TriageVerifier())
                report.update(status="passed" if triage.success else "failed", stopped_reason=triage.stopped_reason,
                              structured_output=triage.attempts[-1].verification_evidence if triage.attempts else None,
                              evidence_origin="synthetic protocol example; no program executions claimed")
            else:
                if task is None:
                    raise ValueError("Super smoke requires one trusted fixture")
                async with NebiusSandboxBackend() as sandbox:
                    await sandbox.upload_project(task.workspace, task.source_files + task.support_files)
                    async with span("baseline_compile") as observed:
                        build = await CCompiler().compile(task, sandbox)
                        observed.update(build_success=build.success)
                        await observed.feedback(build_success=build.success)
                    report["build"] = build.model_dump()
                    if not build.success:
                        report["status"] = "execution_blocked" if build.metadata.get("execution_policy_blocked") else "build_failed"
                    else:
                        async with span("baseline_stress_campaign") as observed:
                            baseline = await StressCampaignManager().run(task, sandbox)
                            observed.update(baseline_runs=len(baseline.runs), baseline_passes=baseline.counts.get("PASS", 0),
                                            infrastructure_failures=baseline.infrastructure_failures)
                        report["baseline"] = baseline.compact()
                        if baseline.execution_blocked:
                            report["status"] = "execution_blocked"
                        elif not baseline.failed_runs or baseline.infrastructure_failures == len(baseline.runs):
                            report["status"] = "no_usable_program_failure"
                        else:
                            async with span("fingerprint_analysis"):
                                normalized = [f.model_dump(mode="json") for f in fingerprints(baseline)]
                            context = {"baseline": baseline.compact(), "fingerprints": normalized}
                            triage = await call("triage", InferenceTier.NANO, context, TriageVerifier())
                            if not triage.success:
                                report.update(status="failed", stopped_reason=triage.stopped_reason)
                            else:
                                sources = {name: safe_path(task.workspace, name).read_text(encoding="utf-8") for name in task.source_files}
                                if sum(len(text) for text in sources.values()) > 120000:
                                    raise ValueError("Source context limit exceeded")
                                context.update(nano_summary=triage.attempts[-1].verification_evidence,
                                               sources=sources, build_command=task.build_command)
                                repair = await call("repair", InferenceTier.SUPER, context, RepairContractVerifier())
                                report.update(status="passed" if repair.success else "failed", stopped_reason=repair.stopped_reason,
                                    structured_output=repair.attempts[-1].verification_evidence if repair.attempts else None)
            root.update(status=report["status"], structured_valid=report["status"] == "passed")
    finally:
        report["observability"] = await observer.flush()
    return report
